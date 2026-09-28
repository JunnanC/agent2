import asyncio
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlsplit

import httpx

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "education_experiment_platform.settings.local")

from django.conf import settings  # noqa: E402

WORKSPACE_CAPABILITIES = frozenset({"webide", "notebook", "terminal", "preview"})
HOP_HEADERS = frozenset({
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
})
FORWARD_HEADERS = frozenset({
    b"accept",
    b"accept-encoding",
    b"accept-language",
    b"content-type",
    b"if-match",
    b"if-none-match",
    b"range",
    b"user-agent",
})


class GatewayDenied(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _headers(scope: Mapping[str, Any]) -> dict[bytes, bytes]:
    return {key.lower(): value for key, value in scope.get("headers", [])}


def _cookie(headers: Mapping[bytes, bytes], name: str) -> str:
    jar = SimpleCookie()
    try:
        jar.load(headers.get(b"cookie", b"").decode("latin-1"))
    except Exception:
        return ""
    value = jar.get(name)
    return value.value if value else ""


def _origin_allowed(scope: Mapping[str, Any], headers: Mapping[bytes, bytes]) -> bool:
    origin = headers.get(b"origin", b"").decode("latin-1").rstrip("/")
    allowed = {str(item).rstrip("/") for item in settings.WORKSPACE_ALLOWED_ORIGINS}
    if origin:
        return origin in allowed
    fetch_site = headers.get(b"sec-fetch-site", b"").decode("ascii", "ignore").casefold()
    if fetch_site == "cross-site":
        return False
    host = headers.get(b"host", b"").decode("latin-1").split(":", 1)[0].casefold()
    return bool(host) and any(urlsplit(item).hostname == host for item in allowed)


def _workspace_path(path: str) -> tuple[str, str | None, str]:
    parts = path.split("/")
    if len(parts) < 3 or parts[1] != "workspace" or not parts[2]:
        raise GatewayDenied("WORKSPACE_PATH_INVALID", 404)
    capability = parts[3].casefold() if len(parts) > 3 and parts[3] else None
    tail = "/".join(parts[4:]) if len(parts) > 4 else ""
    return parts[2], capability, tail


async def _authorize(
    *, session_id: str, token: str, capability: str | None, portal_session_key: str
) -> str:
    headers = {
        "X-Workspace-Internal-Key": settings.WORKSPACE_INTERNAL_KEY,
        "X-Workspace-Session": session_id,
        "X-Workspace-Token": token,
        "X-Portal-Session": portal_session_key,
    }
    if capability:
        headers["X-Workspace-Capability"] = capability
    try:
        async with httpx.AsyncClient(timeout=settings.WORKSPACE_UPSTREAM_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.WORKSPACE_AUTHORITY_URL.rstrip('/')}/internal/workspace-authorize",
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise GatewayDenied("WORKSPACE_AUTHORITY_UNAVAILABLE", 503) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code != 200:
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        raise GatewayDenied(
            str(error.get("code", "WORKSPACE_SESSION_INVALID")), response.status_code
        )
    endpoint = str(payload.get("data", {}).get("endpoint", ""))
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise GatewayDenied("WORKSPACE_UPSTREAM_INVALID", 503)
    return endpoint.rstrip("/")


async def _send_error(
    send: Callable[[dict[str, Any]], Awaitable[None]], code: str, status: int
) -> None:
    payload = json.dumps(
        {"error": {"code": code, "message": "Workspace request denied", "retryable": False}},
        separators=(",", ":"),
    ).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")],
    })
    await send({"type": "http.response.body", "body": payload})


async def _body(receive: Callable[[], Awaitable[dict[str, Any]]]) -> AsyncIterator[bytes]:
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return
        body = message.get("body", b"")
        if body:
            yield body
        if not message.get("more_body", False):
            return


async def _proxy_http(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    upstream: str,
    capability: str,
    tail: str,
) -> None:
    query = scope.get("query_string", b"").decode("ascii", "ignore")
    url = f"{upstream}/{capability}/{tail}"
    if query:
        url = f"{url}?{query}"
    request_headers = [
        (key.decode("latin-1"), value.decode("latin-1"))
        for key, value in scope.get("headers", [])
        if key.lower() in FORWARD_HEADERS
    ]
    request_headers.append(
        (
            "x-forwarded-prefix",
            f"/workspace/{scope['workspace_session']}/{capability}",
        )
    )
    timeout = float(settings.WORKSPACE_UPSTREAM_TIMEOUT_SECONDS)
    async with (
        httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client,
        client.stream(
            str(scope.get("method", "GET")),
            url,
            headers=request_headers,
            content=_body(receive),
        ) as response,
    ):
        response_headers = [
            (key.encode("latin-1"), value.encode("latin-1"))
            for key, value in response.headers.multi_items()
            if key.encode("latin-1").lower() not in HOP_HEADERS
            and key.casefold() != "set-cookie"
        ]
        response_headers.append((b"cache-control", b"private, no-store"))
        await send({
            "type": "http.response.start",
            "status": response.status_code,
            "headers": response_headers,
        })
        async for chunk in response.aiter_raw():
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b""})


async def _proxy_websocket(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    upstream: str,
    capability: str,
    tail: str,
) -> None:
    from websockets.asyncio.client import connect

    query = scope.get("query_string", b"").decode("ascii", "ignore")
    target = f"ws://{urlsplit(upstream).netloc}/{capability}/{tail}"
    if query:
        target = f"{target}?{query}"
    first = await receive()
    if first["type"] != "websocket.connect":
        return
    try:
        async with connect(
            target,
            subprotocols=scope.get("subprotocols") or None,
            open_timeout=float(settings.WORKSPACE_UPSTREAM_TIMEOUT_SECONDS),
        ) as websocket:
            await send({"type": "websocket.accept", "subprotocol": websocket.subprotocol})

            async def browser_to_upstream() -> None:
                while True:
                    message = await receive()
                    if message["type"] == "websocket.disconnect":
                        await websocket.close()
                        return
                    if message.get("text") is not None:
                        await websocket.send(message["text"])
                    elif message.get("bytes") is not None:
                        await websocket.send(message["bytes"])

            async def upstream_to_browser() -> None:
                async for message in websocket:
                    key = "text" if isinstance(message, str) else "bytes"
                    await send({"type": "websocket.send", key: message})

            tasks = {
                asyncio.create_task(browser_to_upstream()),
                asyncio.create_task(upstream_to_browser()),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
    except Exception:
        await send({"type": "websocket.close", "code": 1011})


async def _proxy_operation(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    session_id: str,
    token: str,
) -> None:
    request_headers = [
        (key.decode("latin-1"), value.decode("latin-1"))
        for key, value in scope.get("headers", [])
        if key.lower() in FORWARD_HEADERS
    ]
    request_headers.extend([
        ("x-portal", "USER"),
        ("x-workspace-internal-key", settings.WORKSPACE_INTERNAL_KEY),
        ("x-workspace-token", token),
    ])
    url = f"{settings.WORKSPACE_AUTHORITY_URL.rstrip('/')}/workspace/{session_id}/operations"
    async with (
        httpx.AsyncClient(
            timeout=float(settings.WORKSPACE_UPSTREAM_TIMEOUT_SECONDS), follow_redirects=False
        ) as client,
        client.stream(
            str(scope.get("method", "POST")),
            url,
            headers=request_headers,
            content=_body(receive),
        ) as response,
    ):
        response_headers = [
            (key.encode("latin-1"), value.encode("latin-1"))
            for key, value in response.headers.multi_items()
            if key.encode("latin-1").lower() not in HOP_HEADERS
        ]
        await send({
            "type": "http.response.start",
            "status": response.status_code,
            "headers": response_headers,
        })
        async for chunk in response.aiter_raw():
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b""})


async def application(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    if scope.get("path") == "/healthz":
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
        return
    if scope.get("type") not in {"http", "websocket"}:
        return
    headers = _headers(scope)
    try:
        if not _origin_allowed(scope, headers):
            raise GatewayDenied("WORKSPACE_ORIGIN_DENIED", 403)
        session_id, capability, tail = _workspace_path(str(scope.get("path", "")))
        if (
            capability is not None
            and capability not in WORKSPACE_CAPABILITIES
            and capability != "operations"
        ):
            raise GatewayDenied("WORKSPACE_CAPABILITY_DENIED", 403)
        token = _cookie(headers, settings.WORKSPACE_COOKIE_NAME) or headers.get(
            b"x-workspace-token", b""
        ).decode("latin-1")
        portal_key = _cookie(headers, settings.SESSION_COOKIE_NAME)
        upstream = await _authorize(
            session_id=session_id,
            token=token,
            capability=capability if capability in WORKSPACE_CAPABILITIES else None,
            portal_session_key=portal_key,
        )
        scope["workspace_session"] = session_id
        if capability == "operations" and scope["type"] == "http":
            await _proxy_operation(
                scope, receive, send, session_id=session_id, token=token
            )
            return
        if capability is None:
            raise GatewayDenied("WORKSPACE_PATH_INVALID", 404)
        if scope["type"] == "websocket":
            await _proxy_websocket(
                scope, receive, send, upstream=upstream, capability=capability, tail=tail
            )
        else:
            await _proxy_http(
                scope, receive, send, upstream=upstream, capability=capability, tail=tail
            )
    except GatewayDenied as exc:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4403})
        else:
            await _send_error(send, exc.code, exc.status)
    except (httpx.HTTPError, OSError):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1013})
        else:
            await _send_error(send, "WORKSPACE_UPSTREAM_UNAVAILABLE", 503)

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings

from education_experiment_platform.workspace_gateway import (
    GatewayDenied,
    _authorize,
    _origin_allowed,
    _workspace_path,
    application,
)


class WorkspaceGatewayContractTests(SimpleTestCase):
    def test_workspace_path_only_accepts_session_and_known_capability_shape(self) -> None:
        self.assertEqual(
            _workspace_path("/workspace/session-1/webide/index.html"),
            ("session-1", "webide", "index.html"),
        )
        with self.assertRaises(GatewayDenied):
            _workspace_path("/api/v2/tasks/task-1")

    @override_settings(WORKSPACE_ALLOWED_ORIGINS=["https://student.example.edu"])
    def test_origin_is_allowlisted_and_cross_site_without_origin_is_denied(self) -> None:
        allowed = {b"origin": b"https://student.example.edu", b"host": b"student.example.edu"}
        denied = {b"origin": b"https://evil.example", b"host": b"student.example.edu"}
        cross_site = {
            b"host": b"student.example.edu",
            b"sec-fetch-site": b"cross-site",
        }
        self.assertTrue(_origin_allowed({}, allowed))
        self.assertFalse(_origin_allowed({}, denied))
        self.assertFalse(_origin_allowed({}, cross_site))

    @override_settings(WORKSPACE_ALLOWED_ORIGINS=["https://student.example.edu"])
    def test_asgi_application_rejects_bad_origin_before_authority_call(self) -> None:
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b""}

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/workspace/session-1/webide/",
            "headers": [
                (b"host", b"student.example.edu"),
                (b"origin", b"https://evil.example"),
            ],
            "query_string": b"",
        }
        asyncio.run(application(scope, receive, send))

        self.assertEqual(sent[0]["status"], 403)
        self.assertIn(b"WORKSPACE_ORIGIN_DENIED", sent[1]["body"])

    @override_settings(WORKSPACE_UPSTREAM_TIMEOUT_SECONDS=1)
    def test_authority_response_cannot_supply_userinfo_or_non_http_upstream(self) -> None:
        class FakeResponse:
            status_code = 200

            def json(self) -> dict[str, object]:
                return {"data": {"endpoint": "http://user:password@runtime:8080"}}

        class FakeClient:
            async def __aenter__(self) -> FakeClient:
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def post(self, *_args: object, **_kwargs: object) -> FakeResponse:
                return FakeResponse()

        async def run() -> None:
            with (
                patch.object(httpx, "AsyncClient", return_value=FakeClient()),
                self.assertRaises(GatewayDenied) as raised,
            ):
                await _authorize(
                    session_id="session-1",
                    token="ticket",
                    capability="webide",
                    portal_session_key="portal-session",
                )
            self.assertEqual(raised.exception.code, "WORKSPACE_UPSTREAM_INVALID")

        asyncio.run(run())

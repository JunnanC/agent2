"""Image-level checks for the authenticated workspace contract.

This file is mounted into the running image by scripts/verify/workspace-image.ps1. It uses
only the Python standard library shipped in the workspace image.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = "127.0.0.1"
PORT = 8080
TOKEN_HEADER = "X-Workspace-Upstream-Token"
TOKEN_FILE = "/run/secrets/workspace_upstream_token"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def fetch(path: str, token: str | None = None, *, follow_redirects: bool = True):
    headers = {TOKEN_HEADER: token} if token is not None else {}
    request = urllib.request.Request(f"http://{HOST}:{PORT}{path}", headers=headers)
    opener = (
        urllib.request.build_opener()
        if follow_redirects
        else urllib.request.build_opener(NoRedirect)
    )
    try:
        with opener.open(request, timeout=10) as response:
            return (
                response.status,
                dict(response.headers.items()),
                response.read(),
                response.geturl(),
            )
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers.items()), error.read(), error.geturl()


def assert_listener(port: int, expected_address: str) -> None:
    expected_port = f"{port:04X}"
    listeners: set[str] = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        with open(table, encoding="ascii") as handle:
            listeners.update(
                local_address
                for line in handle.readlines()[1:]
                for local_address, state in [(line.split()[1], line.split()[3])]
                if state == "0A" and local_address.endswith(f":{expected_port}")
            )
    expected_ipv6 = {
        "00000000:1F90": "00000000000000000000000000000000:1F90",
        "0100007F:0BB8": "0000000000000000FFFF00000100007F:0BB8",
    }.get(expected_address)
    assert expected_address in listeners or expected_ipv6 in listeners, (port, listeners)


def websocket_upgrade(path: str, token: str) -> int:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        "Connection: Upgrade\r\n"
        "Upgrade: websocket\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Origin: http://{HOST}:{PORT}\r\n"
        f"{TOKEN_HEADER}: {token}\r\n\r\n"
    ).encode("ascii")
    with socket.create_connection((HOST, PORT), timeout=10) as connection:
        connection.sendall(request)
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = connection.recv(4096)
            if not chunk:
                break
            response += chunk
    status_line = response.split(b"\r\n", 1)[0]
    match = re.fullmatch(rb"HTTP/1\.[01] (\d{3}) .+", status_line)
    assert match is not None, response[:512]
    status = int(match.group(1))
    if status == http.client.SWITCHING_PROTOCOLS:
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        )
        assert expected.lower() in response.lower(), response[:512]
    return status


def main() -> None:
    with open(TOKEN_FILE, encoding="utf-8") as handle:
        token = handle.read().strip()
    assert len(token) >= 32

    health_status, health_headers, health_body, _ = fetch("/healthz")
    assert health_status == 200
    assert health_body == b"ok"
    assert health_headers.get("Cache-Control") == "no-store"

    for rejected_token in (None, "incorrect-upstream-token"):
        for protected_path in ("/webide/", "/terminal/"):
            status, _, body, _ = fetch(protected_path, rejected_token)
            assert status == 403, (protected_path, rejected_token, status, body[:200])

    redirect_status, redirect_headers, _, _ = fetch("/webide", token, follow_redirects=False)
    assert redirect_status == 308
    assert redirect_headers.get("Location") == "/webide/"

    status, _, html, final_url = fetch("/webide/", token)
    assert status == 200
    final_parts = urllib.parse.urlsplit(final_url)
    assert final_parts.netloc == f"{HOST}:{PORT}", final_url
    assert final_parts.path.endswith("/webide/")
    decoded_html = html.decode("utf-8")
    assert "code-server" in decoded_html.lower() or "workbench" in decoded_html.lower()

    asset_matches = re.findall(r"(?:src|href)=[\"']([^\"']+)[\"']", decoded_html)
    asset_url = next(
        urllib.parse.urljoin(final_url, candidate)
        for candidate in asset_matches
        if "static" in candidate and not candidate.startswith(("data:", "http://", "https://"))
    )
    asset_path = urllib.parse.urlsplit(asset_url).path
    asset_status, asset_headers, asset_body, _ = fetch(asset_path, token)
    assert asset_status == 200, (asset_path, asset_status)
    assert len(asset_body) > 100
    assert asset_headers.get("Content-Type")

    websocket_status = websocket_upgrade("/webide/websocket", token)
    assert websocket_status == http.client.SWITCHING_PROTOCOLS, websocket_status

    for unsupported in ("/notebook/", "/preview/"):
        unsupported_status, _, _, _ = fetch(unsupported, token)
        assert unsupported_status == 404, (unsupported, unsupported_status)

    terminal_status, terminal_headers, terminal_html, _ = fetch("/terminal/", token)
    assert terminal_status == 200, (terminal_status, terminal_html[:200])
    assert terminal_headers.get("Content-Type", "").startswith("text/html"), terminal_headers
    decoded_terminal = terminal_html.decode("utf-8", errors="replace")
    assert "<title>ttyd - Terminal</title>" in decoded_terminal, decoded_terminal[:200]
    assert "new WebSocket" in decoded_terminal

    terminal_ws_status = websocket_upgrade("/terminal/ws", token)
    assert terminal_ws_status == http.client.SWITCHING_PROTOCOLS, terminal_ws_status

    assert os.geteuid() == 10001
    assert sys.version_info[:3] == (3, 14, 0), sys.version
    assert_listener(8080, "00000000:1F90")
    assert_listener(3000, "0100007F:0BB8")
    assert_listener(7681, "0100007F:1E01")

    with open("/workspace/main.py", "w", encoding="utf-8") as handle:
        handle.write("print('workspace-ready')\n")

    for forbidden_path in ("/rootfs-write-test", "/opt/workspace-extensions/write-test"):
        try:
            with open(forbidden_path, "w", encoding="utf-8") as handle:
                handle.write("must fail")
        except OSError:
            pass
        else:
            raise AssertionError(f"unexpected write access: {forbidden_path}")

    print(
        json.dumps(
            {
                "capabilities": {
                    "webide": True,
                    "notebook": False,
                    "terminal": True,
                    "preview": False,
                },
                "health": "passed",
                "http": "passed",
                "non_root_uid": os.geteuid(),
                "python": ".".join(str(part) for part in sys.version_info[:3]),
                "read_only_rootfs": "passed",
                "static_asset": asset_path,
                "terminal_http": "passed",
                "terminal_websocket": "passed",
                "websocket": "passed",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.machinery import SourceFileLoader
from pathlib import Path


module = SourceFileLoader(
    "check_portal_entry", str(Path(__file__).with_name("check-portal-entry.py"))
).load_module()


class PortalEntryTests(unittest.TestCase):
    def test_hostname_routing_and_cookie_router_regression(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.headers["Host"] == "redirect.example":
                    self.send_response(302)
                    self.send_header("Location", "/login")
                    self.end_headers()
                    return
                portal = {"student.example": "USER", "teacher.example": "TEACHING",
                          "admin.example": "PLATFORM"}.get(self.headers["Host"])
                if self.headers["Host"] == "broken.example":
                    portal = self.headers["Cookie"].split("=", 1)[1]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"data": {"portal": portal}}).encode())

            def log_message(self, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for host, portal in (("student.example", "USER"), ("teacher.example", "TEACHING"),
                                 ("admin.example", "PLATFORM")):
                module.check(host, portal, port=server.server_port)
            with self.assertRaisesRegex(SystemExit, "expected USER, got wrong-portal"):
                module.check("broken.example", "USER", port=server.server_port)
            with self.assertRaisesRegex(SystemExit, "expected 200, got 302"):
                module.check("redirect.example", "USER", port=server.server_port)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

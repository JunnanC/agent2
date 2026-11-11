"""Check the public host router without DNS, cookies, or redirect following."""

import http.client
import json
import sys


def check(host: str, portal: str, *, address: str = "127.0.0.1", port: int = 80) -> None:
    connection = http.client.HTTPConnection(address, port, timeout=15)
    try:
        # A stale selector cookie must never override the public hostname.
        connection.request("GET", "/api/v2/health", headers={
            "Host": host, "Cookie": "portal=wrong-portal",
        })
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise SystemExit(f"{host}: expected 200, got {response.status}")
        actual = json.loads(body)["data"]["portal"]
        if actual != portal:
            raise SystemExit(f"{host}: expected {portal}, got {actual}")
    finally:
        connection.close()


def main(env_path: str) -> None:
    values = {}
    with open(env_path, encoding="utf-8") as file:
        for line in file:
            key, separator, value = line.strip().partition("=")
            if separator and not key.startswith("#"):
                values[key] = value.strip("\"'")
    for key, portal in (("STUDENT_HOST", "USER"), ("TEACHER_HOST", "TEACHING"),
                        ("ADMIN_HOST", "PLATFORM")):
        check(values[key], portal)


if __name__ == "__main__":
    main(sys.argv[1])

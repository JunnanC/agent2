"""Fail deployment when portal HTTPS hosts are missing from Django CSRF origins."""

import json
import sys


def main(env_path: str, compose_path: str) -> None:
    values = {}
    with open(env_path, encoding="utf-8") as file:
        for line in file:
            key, separator, value = line.strip().partition("=")
            if separator and not key.startswith("#"):
                values[key] = value.strip("\"'")
    with open(compose_path, encoding="utf-8") as file:
        services = json.load(file)["services"]
    hosts = [values.get(key, "") for key in ("STUDENT_HOST", "TEACHER_HOST", "ADMIN_HOST")]
    if any(not host for host in hosts):
        raise SystemExit("STUDENT_HOST, TEACHER_HOST and ADMIN_HOST are required")
    origins = {
        value.strip().rstrip("/")
        for value in services["django"]["environment"]["DJANGO_TRUSTED_ORIGINS"].split(",")
    }
    missing = [
        f"https://{host}" for host in hosts if f"https://{host}" not in origins
    ]
    if missing:
        raise SystemExit("Missing DJANGO_TRUSTED_ORIGINS: " + ", ".join(missing))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

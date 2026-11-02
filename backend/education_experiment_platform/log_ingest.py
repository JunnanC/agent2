import json
import os
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, MongoClient

from apps.core.redaction import redact


class LogHandler(BaseHTTPRequestHandler):
    client: MongoClient[dict[str, Any]]
    database: str
    collection: str

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def do_POST(self) -> None:
        if self.path != "/logs":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = min(int(self.headers.get("Content-Length", "0")), 1_048_576)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        records: list[dict[str, Any]] = []
        for line in body.splitlines():
            if not line.strip():
                continue
            parsed = json.loads(line)
            record = parsed if isinstance(parsed, dict) else {"message": str(parsed)}
            record = redact(record)
            if "created_at" in record:
                record["event_timestamp"] = record.pop("created_at")
            record["created_at"] = datetime.now(UTC)
            records.append(record)
        try:
            if records:
                self.client[self.database][self.collection].insert_many(records, ordered=False)
        except Exception:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        self.send_response(HTTPStatus.ACCEPTED)
        self.end_headers()


def main() -> None:
    uri_file = os.getenv("MONGODB_URI_FILE")
    uri = (
        Path(uri_file).read_text(encoding="utf-8").strip()
        if uri_file
        else os.environ["MONGODB_URI"]
    )
    database = os.getenv("MONGODB_LOG_DATABASE", "observability")
    collection = os.getenv("MONGODB_LOG_COLLECTION", "runtime_logs")
    ttl_days = int(os.getenv("MONGODB_LOG_TTL_DAYS", "30"))
    client: MongoClient[dict[str, Any]] = MongoClient(uri, serverSelectionTimeoutMS=3000)
    logs = client[database][collection]
    logs.create_index([("created_at", ASCENDING)], expireAfterSeconds=ttl_days * 86400)
    for field in ("service", "level", "trace_id", "course_id", "resource_id"):
        logs.create_index([(field, ASCENDING)])
    LogHandler.client = client
    LogHandler.database = database
    LogHandler.collection = collection
    server = ThreadingHTTPServer(("0.0.0.0", 8081), LogHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()

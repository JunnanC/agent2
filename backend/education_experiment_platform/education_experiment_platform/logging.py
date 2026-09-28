import contextvars
import json
import logging
from datetime import UTC, datetime

from apps.core.redaction import redact

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
portal_var: contextvars.ContextVar[str] = contextvars.ContextVar("portal", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": "django",
            "logger": record.name,
            "message": redact(record.getMessage()),
            "trace_id": getattr(record, "trace_id", "") or trace_id_var.get(),
            "portal": portal_var.get(),
        }
        for field in (
            "actor_ref",
            "course_ref",
            "task_ref",
            "instance_ref",
            "execution_run_ref",
            "container_ref",
            "resource_type",
            "resource_ref",
            "action",
            "result",
            "error_code",
            "duration_ms",
            "runtime_count",
            "transient_count",
            "orphan_runtime_count",
            "orphan_judge_count",
            "orphan_volume_count",
            "delivered",
            "processed",
        ):
            if hasattr(record, field):
                payload[field] = redact(getattr(record, field))
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

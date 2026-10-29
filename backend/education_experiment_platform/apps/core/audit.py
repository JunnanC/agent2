import hashlib
from typing import Any

from .identifiers import normalize_trace_id
from .models import AuditLog, FailureRecord
from .redaction import redact


def hash_client_ip(client_ip: str, *, salt: str) -> str:
    if not client_ip:
        return ""
    return hashlib.sha256(f"{salt}:{client_ip}".encode()).hexdigest()


def append_audit(
    *,
    actor_ref: str,
    actor_portal: str,
    actor_context: dict[str, Any],
    action: str,
    target_type: str,
    target_ref: str,
    result: str,
    trace_id: str,
    course_ref: str = "",
    before: Any = None,
    after: Any = None,
    error_code: str = "",
    client_ip_hash: str = "",
    user_agent_summary: str = "",
) -> AuditLog:
    return AuditLog.objects.create(
        actor_ref=actor_ref,
        actor_portal=actor_portal,
        actor_context=redact(actor_context),
        action=action,
        course_ref=course_ref,
        target_type=target_type,
        target_ref=target_ref,
        before_masked=redact(before),
        after_masked=redact(after),
        result=result,
        error_code=error_code,
        client_ip_hash=client_ip_hash,
        user_agent_summary=user_agent_summary[:255],
        trace_id=normalize_trace_id(trace_id),
    )


def append_failure(
    *,
    failure_type: str,
    subject_type: str,
    subject_ref: str,
    error_code: str,
    message: str,
    detail: dict[str, Any],
    retryable: bool,
    trace_id: str,
) -> FailureRecord:
    return FailureRecord.objects.create(
        failure_type=failure_type,
        subject_type=subject_type,
        subject_ref=subject_ref,
        error_code=error_code,
        message_masked=redact(message),
        detail_masked=redact(detail),
        retryable=retryable,
        trace_id=normalize_trace_id(trace_id),
    )

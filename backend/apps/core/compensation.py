import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .audit import append_failure
from .concurrency import compare_and_swap
from .models import CompensationTask
from .outbox import backoff_seconds
from .redaction import redact

CompensationHandler = Callable[[CompensationTask], None]
_handlers: dict[str, CompensationHandler] = {}


def register_compensation_handler(task_type: str, handler: CompensationHandler) -> None:
    if task_type in _handlers:
        raise ValueError(f"Compensation handler already registered: {task_type}")
    _handlers[task_type] = handler


def create_compensation(
    *,
    task_type: str,
    subject_type: str,
    subject_ref: str,
    payload: dict[str, Any],
    trace_id: str,
    max_attempts: int = 10,
) -> CompensationTask:
    return CompensationTask.objects.create(
        task_type=task_type,
        subject_type=subject_type,
        subject_ref=subject_ref,
        payload_masked=redact(payload),
        trace_id=trace_id,
        max_attempts=max_attempts,
    )


def claim_compensations(*, batch_size: int = 50, lease_seconds: int = 120) -> list[int]:
    now = timezone.now()
    token = uuid.uuid4()
    with transaction.atomic():
        queryset = (
            CompensationTask.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status__in=(CompensationTask.Status.PENDING, CompensationTask.Status.RETRY))
                | Q(status=CompensationTask.Status.IN_FLIGHT, lease_until__lt=now)
            )
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
            .order_by("created_at")[:batch_size]
        )
        claimed: list[int] = []
        for task in queryset:
            current = compare_and_swap(
                CompensationTask,
                pk=task.pk,
                expected_version=task.row_version,
                changes={
                    "status": CompensationTask.Status.IN_FLIGHT,
                    "lease_token": token,
                    "lease_until": now + timedelta(seconds=lease_seconds),
                    "attempt_count": task.attempt_count + 1,
                },
            )
            claimed.append(current.pk)
        return claimed


def run_compensation(task_id: object) -> None:
    task = CompensationTask.objects.get(pk=task_id)
    if task.status != CompensationTask.Status.IN_FLIGHT:
        return
    handler = _handlers.get(task.task_type)
    try:
        if handler is None:
            raise LookupError(f"No compensation handler registered for {task.task_type}")
        handler(task)
    except Exception as exc:
        next_status = (
            CompensationTask.Status.DEAD
            if task.attempt_count >= task.max_attempts
            else CompensationTask.Status.RETRY
        )
        failure = append_failure(
            failure_type="COMPENSATION",
            subject_type=task.subject_type,
            subject_ref=task.subject_ref,
            error_code="COMPENSATION_FAILED",
            message=str(redact(str(exc))),
            detail={"task_type": task.task_type},
            retryable=next_status != CompensationTask.Status.DEAD,
            trace_id=task.trace_id,
        )
        compare_and_swap(
            CompensationTask,
            pk=task.pk,
            expected_version=task.row_version,
            changes={
                "status": next_status,
                "next_attempt_at": (
                    None
                    if next_status == CompensationTask.Status.DEAD
                    else timezone.now() + timedelta(seconds=backoff_seconds(task.attempt_count))
                ),
                "lease_token": None,
                "lease_until": None,
                "last_failure": failure,
            },
        )
        return
    compare_and_swap(
        CompensationTask,
        pk=task.pk,
        expected_version=task.row_version,
        changes={
            "status": CompensationTask.Status.COMPLETED,
            "lease_token": None,
            "lease_until": None,
        },
    )

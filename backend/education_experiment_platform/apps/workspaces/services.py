import hashlib
import io
import json
import logging
import secrets
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.accounts.models import User
from apps.core.antivirus import AntivirusUnavailable, ClamAVScanner
from apps.core.assets import register_asset, set_scan_result
from apps.core.audit import append_audit, hash_client_ip
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict, StateConflict
from apps.core.idempotency import request_digest
from apps.core.models import FailureRecord, ObjectAsset
from apps.core.object_storage import iter_chunks, object_storage
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.core.redaction import redact
from apps.courses.models import Enrollment
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.experiments.services import transition_task
from apps.labtemplates.services import build_execution_command
from apps.provisioning.adapters import RuntimeAdapterFailure, runtime_for_driver
from apps.provisioning.metrics import (
    RUNTIME_ENGINE_UNAVAILABLE_TOTAL,
    RUNTIME_EXECUTION_DURATION,
    RUNTIME_EXECUTION_RESULTS,
    is_engine_unavailable,
)
from apps.provisioning.ports import RuntimeExecutionResult, RuntimeSpec

from . import events
from .errors import (
    AutosaveConflict,
    AutosaveStale,
    CheckpointStateConflict,
    WorkspaceCapabilityDenied,
    WorkspaceCaptureConflict,
    WorkspaceCaptureUnsupported,
    WorkspaceOperationDenied,
    WorkspaceScanUnavailable,
    WorkspaceSessionInvalid,
    WorkspaceSnapshotNotReady,
    WorkspaceStorageJobActive,
)
from .metrics import WORKSPACE_AUTOSAVES_TOTAL, WORKSPACE_SESSIONS_TOTAL
from .models import (
    OperationEvent,
    WorkspaceAutosaveLog,
    WorkspaceCheckpoint,
    WorkspaceExecutionRun,
    WorkspaceSession,
    WorkspaceSnapshot,
    WorkspaceStorageJob,
)
from .permissions import require_workspace_session, token_digest

logger = logging.getLogger("runtime.execution")

_STORAGE_JOB_TRANSITIONS: dict[str, set[str]] = {
    WorkspaceStorageJob.Status.QUEUED: {
        WorkspaceStorageJob.Status.RUNNING,
        WorkspaceStorageJob.Status.CANCELLED,
        WorkspaceStorageJob.Status.FAILED,
    },
    WorkspaceStorageJob.Status.RUNNING: {
        WorkspaceStorageJob.Status.RUNNING,
        WorkspaceStorageJob.Status.PASSED,
        WorkspaceStorageJob.Status.FAILED,
        WorkspaceStorageJob.Status.CANCELLED,
    },
    WorkspaceStorageJob.Status.PASSED: set(),
    WorkspaceStorageJob.Status.FAILED: set(),
    WorkspaceStorageJob.Status.CANCELLED: set(),
}

WORKSPACE_CAPABILITIES = (
    "webide",
    "notebook",
    "terminal",
    "preview",
    "snapshot",
    "checkpoint",
)


def _trace(context: Any) -> str:
    return str(getattr(context, "trace_id", ""))


def _actor_ref(actor: User | None, context: Any) -> str:
    return actor.public_id if actor is not None else str(getattr(context, "actor_ref", "worker"))


def _context(actor: User, context: Any) -> ActorContext:
    return ActorContext(
        actor_ref=actor.public_id,
        portal=str(getattr(context, "portal", "USER")),
        trace_id=_trace(context),
        client_ip=str(getattr(context, "client_ip", "")),
        user_agent=str(getattr(context, "user_agent", "")),
    )


def _audit(
    *,
    context: Any,
    actor: User | None,
    action: str,
    target_type: str,
    target_ref: str,
    course_ref: str,
    before: Any = None,
    after: Any = None,
    result: str = "SUCCEEDED",
    error_code: str = "",
) -> None:
    append_audit(
        actor_ref=_actor_ref(actor, context),
        actor_portal=str(getattr(context, "portal", "")),
        actor_context={},
        action=action,
        target_type=target_type,
        target_ref=target_ref,
        course_ref=course_ref,
        before=before,
        after=after,
        result=result,
        error_code=error_code,
        client_ip_hash=hash_client_ip(
            str(getattr(context, "client_ip", "")), salt=settings.AUDIT_IP_HASH_SALT
        ),
        user_agent_summary=str(getattr(context, "user_agent", "")),
        trace_id=_trace(context),
    )


def _emit(
    *, event_type: str, session: WorkspaceSession, payload: dict[str, Any], context: Any
) -> None:
    append_outbox_event(
        event_type=event_type,
        aggregate_type="workspace_session",
        aggregate_ref=session.public_id,
        payload={
            "session_id": session.public_id,
            "task_id": session.task.public_id,
            "course_id": session.course.public_id,
            **payload,
        },
        trace_id=_trace(context),
    )
    enqueue_relay_after_commit(trace_id=_trace(context))


def _ttl_seconds() -> int:
    return max(1, min(int(getattr(settings, "WORKSPACE_SESSION_TTL_SECONDS", 900)), 900))


def _new_token() -> tuple[str, str, str]:
    token = secrets.token_urlsafe(48)
    return token, secrets.token_hex(16), token_digest(token)


def _session_capabilities(task: ExperimentTask) -> dict[str, bool]:
    declared = task.template_version.workspace_capabilities or {}
    return {name: bool(declared.get(name, False)) for name in WORKSPACE_CAPABILITIES}


def _task_for_actor(*, task_id: str, actor: User) -> ExperimentTask:
    try:
        return (
            ExperimentTask.objects.select_for_update()
            .select_related(
                "course", "student", "enrollment", "publication", "template_version"
            )
            .get(public_id=task_id, student=actor)
        )
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def _assert_enterable(task: ExperimentTask) -> None:
    if task.enrollment.status != Enrollment.Status.ACTIVE:
        raise StateConflict(detail={"enrollment_status": task.enrollment.status})
    if task.publication.status != task.publication.Status.PUBLISHED:
        raise StateConflict(detail={"publication_status": task.publication.status})
    instance = getattr(task, "provisioning_instance", None)
    if instance is None or instance.status != "READY":
        raise StateConflict(detail={"instance_status": instance.status if instance else None})
    if task.status not in {
        ExperimentTask.Status.READY,
        ExperimentTask.Status.IN_PROGRESS,
        ExperimentTask.Status.REPORT_DRAFT,
    }:
        raise StateConflict(detail={"status": task.status})
    now = timezone.now()
    deadline = task.effective_deadline or task.publication.window_end
    if now < task.publication.window_start or now > deadline:
        raise StateConflict(
            detail={
                "window_start": task.publication.window_start,
                "effective_deadline": deadline,
            }
        )


@transaction.atomic
def enter_task(
    *, task_id: str, actor: User, expected_version: int, context: Any
) -> tuple[ExperimentTask, WorkspaceSession, str]:
    task = _task_for_actor(task_id=task_id, actor=actor)
    _assert_enterable(task)
    if task.status == ExperimentTask.Status.READY:
        task = transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.IN_PROGRESS,
            actor=actor,
            expected_version=expected_version,
            trigger="ENTER_WORKSPACE",
            reason="student entered workspace",
            context=_context(actor, context),
        )
    elif task.row_version != expected_version:
        raise RowVersionConflict(detail={"expected_row_version": expected_version})
    return issue_session(task=task, actor=actor, context=context)


@transaction.atomic
def issue_session(
    *, task: ExperimentTask, actor: User, context: Any
) -> tuple[ExperimentTask, WorkspaceSession, str]:
    task = (
        ExperimentTask.objects.select_for_update()
        .select_related(
            "course", "student", "enrollment", "publication", "template_version"
        )
        .get(pk=task.pk)
    )
    _assert_enterable(task)
    if task.student_id != actor.pk:
        raise ResourceNotFound()
    if task.publication.report_required:
        from apps.reports.services import initialize_report_draft

        initialize_report_draft(task=task, actor=actor, context=_context(actor, context))
    instance = getattr(task, "provisioning_instance", None)
    if instance is None:
        raise WorkspaceSessionInvalid()
    active = (
        WorkspaceSession.objects.select_for_update()
        .filter(task=task, student=actor, status=WorkspaceSession.Status.ACTIVE)
        .first()
    )
    token, jti, digest = _new_token()
    now = timezone.now()
    expiry = now + timedelta(seconds=_ttl_seconds())
    if active is not None:
        changed = compare_and_swap(
            WorkspaceSession,
            pk=active.pk,
            expected_version=active.row_version,
            changes={
                "jti": jti,
                "token_hash": digest,
                "expires_at": expiry,
                "last_seen_at": now,
                "status": WorkspaceSession.Status.ACTIVE,
                "revoked_at": None,
                "revoke_reason": "",
            },
        )
        session = changed  # type: ignore[assignment]
    else:
        try:
            session = WorkspaceSession.objects.create(
                task=task,
                student=actor,
                instance=instance,
                course=task.course,
                portal="USER",
                jti=jti,
                token_hash=digest,
                active_marker=f"{task.public_id}:ACTIVE",
                capabilities=_session_capabilities(task),
                status=WorkspaceSession.Status.ACTIVE,
                expires_at=expiry,
                last_seen_at=now,
            )
        except IntegrityError:
            active = WorkspaceSession.objects.select_for_update().get(
                task=task, active_marker=f"{task.public_id}:ACTIVE"
            )
            session = compare_and_swap(
                WorkspaceSession,
                pk=active.pk,
                expected_version=active.row_version,
                changes={
                    "jti": jti,
                    "token_hash": digest,
                    "expires_at": expiry,
                    "last_seen_at": now,
                },
            )
    _audit(
        context=context,
        actor=actor,
        action="workspace.session.enter",
        target_type="workspace_session",
        target_ref=session.public_id,
        course_ref=task.course.public_id,
        after={"task_id": task.public_id, "expires_at": expiry.isoformat()},
    )
    _emit(
        event_type=events.SESSION_CREATED,
        session=session,
        payload={"expires_at": expiry.isoformat()},
        context=context,
    )
    from .storage import create_initialization_job

    create_initialization_job(session=session, context=context)
    WORKSPACE_SESSIONS_TOTAL.labels(action="enter", result="succeeded").inc()
    return task, session, token


@transaction.atomic
def renew_session(
    *, session: WorkspaceSession, token: str, actor: User, context: Any
) -> tuple[WorkspaceSession, str]:
    session = (
        WorkspaceSession.objects.select_for_update()
        .select_related("task__enrollment", "task__publication", "course", "student", "instance")
        .get(pk=session.pk)
    )
    require_workspace_session(session=session, token=token, task_id=session.task.public_id)
    new_token, jti, digest = _new_token()
    expiry = timezone.now() + timedelta(seconds=_ttl_seconds())
    changed = compare_and_swap(
        WorkspaceSession,
        pk=session.pk,
        expected_version=session.row_version,
        changes={
            "jti": jti,
            "token_hash": digest,
            "expires_at": expiry,
            "last_seen_at": timezone.now(),
        },
    )
    _audit(
        context=context,
        actor=actor,
        action="workspace.session.renew",
        target_type="workspace_session",
        target_ref=session.public_id,
        course_ref=session.course.public_id,
        after={"expires_at": expiry.isoformat()},
    )
    _emit(
        event_type=events.SESSION_RENEWED,
        session=changed,
        payload={"expires_at": expiry.isoformat()},
        context=context,
    )
    return changed, new_token


@transaction.atomic
def revoke_session(
    *, session: WorkspaceSession, token: str, actor: User, expected_version: int, context: Any
) -> WorkspaceSession:
    session = (
        WorkspaceSession.objects.select_for_update()
        .select_related("task__enrollment", "task__publication", "course", "student", "instance")
        .get(pk=session.pk)
    )
    require_workspace_session(session=session, token=token, task_id=session.task.public_id)
    changed = compare_and_swap(
        WorkspaceSession,
        pk=session.pk,
        expected_version=expected_version,
        changes={
            "status": WorkspaceSession.Status.REVOKED,
            "active_marker": None,
            "revoked_at": timezone.now(),
            "revoke_reason": "student revoked",
        },
    )
    _audit(
        context=context,
        actor=actor,
        action="workspace.session.revoke",
        target_type="workspace_session",
        target_ref=session.public_id,
        course_ref=session.course.public_id,
        before={"status": session.status},
        after={"status": changed.status},
    )
    _emit(
        event_type=events.SESSION_REVOKED,
        session=changed,
        payload={"status": changed.status},
        context=context,
    )
    return changed


@transaction.atomic
def revoke_task_sessions(*, task_id: str, reason: str, context: Any) -> int:
    """Revoke every active ticket for a task without requiring the bearer token."""
    now = timezone.now()
    revoked = 0
    sessions = (
        WorkspaceSession.objects.select_for_update()
        .select_related("task", "course", "student", "instance")
        .filter(task__public_id=task_id, status=WorkspaceSession.Status.ACTIVE)
    )
    for session in sessions:
        changed = compare_and_swap(
            WorkspaceSession,
            pk=session.pk,
            expected_version=session.row_version,
            changes={
                "status": WorkspaceSession.Status.REVOKED,
                "active_marker": None,
                "revoked_at": now,
                "revoke_reason": reason.strip()[:255] or "task lifecycle cleanup",
            },
        )
        _audit(
            context=context,
            actor=None,
            action="workspace.session.system_revoke",
            target_type="workspace_session",
            target_ref=changed.public_id,
            course_ref=changed.course.public_id,
            before={"status": session.status},
            after={"status": changed.status, "reason": changed.revoke_reason},
        )
        _emit(
            event_type=events.SESSION_REVOKED,
            session=changed,
            payload={"status": changed.status, "reason": changed.revoke_reason},
            context=context,
        )
        revoked += 1
    return revoked


def _read_upload(upload: Any) -> tuple[io.BytesIO, int, str, str]:
    limit = int(getattr(settings, "WORKSPACE_SNAPSHOT_MAX_BYTES", 20 * 1024 * 1024))
    stream = io.BytesIO()
    size = 0
    for chunk in upload.chunks() if hasattr(upload, "chunks") else iter_chunks(upload):
        size += len(chunk)
        if size > limit:
            raise AutosaveConflict(detail={"size_bytes": size, "max_bytes": limit})
        stream.write(chunk)
    stream.seek(0)
    digest = hashlib.sha256(stream.getvalue()).hexdigest()
    media_type = str(getattr(upload, "content_type", "application/octet-stream"))[:255]
    allowed = getattr(
        settings,
        "WORKSPACE_SNAPSHOT_ALLOWED_MIME_TYPES",
        {"text/plain", "application/json", "application/octet-stream", "application/zip"},
    )
    if media_type not in allowed:
        raise AutosaveConflict(detail={"reason": "MIME_UNSUPPORTED", "media_type": media_type})
    prefix = stream.getvalue()[:4]
    if media_type == "application/zip" and not prefix.startswith(b"PK"):
        raise AutosaveConflict(detail={"reason": "MAGIC_MISMATCH", "media_type": media_type})
    if media_type in {"text/plain", "application/json"}:
        try:
            stream.getvalue().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AutosaveConflict(
                detail={"reason": "MAGIC_MISMATCH", "media_type": media_type}
            ) from exc
    return stream, size, digest, media_type or "application/octet-stream"


@transaction.atomic
def create_storage_job(
    *,
    task_id: str,
    actor: User,
    token: str,
    expected_version: int,
    kind: str,
    client_seq: int | None,
    base_version: int | None,
    snapshot_id: str | None,
    idempotency_key: str,
    request_payload: dict[str, Any],
    context: Any,
) -> tuple[WorkspaceSession, WorkspaceStorageJob]:
    """Declare a storage operation without performing external I/O.

    P16-A owns the durable request boundary.  Worker execution is deliberately
    left to the later storage-worker phase.
    """

    task = _task_for_actor(task_id=task_id, actor=actor)
    session = (
        WorkspaceSession.objects.select_for_update()
        .select_related(
            "task__enrollment",
            "task__publication",
            "student",
            "course",
            "instance",
        )
        .filter(task=task, student=actor, status=WorkspaceSession.Status.ACTIVE)
        .first()
    )
    if session is None:
        raise WorkspaceSessionInvalid()
    require_workspace_session(session=session, token=token, task_id=task_id)
    payload_digest = request_digest(request_payload)
    existing = WorkspaceStorageJob.objects.filter(
        session=session, idempotency_key=idempotency_key
    ).first()
    if existing is not None:
        if existing.request_digest != payload_digest:
            from apps.core.errors import IdempotencyKeyReused

            raise IdempotencyKeyReused()
        return session, existing
    if session.row_version != expected_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_version,
                "actual_row_version": session.row_version,
            }
        )

    driver = task.runtime_adapter_driver or (
        task.runtime_adapter.driver if task.runtime_adapter_id else "FAKE"
    )
    if driver == "FAKE":
        raise WorkspaceCaptureUnsupported(detail={"driver": driver, "kind": kind})

    if kind == WorkspaceStorageJob.Kind.CAPTURE:
        require_workspace_session(
            session=session, token=token, task_id=task_id, capability="snapshot"
        )
        if client_seq is None or base_version is None:
            raise WorkspaceCaptureConflict(
                detail={"client_seq": client_seq, "base_version": base_version}
            )
        if base_version != session.current_version:
            raise WorkspaceCaptureConflict(
                detail={"base_version": base_version, "current_version": session.current_version}
            )
        if snapshot_id:
            raise WorkspaceCaptureConflict(detail={"snapshot_id": "not_allowed_for_capture"})
        if WorkspaceStorageJob.objects.filter(
            task=task, client_seq=client_seq, kind=WorkspaceStorageJob.Kind.CAPTURE
        ).exists():
            raise WorkspaceCaptureConflict(detail={"client_seq": client_seq})
    elif kind == WorkspaceStorageJob.Kind.RESTORE:
        require_workspace_session(
            session=session, token=token, task_id=task_id, capability="checkpoint"
        )
        if client_seq is not None or base_version is not None:
            raise WorkspaceCaptureConflict(detail={"reason": "restore_fields_not_allowed"})
        try:
            source_snapshot = WorkspaceSnapshot.objects.select_related("asset").get(
                public_id=str(snapshot_id or ""), task=task
            )
        except WorkspaceSnapshot.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        if (
            source_snapshot.asset.status != ObjectAsset.Status.ACTIVE
            or source_snapshot.asset.scan_status != ObjectAsset.ScanStatus.CLEAN
            or source_snapshot.asset.digest_sha256 != source_snapshot.digest_sha256
        ):
            raise WorkspaceSnapshotNotReady(detail={"snapshot_id": source_snapshot.public_id})
    else:
        raise WorkspaceCaptureUnsupported(detail={"kind": kind})

    active = (
        WorkspaceStorageJob.objects.select_for_update()
        .filter(
            session=session,
            kind__in=(
                WorkspaceStorageJob.Kind.INITIALIZE,
                WorkspaceStorageJob.Kind.CAPTURE,
                WorkspaceStorageJob.Kind.RESTORE,
                WorkspaceStorageJob.Kind.FINALIZE,
            ),
            status__in=(WorkspaceStorageJob.Status.QUEUED, WorkspaceStorageJob.Status.RUNNING),
        )
        .first()
    )
    if active is not None:
        raise WorkspaceStorageJobActive(detail={"job_id": active.public_id})

    source_snapshot = None
    if kind == WorkspaceStorageJob.Kind.RESTORE:
        source_snapshot = WorkspaceSnapshot.objects.get(public_id=str(snapshot_id), task=task)
    now = timezone.now()
    job = WorkspaceStorageJob.objects.create(
        kind=kind,
        task=task,
        session=session,
        instance=session.instance,
        source_snapshot=source_snapshot,
        status=WorkspaceStorageJob.Status.QUEUED,
        client_seq=client_seq,
        base_version=base_version,
        idempotency_key=idempotency_key,
        request_digest=payload_digest,
        trace_id=_trace(context),
        queued_at=now,
    )
    changed = compare_and_swap(
        WorkspaceSession,
        pk=session.pk,
        expected_version=session.row_version,
        changes={"last_seen_at": now},
    )
    _audit(
        context=context,
        actor=actor,
        action="workspace.storage.capture.requested"
        if kind == WorkspaceStorageJob.Kind.CAPTURE
        else "workspace.storage.restore.requested",
        target_type="workspace_storage_job",
        target_ref=job.public_id,
        course_ref=task.course.public_id,
        after={"kind": kind, "status": job.status},
    )
    _emit(
        event_type="workspace.storage.job.requested",
        session=changed,
        payload={"storage_job_id": job.public_id, "kind": kind, "status": job.status},
        context=context,
    )
    from .storage import enqueue_storage_job

    enqueue_storage_job(job)
    return changed, job


@transaction.atomic
def transition_storage_job(
    *,
    job_id: str,
    expected_version: int,
    to_status: str,
    context: Any = None,
    result_snapshot: WorkspaceSnapshot | None = None,
    failure_record: FailureRecord | None = None,
) -> WorkspaceStorageJob:
    """Advance a storage job through its explicit, terminal state machine."""

    try:
        job = (
            WorkspaceStorageJob.objects.select_for_update()
            .select_related("task__course", "session")
            .get(public_id=job_id)
        )
    except WorkspaceStorageJob.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if to_status not in WorkspaceStorageJob.Status.values:
        raise StateConflict(detail={"status": to_status})
    if to_status not in _STORAGE_JOB_TRANSITIONS.get(job.status, set()):
        raise StateConflict(
            detail={"job_id": job.public_id, "status": job.status, "to_status": to_status}
        )
    if to_status == WorkspaceStorageJob.Status.PASSED:
        if result_snapshot is None:
            raise StateConflict(detail={"result_snapshot": "required"})
        if job.kind == WorkspaceStorageJob.Kind.RESTORE and job.source_snapshot_id is None:
            raise StateConflict(detail={"source_snapshot": "required"})
    now = timezone.now()
    changes: dict[str, Any] = {"status": to_status}
    if to_status == WorkspaceStorageJob.Status.RUNNING:
        changes["started_at"] = now
    if to_status in {
        WorkspaceStorageJob.Status.PASSED,
        WorkspaceStorageJob.Status.FAILED,
        WorkspaceStorageJob.Status.CANCELLED,
    }:
        changes["completed_at"] = now
    if result_snapshot is not None:
        changes["result_snapshot"] = result_snapshot
    if failure_record is not None:
        changes["failure_record"] = failure_record
    changed = compare_and_swap(
        WorkspaceStorageJob,
        pk=job.pk,
        expected_version=expected_version,
        changes=changes,
    )
    changed = WorkspaceStorageJob.objects.select_related(
        "task", "session", "source_snapshot", "result_snapshot", "failure_record"
    ).get(pk=changed.pk)
    successful_actions = {
        WorkspaceStorageJob.Kind.INITIALIZE: "workspace.volume.initialized",
        WorkspaceStorageJob.Kind.CAPTURE: "workspace.storage.capture.completed",
        WorkspaceStorageJob.Kind.RESTORE: "workspace.storage.restore.completed",
        WorkspaceStorageJob.Kind.FINALIZE: "workspace.runtime.finalized",
    }
    action = (
        successful_actions[job.kind]
        if to_status == WorkspaceStorageJob.Status.PASSED
        else f"workspace.storage.{job.kind.lower()}.{to_status.lower()}"
    )
    _audit(
        context=context,
        actor=None,
        action=action,
        target_type="workspace_storage_job",
        target_ref=changed.public_id,
        course_ref=changed.task.course.public_id,
        before={"status": job.status},
        after={"status": changed.status},
        result="FAILED" if to_status == WorkspaceStorageJob.Status.FAILED else "SUCCEEDED",
        error_code=failure_record.error_code if failure_record is not None else "",
    )
    _emit(
        event_type="workspace.storage.job.updated",
        session=changed.session,
        payload={
            "storage_job_id": changed.public_id,
            "kind": changed.kind,
            "status": changed.status,
        },
        context=context,
    )
    return changed


@transaction.atomic
def save_snapshot(
    *,
    task_id: str,
    actor: User,
    token: str,
    client_seq: int,
    base_version: int,
    upload: Any,
    context: Any,
) -> tuple[WorkspaceSession, WorkspaceSnapshot, str]:
    task = _task_for_actor(task_id=task_id, actor=actor)
    session = (
        WorkspaceSession.objects.select_for_update()
        .select_related(
            "task__enrollment",
            "task__publication",
            "student",
            "course",
            "instance",
        )
        .filter(task=task, student=actor, status=WorkspaceSession.Status.ACTIVE)
        .first()
    )
    if session is None:
        raise WorkspaceSessionInvalid()
    require_workspace_session(session=session, token=token, task_id=task_id, capability="snapshot")
    stream, size, digest, media_type = _read_upload(upload)
    previous_log = (
        WorkspaceAutosaveLog.objects.filter(task=task, client_seq=client_seq).first()
    )
    if previous_log is not None:
        if previous_log.request_digest != digest:
            raise AutosaveConflict(detail={"client_seq": client_seq})
        if previous_log.snapshot is None:
            raise AutosaveStale(detail={"client_seq": client_seq})
        WORKSPACE_AUTOSAVES_TOTAL.labels(result="replayed").inc()
        return session, previous_log.snapshot, "REPLAYED"
    latest_seq = (
        WorkspaceAutosaveLog.objects.filter(task=task).aggregate(value=Max("client_seq"))["value"]
        or 0
    )
    if client_seq <= latest_seq:
        raise AutosaveStale(detail={"client_seq": client_seq, "latest_seq": latest_seq})
    if base_version != session.current_version:
        raise AutosaveConflict(
            detail={"base_version": base_version, "current_version": session.current_version}
        )
    try:
        scanner = ClamAVScanner()
        result = scanner.scan(iter_chunks(stream))
    except AntivirusUnavailable as exc:
        raise WorkspaceScanUnavailable(detail={"reason": "ANTIVIRUS_UNAVAILABLE"}) from exc
    if not result.clean:
        raise AutosaveConflict(detail={"reason": "INFECTED", "signature": result.signature})
    stream.seek(0)
    key = (
        f"workspaces/{task.public_id}/{session.public_id}/"
        f"{session.current_version + 1}-{secrets.token_hex(8)}"
    )
    stored = object_storage().put_stream(
        bucket=settings.MINIO_BUCKET, object_key=key, stream=stream, media_type=media_type
    )
    try:
        asset = register_asset(
            bucket=settings.MINIO_BUCKET,
            object_key=key,
            object_version=stored.version_id,
            digest_sha256=digest,
            size_bytes=size,
            owner_type="WORKSPACE_TASK",
            owner_ref=task.public_id,
            purpose="WORKSPACE_SNAPSHOT",
            media_type=media_type,
        )
    except Exception:
        object_storage().delete_object(
            bucket=settings.MINIO_BUCKET, object_key=key, version_id=stored.version_id
        )
        raise
    set_scan_result(
        asset_id=asset.pk,
        expected_version=asset.row_version,
        scan_status=ObjectAsset.ScanStatus.CLEAN,
    )
    now = timezone.now()
    snapshot = WorkspaceSnapshot.objects.create(
        task=task,
        session=session,
        asset=asset,
        version_no=session.current_version + 1,
        client_seq=client_seq,
        base_version=base_version,
        digest_sha256=digest,
        size_bytes=size,
        media_type=media_type,
        saved_at=now,
        trace_id=_trace(context),
    )
    changed = compare_and_swap(
        WorkspaceSession,
        pk=session.pk,
        expected_version=session.row_version,
        changes={
            "current_version": snapshot.version_no,
            "latest_snapshot": snapshot,
            "last_seen_at": now,
        },
    )
    WorkspaceAutosaveLog.objects.create(
        task=task,
        session=session,
        client_seq=client_seq,
        request_digest=digest,
        snapshot=snapshot,
        result=WorkspaceAutosaveLog.Result.CONFIRMED,
        trace_id=_trace(context),
    )
    _audit(
        context=context,
        actor=actor,
        action="workspace.snapshot.save",
        target_type="workspace_snapshot",
        target_ref=snapshot.public_id,
        course_ref=task.course.public_id,
        after={"version": snapshot.version_no, "client_seq": client_seq, "digest": digest},
    )
    _emit(
        event_type=events.SNAPSHOT_SAVED,
        session=changed,
        payload={
            "snapshot_id": snapshot.public_id,
            "version": snapshot.version_no,
            "client_seq": client_seq,
            "saved_at": now.isoformat(),
        },
        context=context,
    )
    WORKSPACE_AUTOSAVES_TOTAL.labels(result="confirmed").inc()
    return changed, snapshot, "CONFIRMED"


@transaction.atomic
def create_checkpoint(
    *, task_id: str, actor: User, token: str, name: str, context: Any
) -> WorkspaceCheckpoint:
    task = _task_for_actor(task_id=task_id, actor=actor)
    session = (
        WorkspaceSession.objects.select_for_update()
        .select_related(
            "task__enrollment",
            "task__publication",
            "course",
            "student",
            "instance",
        )
        .filter(task=task, student=actor, status=WorkspaceSession.Status.ACTIVE)
        .first()
    )
    if session is None:
        raise WorkspaceSessionInvalid()
    session.latest_snapshot = (
        WorkspaceSnapshot.objects.select_related("asset")
        .filter(pk=session.latest_snapshot_id)
        .first()
    )
    require_workspace_session(
        session=session, token=token, task_id=task_id, capability="checkpoint"
    )
    if session.latest_snapshot is None:
        raise CheckpointStateConflict(detail={"snapshot": "missing"})
    current = (
        WorkspaceCheckpoint.objects.filter(task=task).aggregate(value=Max("checkpoint_no"))["value"]
        or 0
    )
    checkpoint = WorkspaceCheckpoint.objects.create(
        task=task,
        session=session,
        snapshot=session.latest_snapshot,
        checkpoint_no=current + 1,
        name=name.strip()[:180] or f"检查点 {current + 1}",
        source_seq=session.latest_snapshot.client_seq,
        digest_sha256=session.latest_snapshot.digest_sha256,
        retention_until=timezone.now() + timedelta(days=365),
        trace_id=_trace(context),
    )
    _audit(
        context=context,
        actor=actor,
        action="workspace.checkpoint.create",
        target_type="workspace_checkpoint",
        target_ref=checkpoint.public_id,
        course_ref=task.course.public_id,
        after={"checkpoint_no": checkpoint.checkpoint_no, "source_seq": checkpoint.source_seq},
    )
    _emit(
        event_type=events.CHECKPOINT_CREATED,
        session=session,
        payload={
            "checkpoint_id": checkpoint.public_id,
            "checkpoint_no": checkpoint.checkpoint_no,
            "version": checkpoint.snapshot.version_no,
        },
        context=context,
    )
    return checkpoint


@transaction.atomic
def restore_checkpoint(
    *,
    task_id: str,
    checkpoint_id: str,
    actor: User,
    token: str,
    expected_version: int,
    context: Any,
    idempotency_key: str = "",
) -> tuple[WorkspaceSession, WorkspaceSnapshot | WorkspaceStorageJob]:
    task = _task_for_actor(task_id=task_id, actor=actor)
    session = (
        WorkspaceSession.objects.select_for_update()
        .select_related(
            "task__enrollment",
            "task__publication",
            "course",
            "student",
            "instance",
        )
        .filter(task=task, student=actor, status=WorkspaceSession.Status.ACTIVE)
        .first()
    )
    if session is None:
        raise WorkspaceSessionInvalid()
    session.latest_snapshot = (
        WorkspaceSnapshot.objects.select_related("asset")
        .filter(pk=session.latest_snapshot_id)
        .first()
    )
    require_workspace_session(
        session=session, token=token, task_id=task_id, capability="checkpoint"
    )
    if session.row_version != expected_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_version,
                "actual_row_version": session.row_version,
            }
        )
    try:
        checkpoint = WorkspaceCheckpoint.objects.select_related("snapshot", "snapshot__asset").get(
            public_id=checkpoint_id, task=task
        )
    except WorkspaceCheckpoint.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    driver = task.runtime_adapter_driver or (
        task.runtime_adapter.driver if task.runtime_adapter_id else "FAKE"
    )
    if driver != "FAKE":
        _changed, job = create_storage_job(
            task_id=task.public_id,
            actor=actor,
            token=token,
            expected_version=expected_version,
            kind=WorkspaceStorageJob.Kind.RESTORE,
            client_seq=None,
            base_version=None,
            snapshot_id=checkpoint.snapshot.public_id,
            idempotency_key=idempotency_key
            or f"checkpoint-restore:{checkpoint.public_id}:{expected_version}",
            request_payload={
                "kind": WorkspaceStorageJob.Kind.RESTORE,
                "snapshot_id": checkpoint.snapshot.public_id,
            },
            context=context,
        )
        return _changed, job
    next_seq = (
        WorkspaceAutosaveLog.objects.filter(task=task).aggregate(value=Max("client_seq"))["value"]
        or 0
    ) + 1
    now = timezone.now()
    snapshot = WorkspaceSnapshot.objects.create(
        task=task,
        session=session,
        asset=checkpoint.snapshot.asset,
        version_no=session.current_version + 1,
        client_seq=next_seq,
        base_version=session.current_version,
        digest_sha256=checkpoint.digest_sha256,
        size_bytes=checkpoint.snapshot.size_bytes,
        media_type=checkpoint.snapshot.media_type,
        saved_at=now,
        trace_id=_trace(context),
    )
    WorkspaceAutosaveLog.objects.create(
        task=task,
        session=session,
        client_seq=next_seq,
        request_digest=checkpoint.digest_sha256,
        snapshot=snapshot,
        result=WorkspaceAutosaveLog.Result.CONFIRMED,
        trace_id=_trace(context),
    )
    changed = compare_and_swap(
        WorkspaceSession,
        pk=session.pk,
        expected_version=expected_version,
        changes={
            "current_version": snapshot.version_no,
            "latest_snapshot": snapshot,
            "last_seen_at": now,
        },
    )
    OperationEvent.objects.create(
        task=task,
        session=changed,
        seq=(
            (OperationEvent.objects.filter(task=task).aggregate(value=Max("seq"))["value"] or 0) + 1
        ),
        event_type="checkpoint.restored",
        phase="CHECKPOINT",
        payload_masked={"checkpoint_id": checkpoint.public_id, "version": snapshot.version_no},
        result_summary="checkpoint restored",
        occurred_at=now,
        trace_id=_trace(context),
    )
    _audit(
        context=context,
        actor=actor,
        action="workspace.checkpoint.restore",
        target_type="workspace_checkpoint",
        target_ref=checkpoint.public_id,
        course_ref=task.course.public_id,
        after={"version": snapshot.version_no},
    )
    _emit(
        event_type=events.CHECKPOINT_RESTORED,
        session=changed,
        payload={"checkpoint_id": checkpoint.public_id, "version": snapshot.version_no},
        context=context,
    )
    return changed, snapshot


ALLOWED_OPERATIONS = {
    "OPEN_PREVIEW": "preview",
    "RUN_CHECK": "snapshot",
    "STOP_PROCESS": "terminal",
    "FORMAT_DOCUMENT": "webide",
    "RESET_WORKSPACE": "webide",
}

EXECUTION_TERMINAL_STATUSES = frozenset(
    {
        WorkspaceExecutionRun.Status.PASSED,
        WorkspaceExecutionRun.Status.FAILED,
        WorkspaceExecutionRun.Status.TIMEOUT,
        WorkspaceExecutionRun.Status.RESOURCE_EXCEEDED,
        WorkspaceExecutionRun.Status.REJECTED,
    }
)


def _execution_rules(task: ExperimentTask) -> tuple[dict[str, Any], list[str], str]:
    execution_spec = dict(task.execution_spec or {})
    if not execution_spec:
        execution_spec = dict(task.template_version.execution_spec or {})
    try:
        command = list(build_execution_command(execution_spec))
    except Exception:  # noqa: BLE001 - legacy FakeRuntime rows have no execution spec
        command = []
    summary: dict[str, Any] = {
        "language": execution_spec.get("language", ""),
        "entrypoint": execution_spec.get("entrypoint", ""),
        "timeout_seconds": execution_spec.get("timeout_seconds", 0),
        "memory_mb": execution_spec.get("memory_mb", 0),
        "cpu_millicores": execution_spec.get("cpu_millicores", 0),
        "comparator": execution_spec.get("comparator", "token"),
        "network_mode": execution_spec.get("network_mode", "DENY_ALL"),
        "tests_asset": execution_spec.get("tests_asset", ""),
        "command": command,
    }
    digest = hashlib.sha256(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return summary, command, digest


def _runtime_spec_for_execution(task: ExperimentTask, *, trace_id: str) -> RuntimeSpec:
    profile = dict(task.resource_profile_snapshot or {})
    image = task.image
    return RuntimeSpec(
        task_id=task.public_id,
        course_id=task.course.public_id,
        student_id=task.student.public_id,
        runtime_type=task.runtime_type,
        image_registry=task.image_registry or (image.registry if image else ""),
        image_repository=task.image_repository or (image.repository if image else ""),
        image_digest=task.image_digest or (image.digest if image else "sha256:"),
        resource_profile_id=(
            task.resource_profile.public_id
            if task.resource_profile_id
            else str(profile.get("public_id", ""))
        ),
        cpu_millicores=int(profile.get("cpu_millicores", 0) or 0),
        memory_mb=int(profile.get("memory_mb", 0) or 0),
        disk_gb=int(profile.get("disk_gb", 0) or 0),
        network_policy={"mode": str(profile.get("network_mode", "DENY_ALL"))},
        workspace_capabilities=dict(task.template_version.workspace_capabilities or {}),
        workspace_port=int(getattr(settings, "RUNTIME_WORKSPACE_PORT", 8080)),
        healthcheck_path=str(getattr(settings, "RUNTIME_HEALTHCHECK_PATH", "/healthz")),
        trace_id=trace_id,
    )


def _execution_key(
    *, session: WorkspaceSession, snapshot: WorkspaceSnapshot | None, request_key: str
) -> str:
    clean = request_key.strip()[:128]
    snapshot_ref = snapshot.public_id if snapshot else "NO_SNAPSHOT"
    source = (
        f"{session.public_id}:RUN_CHECK:{clean}:{snapshot_ref}"
        if clean
        else f"{session.public_id}:RUN_CHECK:{snapshot_ref}"
    )
    return hashlib.sha256(source.encode()).hexdigest()


def _schedule_execution(run_id: str, trace_id: str) -> None:
    from .tasks import execute_workspace_execution_run

    transaction.on_commit(
        lambda: execute_workspace_execution_run.apply_async(
            kwargs={"execution_run_id": run_id, "trace_id": trace_id}
        ),
        robust=True,
    )


@transaction.atomic
def request_execution_run(
    *,
    session: WorkspaceSession,
    token: str,
    actor: User,
    arguments: dict[str, Any],
    request_key: str,
    context: Any,
) -> WorkspaceExecutionRun:
    """Create or replay one RUN_CHECK execution for the scoped session."""

    locked = (
        WorkspaceSession.objects.select_for_update(of=("self",))
        .select_related(
            "task__course",
            "task__student",
            "task__template_version",
            "task__runtime_adapter",
            "task__image",
            "task__resource_profile",
            "course",
            "student",
            "instance",
            "latest_snapshot",
        )
        .get(pk=session.pk)
    )
    require_workspace_session(session=locked, token=token, task_id=locked.task.public_id)
    if locked.student_id != actor.pk:
        raise ResourceNotFound()
    snapshot = locked.latest_snapshot
    requested_snapshot_id = str(arguments.get("snapshot_id", "")).strip()
    if requested_snapshot_id and (snapshot is None or snapshot.public_id != requested_snapshot_id):
        try:
            snapshot = WorkspaceSnapshot.objects.get(
                public_id=requested_snapshot_id, task=locked.task, session=locked
            )
        except WorkspaceSnapshot.DoesNotExist as exc:
            raise ResourceNotFound() from exc
    key = _execution_key(session=locked, snapshot=snapshot, request_key=request_key)
    existing = (
        WorkspaceExecutionRun.objects.select_related("snapshot")
        .filter(idempotency_key=key)
        .first()
    )
    if existing is not None:
        return existing
    summary, _command, digest = _execution_rules(locked.task)
    driver = locked.task.runtime_adapter_driver or (
        locked.task.runtime_adapter.driver if locked.task.runtime_adapter_id else "FAKE"
    )
    run = WorkspaceExecutionRun.objects.create(
        task=locked.task,
        session=locked,
        snapshot=snapshot,
        status=WorkspaceExecutionRun.Status.QUEUED,
        execution_rule_summary=summary,
        execution_rule_digest=digest,
        idempotency_key=key,
        trace_id=_trace(context),
    )
    if driver == "FAKE":
        now = timezone.now()
        run = compare_and_swap(
            WorkspaceExecutionRun,
            pk=run.pk,
            expected_version=run.row_version,
            changes={
                "status": WorkspaceExecutionRun.Status.PASSED,
                "started_at": now,
                "finished_at": now,
                "duration_ms": 0,
                "result_summary": "PASSED by FakeRuntime",
            },
        )
    else:
        _schedule_execution(run.public_id, _trace(context))
    _emit(
        event_type=events.EXECUTION_QUEUED,
        session=locked,
        payload={
            "execution_run_id": run.public_id,
            "status": run.status,
            "snapshot_id": snapshot.public_id if snapshot else None,
        },
        context=context,
    )
    return run


def _output_asset(
    *, run: WorkspaceExecutionRun, kind: str, content: bytes
) -> ObjectAsset | None:
    if not content:
        return None
    try:
        key = f"workspace/executions/{run.public_id}/{kind.lower()}"
        media_type = "application/json" if kind == "TEST_REPORT" else "text/plain"
        stored = object_storage().put_stream(
            bucket=settings.MINIO_BUCKET,
            object_key=key,
            stream=io.BytesIO(content),
            media_type=media_type,
        )
        asset = register_asset(
            bucket=settings.MINIO_BUCKET,
            object_key=key,
            object_version=stored.version_id,
            digest_sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            owner_type="WORKSPACE_EXECUTION",
            owner_ref=run.public_id,
            purpose=f"EXECUTION_{kind}",
            media_type=media_type,
            original_name=f"{kind.lower()}.{'json' if kind == 'TEST_REPORT' else 'txt'}",
            retention_until=timezone.now()
            + timedelta(
                days=max(1, int(getattr(settings, "RUNTIME_EXECUTION_RETENTION_DAYS", 30)))
            ),
        )
        set_scan_result(
            asset_id=asset.pk,
            expected_version=asset.row_version,
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )
        return asset
    except Exception:  # noqa: BLE001 - storage failure must remain visible in the run state
        return None


def _finish_execution(
    run: WorkspaceExecutionRun, *, status: str, error_code: str, summary: str
) -> WorkspaceExecutionRun:
    finished = timezone.now()
    duration = (
        max(0, int((finished - run.started_at).total_seconds() * 1000))
        if run.started_at
        else None
    )
    with transaction.atomic():
        current = WorkspaceExecutionRun.objects.select_for_update().get(pk=run.pk)
        if current.status in EXECUTION_TERMINAL_STATUSES:
            return current
        return compare_and_swap(
            WorkspaceExecutionRun,
            pk=current.pk,
            expected_version=current.row_version,
            changes={
                "status": status,
                "finished_at": finished,
                "duration_ms": duration,
                "error_code": error_code[:64],
                "result_summary": summary[:500],
            },
        )


def execute_execution_run(*, execution_run_id: str, trace_id: str = "") -> WorkspaceExecutionRun:
    """Run one queued execution and atomically publish its terminal result."""

    with transaction.atomic():
        # Keep the read-only snapshot outside this locking query; it is loaded after the run lock.
        run = (
            WorkspaceExecutionRun.objects.select_for_update()
            .select_related(
                "task__course",
                "task__student",
                "task__template_version",
                "task__runtime_adapter",
                "task__image",
                "task__resource_profile",
                "session",
            )
            .get(public_id=execution_run_id)
        )
        if run.status in EXECUTION_TERMINAL_STATUSES:
            return run
        run = compare_and_swap(
            WorkspaceExecutionRun,
            pk=run.pk,
            expected_version=run.row_version,
            changes={"status": WorkspaceExecutionRun.Status.RUNNING, "started_at": timezone.now()},
        )
    task = run.task
    context = type(
        "ExecutionContext",
        (),
        {"trace_id": trace_id or run.trace_id, "portal": "WORKER", "actor_ref": "worker"},
    )()
    driver = task.runtime_adapter_driver or (
        task.runtime_adapter.driver if task.runtime_adapter_id else "FAKE"
    )
    try:
        if run.snapshot is None:
            raise RuntimeError("EXECUTION_SNAPSHOT_REQUIRED")
        summary = dict(run.execution_rule_summary or {})
        command = [str(value) for value in summary.get("command", [])]
        source = b""
        adapter = runtime_for_driver(
            driver,
            config_ref=task.runtime_adapter_config_ref
            or (task.runtime_adapter.config_ref if task.runtime_adapter_id else ""),
        )
        if adapter.__class__.__name__ != "DockerLocalProtocolStub":
            stored = object_storage().open_object(
                bucket=run.snapshot.asset.bucket,
                object_key=run.snapshot.asset.object_key,
                version_id=run.snapshot.asset.object_version,
            )
            source = stored.body.read() if hasattr(stored.body, "read") else b""
        result: RuntimeExecutionResult = adapter.execute(
            spec=_runtime_spec_for_execution(task, trace_id=run.trace_id),
            command=command,
            source=source,
            timeout_seconds=int(summary.get("timeout_seconds", 0) or 0),
            memory_mb=int(summary.get("memory_mb", 0) or 0),
            cpu_millicores=int(summary.get("cpu_millicores", 0) or 0),
            network_mode=str(summary.get("network_mode", "DENY_ALL")),
        )
        status = (
            result.status if result.status in WorkspaceExecutionRun.Status.values else "FAILED"
        )
        finished = timezone.now()
        duration = result.duration_ms
        if duration is None and run.started_at:
            duration = max(0, int((finished - run.started_at).total_seconds() * 1000))
        stdout_asset = _output_asset(run=run, kind="STDOUT", content=result.stdout.encode())
        stderr_asset = _output_asset(run=run, kind="STDERR", content=result.stderr.encode())
        report_bytes = json.dumps(
            result.test_report or {}, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode()
        report_asset = _output_asset(run=run, kind="TEST_REPORT", content=report_bytes)
        changed = compare_and_swap(
            WorkspaceExecutionRun,
            pk=run.pk,
            expected_version=run.row_version,
            changes={
                "status": status,
                "finished_at": finished,
                "duration_ms": duration,
                "stdout_asset": stdout_asset,
                "stderr_asset": stderr_asset,
                "test_report_asset": report_asset,
                "error_code": result.error_code,
                "result_summary": result.result_summary or status,
            },
        )
    except TimeoutError:
        changed = _finish_execution(
            run,
            status=WorkspaceExecutionRun.Status.TIMEOUT,
            error_code="EXECUTION_TIMEOUT",
            summary="Execution timed out",
        )
    except MemoryError:
        changed = _finish_execution(
            run,
            status=WorkspaceExecutionRun.Status.RESOURCE_EXCEEDED,
            error_code="EXECUTION_MEMORY_EXCEEDED",
            summary="Execution exceeded memory limit",
        )
    except RuntimeAdapterFailure as exc:
        if is_engine_unavailable(exc.code):
            RUNTIME_ENGINE_UNAVAILABLE_TOTAL.labels(driver=driver).inc()
        changed = _finish_execution(
            run,
            status=(
                WorkspaceExecutionRun.Status.REJECTED
                if not exc.retryable
                else WorkspaceExecutionRun.Status.FAILED
            ),
            error_code=exc.code,
            summary=exc.code,
        )
    except Exception as exc:  # noqa: BLE001 - worker must publish a terminal audit fact
        changed = _finish_execution(
            run,
            status=WorkspaceExecutionRun.Status.REJECTED,
            error_code=str(exc)[:64] or "EXECUTION_FAILED",
            summary="Execution rejected",
        )
    if changed.duration_ms is not None:
        RUNTIME_EXECUTION_DURATION.labels(driver=driver).observe(changed.duration_ms / 1000)
    RUNTIME_EXECUTION_RESULTS.labels(driver=driver, status=changed.status).inc()
    logger.info(
        "runtime execution finished",
        extra={
            "trace_id": changed.trace_id,
            "task_ref": task.public_id,
            "execution_run_ref": changed.public_id,
            "resource_ref": changed.public_id,
            "result": changed.status,
            "error_code": changed.error_code,
            "duration_ms": changed.duration_ms or 0,
        },
    )
    with transaction.atomic():
        locked = WorkspaceExecutionRun.objects.select_related("session").get(pk=changed.pk)
        _emit(
            event_type=events.EXECUTION_FINISHED,
            session=locked.session,
            payload={"execution_run_id": locked.public_id, "status": locked.status},
            context=context,
        )
    return changed


@transaction.atomic
def record_operation(
    *,
    session: WorkspaceSession,
    token: str,
    actor: User,
    operation: str,
    arguments: dict[str, Any],
    context: Any,
    request_key: str = "",
) -> OperationEvent:
    session = (
        WorkspaceSession.objects.select_for_update()
        .select_related("task__enrollment", "task__publication", "course", "student", "instance")
        .get(pk=session.pk)
    )
    require_workspace_session(session=session, token=token, task_id=session.task.public_id)
    capability = ALLOWED_OPERATIONS.get(operation)
    if capability is None:
        raise WorkspaceOperationDenied(detail={"operation": operation})
    if not bool((session.capabilities or {}).get(capability)):
        raise WorkspaceCapabilityDenied(detail={"capability": capability})
    safe_arguments = redact(arguments or {})
    execution_run: WorkspaceExecutionRun | None = None
    if operation == "RUN_CHECK":
        execution_run = request_execution_run(
            session=session,
            token=token,
            actor=actor,
            arguments=arguments or {},
            request_key=request_key,
            context=context,
        )
        safe_arguments = {
            **safe_arguments,
            "execution_run_id": execution_run.public_id,
            "execution_status": execution_run.status,
        }
        existing_event = (
            OperationEvent.objects.filter(
                task=session.task,
                event_type="operation.run_check",
                payload_masked__execution_run_id=execution_run.public_id,
            )
            .order_by("id")
            .first()
        )
        if existing_event is not None:
            return existing_event
    seq = (
        OperationEvent.objects.filter(task=session.task).aggregate(value=Max("seq"))["value"] or 0
    ) + 1
    event = OperationEvent.objects.create(
        task=session.task,
        session=session,
        seq=seq,
        event_type=f"operation.{operation.lower()}",
        phase=capability.upper(),
        payload_masked=safe_arguments,
        result_summary=(
            f"{operation} accepted by FakeRuntime"
            if execution_run is None or execution_run.status == WorkspaceExecutionRun.Status.PASSED
            else f"{operation} {execution_run.status.lower()}"
        ),
        occurred_at=timezone.now(),
        trace_id=_trace(context),
    )
    _audit(
        context=context,
        actor=actor,
        action="workspace.operation.record",
        target_type="operation_event",
        target_ref=event.public_id,
        course_ref=session.course.public_id,
        after={"operation": operation, "seq": seq},
    )
    _emit(
        event_type=events.OPERATION_RECORDED,
        session=session,
        payload={
            "operation_id": event.public_id,
            "seq": seq,
            "operation": operation,
            "result": event.result_summary,
            **({"execution_run_id": execution_run.public_id} if execution_run else {}),
        },
        context=context,
    )
    return event


@transaction.atomic
def expire_sessions(*, trace_id: str = "") -> int:
    now = timezone.now()
    count = 0
    for session in WorkspaceSession.objects.select_for_update().filter(
        status=WorkspaceSession.Status.ACTIVE, expires_at__lte=now
    ):
        compare_and_swap(
            WorkspaceSession,
            pk=session.pk,
            expected_version=session.row_version,
            changes={
                "status": WorkspaceSession.Status.EXPIRED,
                "active_marker": None,
                "revoked_at": now,
                "revoke_reason": "ticket expired",
            },
        )
        count += 1
    return count

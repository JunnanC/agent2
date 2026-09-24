import hashlib
import io
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
from apps.core.models import ObjectAsset
from apps.core.object_storage import iter_chunks, object_storage
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.core.redaction import redact
from apps.courses.models import Enrollment
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.experiments.services import transition_task

from . import events
from .errors import (
    AutosaveConflict,
    AutosaveStale,
    CheckpointStateConflict,
    WorkspaceCapabilityDenied,
    WorkspaceOperationDenied,
    WorkspaceScanUnavailable,
    WorkspaceSessionInvalid,
)
from .metrics import WORKSPACE_AUTOSAVES_TOTAL, WORKSPACE_SESSIONS_TOTAL
from .models import (
    OperationEvent,
    WorkspaceAutosaveLog,
    WorkspaceCheckpoint,
    WorkspaceSession,
    WorkspaceSnapshot,
)
from .permissions import require_workspace_session, token_digest


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


def _task_for_actor(*, task_id: str, actor: User) -> ExperimentTask:
    try:
        return (
            ExperimentTask.objects.select_for_update()
            .select_related("course", "student", "enrollment", "publication")
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
        .select_related("course", "student", "enrollment", "publication")
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
                capabilities={
                    "webide": True,
                    "terminal": True,
                    "preview": True,
                    "snapshot": True,
                    "checkpoint": True,
                },
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
) -> tuple[WorkspaceSession, WorkspaceSnapshot]:
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
    "RUN_CHECK": "terminal",
    "STOP_PROCESS": "terminal",
    "FORMAT_DOCUMENT": "webide",
    "RESET_WORKSPACE": "webide",
}


@transaction.atomic
def record_operation(
    *,
    session: WorkspaceSession,
    token: str,
    actor: User,
    operation: str,
    arguments: dict[str, Any],
    context: Any,
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
        result_summary=f"{operation} accepted by FakeRuntime",
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

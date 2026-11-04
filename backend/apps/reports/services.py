import hashlib
import json
import secrets
import tempfile
import zipfile
from pathlib import PurePath
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.accounts.models import User
from apps.core.antivirus import AntivirusUnavailable, ClamAVScanner
from apps.core.assets import record_purge_result
from apps.core.audit import append_audit, append_failure, hash_client_ip
from apps.core.compensation import create_compensation
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.identifiers import new_ulid
from apps.core.models import CompensationTask, ObjectAsset, ObjectPurgeLog
from apps.core.object_storage import iter_chunks, object_storage
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.core.tasks import run_compensations
from apps.courses.models import CourseStaffGrant, Enrollment
from apps.courses.selectors import require_course_capability
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.experiments.services import transition_task
from apps.workspaces.models import WorkspaceExecutionRun, WorkspaceSnapshot
from apps.workspaces.services import task_has_active_test_rules

from . import events
from .errors import (
    ReportAttachmentNotReady,
    ReportExecutionConflict,
    ReportExecutionNotReady,
    ReportSnapshotConflict,
    ReportStateConflict,
    ReportUploadInvalid,
)
from .metrics import REPORT_ATTACHMENT_SCANS_TOTAL, REPORT_SUBMISSIONS_TOTAL
from .models import (
    ReportAttachment,
    ReportDraft,
    ReportVersion,
    ReportVersionAttachment,
    SystemArtifact,
)

REPORT_OWNER = "REPORT_ATTACHMENT"
REPORT_PURPOSE = "REPORT_ATTACHMENT"
ALLOWED_FILES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".txt": "text/plain",
}


def _trace(context: Any) -> str:
    return str(getattr(context, "trace_id", ""))


def _audit(
    *,
    context: Any,
    actor: User | None,
    action: str,
    target_type: str,
    target_ref: str,
    course_ref: str,
    after: Any = None,
    result: str = "SUCCEEDED",
    error_code: str = "",
) -> None:
    append_audit(
        actor_ref=actor.public_id if actor else str(getattr(context, "actor_ref", "SYSTEM")),
        actor_portal=str(getattr(context, "portal", "WORKER")),
        actor_context={},
        action=action,
        target_type=target_type,
        target_ref=target_ref,
        course_ref=course_ref,
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
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_ref: str,
    payload: dict[str, Any],
    trace_id: str,
) -> None:
    append_outbox_event(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_ref=aggregate_ref,
        payload=payload,
        trace_id=trace_id,
    )
    enqueue_relay_after_commit(trace_id=trace_id)


def _locked_task(*, task_id: str, actor: User) -> ExperimentTask:
    try:
        return (
            ExperimentTask.objects.select_for_update()
            .select_related("course", "publication", "enrollment", "student")
            .get(public_id=task_id, student=actor)
        )
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def _require_report_task(task: ExperimentTask) -> None:
    if not task.publication.report_required:
        raise ReportStateConflict(detail={"report_required": False})


def _task_scope_matches(task: ExperimentTask) -> bool:
    return (
        task.course_id == task.publication.course_id
        and task.course_id == task.enrollment.course_id
        and task.student_id == task.enrollment.student_id
    )


def _require_task_scope(task: ExperimentTask) -> None:
    if not _task_scope_matches(task):
        raise ReportStateConflict(detail={"task_scope": "course_or_student_mismatch"})


def _lock_workspace_sessions(task: ExperimentTask) -> None:
    list(task.workspace_sessions.select_for_update().order_by("pk").values_list("pk", flat=True))


def _latest_snapshot(task: ExperimentTask) -> WorkspaceSnapshot | None:
    return (
        WorkspaceSnapshot.objects.select_related("asset")
        .filter(task=task)
        .order_by("-version_no", "-id")
        .first()
    )


def _snapshot_is_valid(snapshot: WorkspaceSnapshot, task: ExperimentTask) -> bool:
    asset = snapshot.asset
    return (
        snapshot.task_id == task.pk
        and asset.owner_type == "WORKSPACE_TASK"
        and asset.owner_ref == task.public_id
        and asset.digest_sha256 == snapshot.digest_sha256
        and asset.scan_status == ObjectAsset.ScanStatus.CLEAN
        and asset.status == ObjectAsset.Status.ACTIVE
    )


_EXECUTION_TERMINAL_STATUSES = frozenset(
    {
        WorkspaceExecutionRun.Status.PASSED,
        WorkspaceExecutionRun.Status.FAILED,
        WorkspaceExecutionRun.Status.TIMEOUT,
        WorkspaceExecutionRun.Status.RESOURCE_EXCEEDED,
        WorkspaceExecutionRun.Status.REJECTED,
    }
)


def _execution_asset_is_valid(asset: ObjectAsset | None, run: WorkspaceExecutionRun) -> bool:
    if asset is None:
        return True
    return (
        asset.owner_type == "WORKSPACE_EXECUTION"
        and asset.owner_ref == run.public_id
        and asset.scan_status == ObjectAsset.ScanStatus.CLEAN
        and asset.status == ObjectAsset.Status.ACTIVE
    )


def _legacy_fake_execution(
    *, task: ExperimentTask, snapshot: WorkspaceSnapshot
) -> WorkspaceExecutionRun:
    """Materialize the legacy simulated-runtime submission once per snapshot."""

    summary = dict(getattr(task, "execution_spec", None) or {})
    digest = hashlib.sha256(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    key = hashlib.sha256(
        f"legacy-report-fake:{task.public_id}:{snapshot.public_id}".encode()
    ).hexdigest()
    run, _ = WorkspaceExecutionRun.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "task": task,
            "session": snapshot.session,
            "snapshot": snapshot,
            "status": WorkspaceExecutionRun.Status.PASSED,
            "execution_rule_summary": summary,
            "execution_rule_digest": digest,
            "result_summary": "PASSED by FakeRuntime (report compatibility)",
            "started_at": timezone.now(),
            "finished_at": timezone.now(),
            "duration_ms": 0,
            "trace_id": "legacy-fake".ljust(32, "0"),
        },
    )
    return run


def _latest_execution_for_submission(
    *, task: ExperimentTask, snapshot: WorkspaceSnapshot
) -> WorkspaceExecutionRun:
    """Return the newest run, requiring it to prove the submitted snapshot.

    Looking at the newest run before checking its state prevents a student from
    submitting an older passing run while a newer run is still queued or points at
    a newer snapshot.  All copied fields are later written to the append-only report
    version, so this check is the only live run read needed during submission.

    任务模板未声明任何测试用例且不存在执行运行时,提交不要求运行,沿用兼容
    路径生成执行凭据(snapshot 级幂等),避免把"检查点型实验"卡在无测试可运行
    的状态;已有真实运行(即使无规则)仍以真实运行为准。
    """
    runs = (
        WorkspaceExecutionRun.objects.select_related(
            "task",
            "session",
            "snapshot__asset",
            "stdout_asset",
            "stderr_asset",
            "test_report_asset",
        )
        .filter(task=task)
        .order_by("-created_at", "-id")
    )
    run = next(
        (item for item in runs.iterator()
         if item.execution_rule_summary.get("evaluation_mode") != "SELF_TEST"),
        None,
    )
    if run is None:
        if (task.execution_spec or {}).get("schema_version") == 2:
            raise ReportExecutionNotReady(detail={"execution": "missing_formal_run"})
        if not task_has_active_test_rules(task):
            return _legacy_fake_execution(task=task, snapshot=snapshot)
        driver = task.runtime_adapter_driver or (
            task.runtime_adapter.driver if task.runtime_adapter_id else "FAKE"
        )
        if driver == "FAKE" or ReportVersion.objects.filter(
            task=task, execution_run__isnull=True
        ).exists():
            return _legacy_fake_execution(task=task, snapshot=snapshot)
        raise ReportExecutionNotReady(detail={"execution": "missing"})
    if run.status not in _EXECUTION_TERMINAL_STATUSES:
        raise ReportExecutionNotReady(
            detail={"execution_run_id": run.public_id, "status": run.status}
        )
    if (
        run.session.task_id != task.pk
        or run.session.student_id != task.student_id
        or run.snapshot_id != snapshot.pk
        or run.snapshot is None
        or run.snapshot.digest_sha256 != snapshot.digest_sha256
    ):
        raise ReportExecutionConflict(
            detail={
                "execution_run_id": run.public_id,
                "execution_snapshot_id": run.snapshot.public_id if run.snapshot else None,
                "report_snapshot_id": snapshot.public_id,
            }
        )
    if not _snapshot_is_valid(run.snapshot, task):
        raise ReportExecutionConflict(detail={"execution": "snapshot_not_clean"})
    if not all(
        _execution_asset_is_valid(asset, run)
        for asset in (run.stdout_asset, run.stderr_asset, run.test_report_asset)
    ):
        raise ReportExecutionConflict(detail={"execution": "asset_not_available"})
    if (task.execution_spec or {}).get("schema_version") == 2:
        from apps.workspaces.services import _execution_rules

        driver = task.runtime_adapter_driver or (
            task.runtime_adapter.driver if task.runtime_adapter_id else "FAKE"
        )
        if driver == "FAKE" or run.status != WorkspaceExecutionRun.Status.PASSED:
            raise ReportExecutionNotReady(detail={"execution": "formal_pass_required"})
        summary, _, digest = _execution_rules(task, language=snapshot.language)
        if (
            run.execution_rule_digest != digest
            or run.execution_rule_summary != summary
            or snapshot.language != run.session.language
        ):
            raise ReportExecutionConflict(detail={"execution": "contract_changed"})
        from apps.workspaces.presentation import asset_text

        try:
            report = json.loads(asset_text(run.test_report_asset, limit=1024 * 1024) or "{}")
            tests_asset = ObjectAsset.objects.get(public_id=summary["tests_asset"])
            tests = json.loads(asset_text(tests_asset, limit=1024 * 1024) or "{}")
            expected_count = len(tests["cases"])
            results = report["results"]
            complete = (
                report.get("status") == "PASSED"
                and report.get("cases") == len(results)
                and len(results) == expected_count > 0
                and all(item.get("status") == "PASSED" for item in results)
            )
        except (KeyError, TypeError, ValueError, AttributeError, ObjectAsset.DoesNotExist):
            complete = False
        if not complete:
            raise ReportExecutionNotReady(detail={"execution": "complete_results_required"})
    return run


def _report_execution_is_consistent(version: ReportVersion, task: ExperimentTask) -> bool:
    """Validate the immutable report projection before exposing its evidence."""

    try:
        run = version.execution_run
    except WorkspaceExecutionRun.DoesNotExist:
        return False
    if run is None:
        return False
    if (
        run.task_id != task.pk
        or run.session.task_id != task.pk
        or run.session.student_id != task.student_id
        or version.execution_snapshot_id != version.workspace_snapshot_id
        or version.execution_snapshot_digest != version.snapshot_digest
        or version.execution_status not in _EXECUTION_TERMINAL_STATUSES
    ):
        return False
    return all(
        asset is None
        or (
            asset.owner_type == "WORKSPACE_EXECUTION"
            and asset.owner_ref == run.public_id
        )
        for asset in (
            version.execution_stdout_asset,
            version.execution_stderr_asset,
            version.execution_test_report_asset,
        )
    )


@transaction.atomic
def initialize_report_draft(
    *, task: ExperimentTask, actor: User, context: ActorContext
) -> ReportDraft | None:
    if not task.publication.report_required:
        return None
    _require_task_scope(task)
    if actor.pk != task.student_id:
        raise ResourceNotFound()
    draft, created = ReportDraft.objects.get_or_create(
        task=task,
        defaults={"student": actor},
    )
    if not created:
        if draft.student_id != actor.pk:
            raise ReportStateConflict(detail={"student_scope": "mismatch"})
        return draft
    _audit(
        context=context,
        actor=actor,
        action="report.draft.initialize",
        target_type="report_draft",
        target_ref=draft.public_id,
        course_ref=task.course.public_id,
        after={"task_id": task.public_id},
    )
    _emit(
        event_type=events.REPORT_DRAFT_CREATED,
        aggregate_type="report_draft",
        aggregate_ref=draft.public_id,
        payload={"task_id": task.public_id, "course_id": task.course.public_id},
        trace_id=_trace(context),
    )
    return draft


@transaction.atomic
def update_report_draft(
    *, task_id: str, actor: User, body_markdown: str, expected_version: int, context: ActorContext
) -> ReportDraft:
    task = _locked_task(task_id=task_id, actor=actor)
    _require_report_task(task)
    _require_task_scope(task)
    if task.status not in {ExperimentTask.Status.IN_PROGRESS, ExperimentTask.Status.REPORT_DRAFT}:
        raise ReportStateConflict(detail={"task_status": task.status})
    try:
        draft = ReportDraft.objects.select_for_update().get(task=task, student=actor)
    except ReportDraft.DoesNotExist as exc:
        raise ReportStateConflict(detail={"draft": "not_initialized"}) from exc
    if draft.status != ReportDraft.Status.DRAFT:
        raise ReportStateConflict(detail={"draft_status": draft.status})
    if draft.row_version != expected_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_version,
                "actual_row_version": draft.row_version,
            }
        )
    _lock_workspace_sessions(task)
    snapshot = _latest_snapshot(task)
    if snapshot is not None and not _snapshot_is_valid(snapshot, task):
        raise ReportSnapshotConflict(detail={"snapshot": "not_clean"})
    updated = compare_and_swap(
        ReportDraft,
        pk=draft.pk,
        expected_version=expected_version,
        changes={
            "body_markdown": body_markdown,
            "workspace_snapshot": snapshot,
            "snapshot_digest": snapshot.digest_sha256 if snapshot else "",
        },
    )
    if task.status == ExperimentTask.Status.IN_PROGRESS:
        transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.REPORT_DRAFT,
            actor=actor,
            expected_version=task.row_version,
            trigger="REPORT_DRAFT_UPDATED",
            reason="student saved report draft",
            context=context,
        )
    _audit(
        context=context,
        actor=actor,
        action="report.draft.update",
        target_type="report_draft",
        target_ref=updated.public_id,
        course_ref=task.course.public_id,
        after={"row_version": updated.row_version, "snapshot_digest": updated.snapshot_digest},
    )
    _emit(
        event_type=events.REPORT_DRAFT_UPDATED,
        aggregate_type="report_draft",
        aggregate_ref=updated.public_id,
        payload={"task_id": task.public_id, "row_version": updated.row_version},
        trace_id=_trace(context),
    )
    return updated  # type: ignore[return-value]


def report_draft_for_user(*, task_id: str, actor: User) -> ReportDraft:
    try:
        draft = ReportDraft.objects.select_related("task", "student", "workspace_snapshot").get(
            task__public_id=task_id, student=actor
        )
    except ReportDraft.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if not draft.task.publication.report_required:
        raise ResourceNotFound()
    try:
        _require_task_scope(draft.task)
    except ReportStateConflict as exc:
        raise ResourceNotFound() from exc
    return draft


def _safe_filename(file_name: str) -> str:
    clean = PurePath(file_name.replace("\\", "/")).name
    if not clean or clean in {".", ".."} or len(clean) > 255:
        raise ReportUploadInvalid(detail={"file_name": "invalid"})
    return clean


@transaction.atomic
def create_attachment_upload(
    *,
    task_id: str,
    actor: User,
    file_name: str,
    media_type: str,
    size_bytes: int,
    digest_sha256: str,
    context: ActorContext,
) -> tuple[ObjectAsset, dict[str, Any]]:
    task = _locked_task(task_id=task_id, actor=actor)
    _require_report_task(task)
    _require_task_scope(task)
    if task.status not in {ExperimentTask.Status.IN_PROGRESS, ExperimentTask.Status.REPORT_DRAFT}:
        raise ReportStateConflict(detail={"task_status": task.status})
    if not ReportDraft.objects.filter(
        task=task, student=actor, status=ReportDraft.Status.DRAFT
    ).exists():
        raise ReportStateConflict(detail={"draft": "not_initialized"})
    clean_name = _safe_filename(file_name)
    suffix = PurePath(clean_name).suffix.casefold()
    if ALLOWED_FILES.get(suffix) != media_type:
        raise ReportUploadInvalid(detail={"media_type": "extension_and_type_mismatch"})
    max_bytes = int(getattr(settings, "REPORT_ATTACHMENT_MAX_BYTES", 20 * 1024 * 1024))
    if not 1 <= size_bytes <= max_bytes:
        raise ReportUploadInvalid(detail={"size_bytes": "outside_allowed_range"})
    digest_sha256 = digest_sha256.casefold()
    if len(digest_sha256) != 64 or any(char not in "0123456789abcdef" for char in digest_sha256):
        raise ReportUploadInvalid(detail={"digest_sha256": "invalid"})
    asset_id = new_ulid()
    object_key = f"reports/{task.public_id}/{asset_id}/{secrets.token_hex(16)}"
    asset = ObjectAsset.objects.create(
        public_id=asset_id,
        bucket=settings.MINIO_BUCKET,
        object_key=object_key,
        digest_sha256=digest_sha256,
        size_bytes=size_bytes,
        media_type=media_type,
        original_name=clean_name,
        owner_type=REPORT_OWNER,
        owner_ref=task.public_id,
        purpose=REPORT_PURPOSE,
    )
    upload = object_storage(public=True).create_upload_post(
        bucket=asset.bucket,
        object_key=asset.object_key,
        media_type=asset.media_type,
        size_bytes=asset.size_bytes,
        expires_seconds=int(getattr(settings, "REPORT_UPLOAD_EXPIRES_SECONDS", 900)),
    )
    _audit(
        context=context,
        actor=actor,
        action="report.attachment.upload.create",
        target_type="object_asset",
        target_ref=asset.public_id,
        course_ref=task.course.public_id,
        after={"task_id": task.public_id, "size_bytes": asset.size_bytes},
    )
    _emit(
        event_type=events.ATTACHMENT_UPLOAD_CREATED,
        aggregate_type="object_asset",
        aggregate_ref=asset.public_id,
        payload={"task_id": task.public_id, "course_id": task.course.public_id},
        trace_id=_trace(context),
    )
    return asset, upload


@transaction.atomic
def request_attachment_scan(
    *, task_id: str, asset_id: str, actor: User, expected_version: int, context: ActorContext
) -> ObjectAsset:
    task = _locked_task(task_id=task_id, actor=actor)
    _require_report_task(task)
    _require_task_scope(task)
    try:
        asset = ObjectAsset.objects.select_for_update().get(
            public_id=asset_id, owner_type=REPORT_OWNER, owner_ref=task.public_id
        )
    except ObjectAsset.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if asset.row_version != expected_version:
        raise RowVersionConflict(detail={"expected_row_version": expected_version})
    if asset.scan_status != ObjectAsset.ScanStatus.PENDING:
        raise ReportStateConflict(detail={"scan_status": asset.scan_status})
    if task.status not in {ExperimentTask.Status.IN_PROGRESS, ExperimentTask.Status.REPORT_DRAFT}:
        raise ReportStateConflict(detail={"task_status": task.status})
    _audit(
        context=context,
        actor=actor,
        action="report.attachment.scan.request",
        target_type="object_asset",
        target_ref=asset.public_id,
        course_ref=task.course.public_id,
        after={"task_id": task.public_id},
    )
    _emit(
        event_type=events.ATTACHMENT_SCAN_REQUESTED,
        aggregate_type="object_asset",
        aggregate_ref=asset.public_id,
        payload={"task_id": task.public_id, "course_id": task.course.public_id},
        trace_id=_trace(context),
    )
    return asset


def attachment_for_user(*, task_id: str, asset_id: str, actor: User) -> ObjectAsset:
    try:
        task = ExperimentTask.objects.select_related(
            "course", "publication", "enrollment"
        ).get(public_id=task_id, student=actor)
        asset = ObjectAsset.objects.get(
            public_id=asset_id, owner_type=REPORT_OWNER, owner_ref=task.public_id
        )
    except (ExperimentTask.DoesNotExist, ObjectAsset.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    if not task.publication.report_required or not _task_scope_matches(task):
        raise ResourceNotFound()
    return asset


def _magic_matches(asset: ObjectAsset, stream: Any) -> bool:
    suffix = PurePath(asset.original_name).suffix.casefold()
    head = stream.read(512)
    stream.seek(0)
    if suffix == ".pdf":
        return head.startswith(b"%PDF-")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(stream) as archive:
                names = set(archive.namelist())
                return "[Content_Types].xml" in names and any(
                    name.startswith("word/") for name in names
                )
        except zipfile.BadZipFile:
            return False
        finally:
            stream.seek(0)
    try:
        return b"\x00" not in head and head.decode("utf-8") is not None
    except UnicodeDecodeError:
        return False


def _mark_scan_failed(
    asset: ObjectAsset,
    *,
    code: str,
    status: str = ObjectAsset.ScanStatus.FAILED,
    object_version: str | None = None,
) -> ObjectAsset:
    changes: dict[str, Any] = {
        "scan_status": status,
        "failure_code": code,
        "scan_completed_at": timezone.now(),
    }
    if object_version is not None:
        changes["object_version"] = object_version
    return compare_and_swap(
        ObjectAsset,
        pk=asset.pk,
        expected_version=asset.row_version,
        changes=changes,
    )


def _delete_or_compensate(asset: ObjectAsset, *, trace_id: str) -> None:
    try:
        object_storage().delete_object(
            bucket=asset.bucket, object_key=asset.object_key, version_id=asset.object_version
        )
    except Exception:
        current = ObjectAsset.objects.get(pk=asset.pk)
        if current.status == ObjectAsset.Status.ACTIVE:
            current = compare_and_swap(
                ObjectAsset,
                pk=current.pk,
                expected_version=current.row_version,
                changes={"status": ObjectAsset.Status.PURGE_PENDING},
            )
        create_compensation(
            task_type="DELETE_REPORT_ASSET",
            subject_type="OBJECT_ASSET",
            subject_ref=asset.public_id,
            payload={"asset_id": asset.public_id},
            trace_id=trace_id,
        )
        transaction.on_commit(lambda: run_compensations.delay(trace_id=trace_id), robust=True)
    else:
        current = ObjectAsset.objects.get(pk=asset.pk)
        record_purge_result(
            asset_id=current.pk,
            expected_version=current.row_version,
            result=ObjectPurgeLog.Result.PURGED,
            trace_id=trace_id,
            reason="report attachment scan rejected",
        )


def delete_report_asset_compensation(task: CompensationTask) -> None:
    asset = ObjectAsset.objects.get(public_id=task.subject_ref)
    object_storage().delete_object(
        bucket=asset.bucket, object_key=asset.object_key, version_id=asset.object_version
    )
    record_purge_result(
        asset_id=asset.pk,
        expected_version=asset.row_version,
        result=ObjectPurgeLog.Result.PURGED,
        trace_id=task.trace_id,
        reason="report attachment scan rejected",
    )


def _record_scan(*, asset: ObjectAsset, trace_id: str) -> None:
    append_audit(
        actor_ref="SYSTEM",
        actor_portal="WORKER",
        actor_context={},
        action="report.attachment.scan.complete",
        target_type="object_asset",
        target_ref=asset.public_id,
        course_ref="",
        after={"scan_status": asset.scan_status, "failure_code": asset.failure_code},
        result="SUCCEEDED" if asset.scan_status == ObjectAsset.ScanStatus.CLEAN else "FAILED",
        error_code=asset.failure_code,
        trace_id=trace_id,
    )
    _emit(
        event_type=events.ATTACHMENT_SCAN_COMPLETED,
        aggregate_type="object_asset",
        aggregate_ref=asset.public_id,
        payload={"scan_status": asset.scan_status, "failure_code": asset.failure_code},
        trace_id=trace_id,
    )


def scan_report_attachment(*, asset_id: str, trace_id: str) -> ObjectAsset:
    asset = ObjectAsset.objects.get(public_id=asset_id, owner_type=REPORT_OWNER)
    if asset.scan_status != ObjectAsset.ScanStatus.PENDING:
        return asset
    stored = None
    try:
        stored = object_storage().open_object(bucket=asset.bucket, object_key=asset.object_key)
        with tempfile.SpooledTemporaryFile(max_size=asset.size_bytes) as stream:
            digest = hashlib.sha256()
            size = 0
            for chunk in iter_chunks(stored.body):
                size += len(chunk)
                if size > asset.size_bytes:
                    raise ReportUploadInvalid(detail={"size_bytes": "too_large"})
                digest.update(chunk)
                stream.write(chunk)
            if size != asset.size_bytes or stored.content_length != asset.size_bytes:
                raise ReportUploadInvalid(detail={"size_bytes": "mismatch"})
            if stored.content_type.split(";", 1)[0].strip() != asset.media_type:
                raise ReportUploadInvalid(detail={"media_type": "mismatch"})
            if digest.hexdigest() != asset.digest_sha256:
                raise ReportUploadInvalid(detail={"digest_sha256": "mismatch"})
            stream.seek(0)
            if not _magic_matches(asset, stream):
                raise ReportUploadInvalid(detail={"magic": "mismatch"})
            stream.seek(0)
            result = ClamAVScanner().scan(iter_chunks(stream))
            if not result.clean:
                raise ReportUploadInvalid(detail={"malware": "detected"})
    except (ReportUploadInvalid, AntivirusUnavailable) as exc:
        infected = bool(getattr(exc, "detail", {}).get("malware"))
        code = (
            "ASSET_MALWARE_DETECTED"
            if infected
            else (
                "ASSET_SCAN_UNAVAILABLE"
                if isinstance(exc, AntivirusUnavailable)
                else "ASSET_VALIDATION_FAILED"
            )
        )
        with transaction.atomic():
            locked = ObjectAsset.objects.select_for_update().get(pk=asset.pk)
            if locked.scan_status != ObjectAsset.ScanStatus.PENDING:
                return locked
            changed = _mark_scan_failed(
                locked,
                code=code,
                status=(
                    ObjectAsset.ScanStatus.INFECTED
                    if infected
                    else ObjectAsset.ScanStatus.FAILED
                ),
                object_version=stored.version_id if stored is not None else None,
            )
            append_failure(
                failure_type="REPORT_ATTACHMENT_SCAN",
                subject_type="OBJECT_ASSET",
                subject_ref=asset.public_id,
                error_code=code,
                message="Report attachment rejected",
                detail=getattr(exc, "detail", {}),
                retryable=False,
                trace_id=trace_id,
            )
            _record_scan(asset=changed, trace_id=trace_id)
            REPORT_ATTACHMENT_SCANS_TOTAL.labels(result="failed").inc()
        _delete_or_compensate(changed, trace_id=trace_id)
        return changed
    finally:
        stored_body = locals().get("stored")
        if stored_body is not None:
            stored_body.body.close()

    missing_scope: ObjectAsset | None = None
    with transaction.atomic():
        locked = ObjectAsset.objects.select_for_update().get(pk=asset.pk)
        if locked.scan_status != ObjectAsset.ScanStatus.PENDING:
            return locked
        changed = locked
        try:
            task = (
                ExperimentTask.objects.select_for_update()
                .select_related("course", "publication", "enrollment", "student")
                .get(public_id=locked.owner_ref, publication__report_required=True)
            )
            if not _task_scope_matches(task):
                raise ReportStateConflict(detail={"task_scope": "course_or_student_mismatch"})
            draft = ReportDraft.objects.select_for_update().get(task=task, student=task.student)
        except (ExperimentTask.DoesNotExist, ReportDraft.DoesNotExist, ReportStateConflict):
            changed = _mark_scan_failed(locked, code="REPORT_SCOPE_NOT_FOUND")
            _record_scan(asset=changed, trace_id=trace_id)
            missing_scope = changed
        else:
            if not stored.version_id:
                changed = _mark_scan_failed(locked, code="ASSET_VERSION_NOT_PINNED")
                _record_scan(asset=changed, trace_id=trace_id)
                missing_scope = changed
            else:
                changed = compare_and_swap(
                    ObjectAsset,
                    pk=locked.pk,
                    expected_version=locked.row_version,
                    changes={
                        "scan_status": ObjectAsset.ScanStatus.CLEAN,
                        "failure_code": "",
                        "object_version": stored.version_id,
                        "scan_completed_at": timezone.now(),
                    },
                )
                ReportAttachment.objects.get_or_create(
                    draft=draft,
                    asset=changed,
                    defaults={"uploaded_by": task.student, "trace_id": trace_id},
                )
                _record_scan(asset=changed, trace_id=trace_id)
                _audit(
                    context=ActorContext("SYSTEM", "WORKER", trace_id, "", ""),
                    actor=None,
                    action="report.attachment.register",
                    target_type="object_asset",
                    target_ref=changed.public_id,
                    course_ref=task.course.public_id,
                    after={"task_id": task.public_id, "scan_status": changed.scan_status},
                )
                REPORT_ATTACHMENT_SCANS_TOTAL.labels(result="clean").inc()
    if missing_scope is not None:
        _delete_or_compensate(missing_scope, trace_id=trace_id)
        return missing_scope
    return changed


def fail_report_attachment_scan(*, asset_id: str, trace_id: str, code: str) -> ObjectAsset:
    with transaction.atomic():
        asset = ObjectAsset.objects.select_for_update().get(
            public_id=asset_id, owner_type=REPORT_OWNER
        )
        if asset.scan_status != ObjectAsset.ScanStatus.PENDING:
            return asset
        changed = _mark_scan_failed(asset, code=code)
        append_failure(
            failure_type="REPORT_ATTACHMENT_SCAN",
            subject_type="OBJECT_ASSET",
            subject_ref=asset.public_id,
            error_code=code,
            message="Report attachment scan failed",
            detail={},
            retryable=False,
            trace_id=trace_id,
        )
        _record_scan(asset=changed, trace_id=trace_id)
        REPORT_ATTACHMENT_SCANS_TOTAL.labels(result="failed").inc()
    _delete_or_compensate(changed, trace_id=trace_id)
    return changed


@transaction.atomic
def submit_report(
    *, task_id: str, actor: User, expected_task_version: int, context: ActorContext
) -> tuple[ReportVersion, ExperimentTask]:
    task = _locked_task(task_id=task_id, actor=actor)
    _require_report_task(task)
    _require_task_scope(task)
    if (
        task.enrollment.status != Enrollment.Status.ACTIVE
    ):
        raise ReportStateConflict(detail={"enrollment_status": task.enrollment.status})
    if task.row_version != expected_task_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_task_version,
                "actual_row_version": task.row_version,
            }
        )
    if task.status not in {ExperimentTask.Status.IN_PROGRESS, ExperimentTask.Status.REPORT_DRAFT}:
        raise ReportStateConflict(detail={"task_status": task.status})
    try:
        draft = ReportDraft.objects.select_for_update().get(task=task, student=actor)
    except ReportDraft.DoesNotExist as exc:
        raise ReportStateConflict(detail={"draft": "not_initialized"}) from exc
    if draft.status != ReportDraft.Status.DRAFT:
        raise ReportStateConflict(detail={"draft_status": draft.status})
    if not draft.body_markdown.strip():
        raise ReportStateConflict(detail={"body_markdown": "required"})
    _lock_workspace_sessions(task)
    snapshot = _latest_snapshot(task)
    if snapshot is None or not _snapshot_is_valid(snapshot, task):
        raise ReportSnapshotConflict(detail={"snapshot": "missing_or_not_clean"})
    if (
        draft.workspace_snapshot_id != snapshot.pk
        or draft.snapshot_digest != snapshot.digest_sha256
    ):
        raise ReportSnapshotConflict(
            detail={
                "draft_snapshot_digest": draft.snapshot_digest,
                "latest_snapshot_digest": snapshot.digest_sha256,
            }
        )
    execution = _latest_execution_for_submission(task=task, snapshot=snapshot)
    pending = ObjectAsset.objects.filter(
        owner_type=REPORT_OWNER,
        owner_ref=task.public_id,
        scan_status=ObjectAsset.ScanStatus.PENDING,
        status=ObjectAsset.Status.ACTIVE,
    ).exists()
    if pending:
        raise ReportAttachmentNotReady(detail={"scan_status": ObjectAsset.ScanStatus.PENDING})
    # The task and draft locks also serialize attachment registration by the scan worker.
    # ReportAttachment stays append-only, so its runtime grant does not need UPDATE solely
    # to satisfy MySQL's SELECT ... FOR UPDATE privilege requirement.
    attachments = list(
        ReportAttachment.objects.select_related("asset")
        .filter(draft=draft)
        .order_by("created_at", "id")
    )
    if any(
        item.asset.scan_status != ObjectAsset.ScanStatus.CLEAN
        or item.asset.status != ObjectAsset.Status.ACTIVE
        for item in attachments
    ):
        raise ReportAttachmentNotReady()
    version_no = (
        ReportVersion.objects.filter(task=task).aggregate(value=Max("version_no"))["value"] or 0
    ) + 1
    submitted_at = timezone.now()
    version = ReportVersion.objects.create(
        task=task,
        draft=draft,
        student=actor,
        version_no=version_no,
        body_markdown=draft.body_markdown,
        body_digest=hashlib.sha256(draft.body_markdown.encode()).hexdigest(),
        workspace_snapshot=snapshot,
        snapshot_digest=snapshot.digest_sha256,
        execution_run=execution,
        execution_status=execution.status,
        execution_result_summary=execution.result_summary,
        execution_rule_summary=dict(execution.execution_rule_summary or {}),
        execution_rule_digest=execution.execution_rule_digest,
        execution_snapshot=execution.snapshot,
        execution_snapshot_digest=execution.snapshot.digest_sha256,
        execution_stdout_asset=execution.stdout_asset,
        execution_stderr_asset=execution.stderr_asset,
        execution_test_report_asset=execution.test_report_asset,
        submitted_by=actor,
        submitted_at=submitted_at,
        trace_id=_trace(context),
    )
    ReportVersionAttachment.objects.bulk_create([
        ReportVersionAttachment(
            version=version, attachment=item, asset_digest=item.asset.digest_sha256
        )
        for item in attachments
    ])
    compare_and_swap(
        ReportDraft,
        pk=draft.pk,
        expected_version=draft.row_version,
        changes={"status": ReportDraft.Status.SUBMITTED, "submitted_at": submitted_at},
    )
    changed_task = transition_task(
        task_id=task.public_id,
        to_status=ExperimentTask.Status.UNDER_REVIEW,
        actor=actor,
        expected_version=task.row_version,
        trigger="REPORT_SUBMITTED",
        reason="student submitted report",
        context=context,
        detail={"report_version_id": version.public_id, "version_no": version.version_no},
    )
    from apps.reviews.services import create_review_for_submission

    create_review_for_submission(
        task=changed_task,
        report_version=version,
        context=context,
    )
    _audit(
        context=context,
        actor=actor,
        action="report.submit",
        target_type="report_version",
        target_ref=version.public_id,
        course_ref=task.course.public_id,
        after={
            "task_id": task.public_id,
            "version_no": version.version_no,
            "snapshot_digest": version.snapshot_digest,
            "attachment_count": len(attachments),
            "execution_run_id": execution.public_id,
            "execution_status": execution.status,
            "execution_rule_digest": execution.execution_rule_digest,
        },
    )
    _emit(
        event_type=events.REPORT_SUBMITTED,
        aggregate_type="report_version",
        aggregate_ref=version.public_id,
        payload={
            "task_id": task.public_id,
            "course_id": task.course.public_id,
            "version_no": version.version_no,
            "body_digest": version.body_digest,
            "snapshot_digest": version.snapshot_digest,
            "execution_run_id": execution.public_id,
            "execution_status": execution.status,
            "execution_rule_digest": execution.execution_rule_digest,
            "execution_snapshot_id": execution.snapshot.public_id,
            "stdout_asset_id": execution.stdout_asset.public_id
            if execution.stdout_asset_id
            else None,
            "stderr_asset_id": execution.stderr_asset.public_id
            if execution.stderr_asset_id
            else None,
            "test_report_asset_id": execution.test_report_asset.public_id
            if execution.test_report_asset_id
            else None,
        },
        trace_id=_trace(context),
    )
    REPORT_SUBMISSIONS_TOTAL.labels(result="submitted").inc()
    return version, changed_task


@transaction.atomic
def complete_non_report_task(
    *, task_id: str, actor: User, expected_task_version: int, context: ActorContext
) -> tuple[SystemArtifact, ExperimentTask]:
    task = _locked_task(task_id=task_id, actor=actor)
    if task.publication.report_required:
        raise ReportStateConflict(detail={"report_required": True})
    _require_task_scope(task)
    if task.row_version != expected_task_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_task_version,
                "actual_row_version": task.row_version,
            }
        )
    if task.status != ExperimentTask.Status.IN_PROGRESS:
        raise ReportStateConflict(detail={"task_status": task.status})
    if task.enrollment.status != Enrollment.Status.ACTIVE:
        raise ReportStateConflict(detail={"enrollment_status": task.enrollment.status})
    _lock_workspace_sessions(task)
    snapshot = _latest_snapshot(task)
    if snapshot is None or not _snapshot_is_valid(snapshot, task):
        raise ReportSnapshotConflict(detail={"snapshot": "missing_or_not_clean"})
    execution = None
    if (task.execution_spec or {}).get("schema_version") == 2:
        execution = _latest_execution_for_submission(task=task, snapshot=snapshot)
    artifact = SystemArtifact.objects.create(
        task=task,
        student=actor,
        workspace_snapshot=snapshot,
        asset=snapshot.asset,
        kind=SystemArtifact.Kind.WORKSPACE_SNAPSHOT,
        digest_sha256=snapshot.digest_sha256,
        execution_run=execution,
        execution_evidence={
            "status": execution.status,
            "rule_summary": execution.execution_rule_summary,
            "rule_digest": execution.execution_rule_digest,
            "snapshot_id": snapshot.public_id,
            "snapshot_digest": snapshot.digest_sha256,
            "stdout_asset_id": execution.stdout_asset.public_id if execution.stdout_asset else None,
            "stderr_asset_id": execution.stderr_asset.public_id if execution.stderr_asset else None,
            "test_report_asset_id": (
                execution.test_report_asset.public_id if execution.test_report_asset else None
            ),
        } if execution else {},
        trace_id=_trace(context),
    )
    changed_task = transition_task(
        task_id=task.public_id,
        to_status=ExperimentTask.Status.UNDER_REVIEW,
        actor=actor,
        expected_version=task.row_version,
        trigger="SYSTEM_ARTIFACT_SUBMITTED",
        reason="student submitted system artifact",
        context=context,
        detail={"artifact_id": artifact.public_id, "digest_sha256": artifact.digest_sha256},
    )
    from apps.reviews.services import create_review_for_submission

    create_review_for_submission(
        task=changed_task,
        system_artifact=artifact,
        context=context,
    )
    _audit(
        context=context,
        actor=actor,
        action="report.system_artifact.submit",
        target_type="system_artifact",
        target_ref=artifact.public_id,
        course_ref=task.course.public_id,
        after={"task_id": task.public_id, "digest_sha256": artifact.digest_sha256},
    )
    _emit(
        event_type=events.SYSTEM_ARTIFACT_SUBMITTED,
        aggregate_type="system_artifact",
        aggregate_ref=artifact.public_id,
        payload={
            "task_id": task.public_id,
            "course_id": task.course.public_id,
            "artifact_id": artifact.public_id,
            "digest_sha256": artifact.digest_sha256,
        },
        trace_id=_trace(context),
    )
    return artifact, changed_task


def authorize_report_asset_download(asset: ObjectAsset, actor: User, portal: str) -> str:
    task: ExperimentTask | None = None
    if asset.owner_type == REPORT_OWNER:
        link = (
            ReportAttachment.objects.select_related(
                "draft__task__course",
                "draft__task__publication",
                "draft__task__enrollment",
                "draft__task__student",
            )
            .filter(asset=asset)
            .first()
        )
        if link and (
            portal != "TEACHING"
            or ReportVersionAttachment.objects.filter(
                attachment=link,
                version__task=link.draft.task,
                version__draft=link.draft,
            ).exists()
        ):
            task = link.draft.task
    elif asset.owner_type == "WORKSPACE_TASK":
        artifact = (
            SystemArtifact.objects.select_related("task__course", "task__student")
            .filter(asset=asset)
            .first()
        )
        if artifact:
            task = artifact.task
    elif asset.owner_type == "WORKSPACE_EXECUTION":
        version = (
            ReportVersion.objects.select_related(
                "task__course",
                "task__publication",
                "task__enrollment",
                "task__student",
                "execution_run",
            )
            .filter(execution_stdout_asset=asset)
            .first()
        )
        if version is None:
            version = (
                ReportVersion.objects.select_related(
                    "task__course",
                    "task__publication",
                    "task__enrollment",
                    "task__student",
                    "execution_run",
                )
                .filter(execution_stderr_asset=asset)
                .first()
            )
        if version is None:
            version = (
                ReportVersion.objects.select_related(
                    "task__course",
                    "task__publication",
                    "task__enrollment",
                    "task__student",
                    "execution_run",
                )
                .filter(execution_test_report_asset=asset)
                .first()
            )
        if version is not None and version.execution_run_id:
            run = version.execution_run
            if (
                run.public_id == asset.owner_ref
                and run.task_id == version.task_id
                and version.execution_snapshot_id == version.workspace_snapshot_id
            ):
                task = version.task
    if task is None:
        raise ResourceNotFound()
    if not task.publication.report_required and asset.owner_type == REPORT_OWNER:
        raise ResourceNotFound()
    if not _task_scope_matches(task):
        raise ResourceNotFound()
    if asset.owner_ref != task.public_id:
        raise ResourceNotFound()
    if asset.owner_type == "WORKSPACE_TASK" and not SystemArtifact.objects.filter(
        task=task, asset=asset, workspace_snapshot__task=task
    ).exists():
        raise ResourceNotFound()
    if portal == "USER":
        if task.student_id != actor.pk:
            raise ResourceNotFound()
    elif portal == "TEACHING":
        require_course_capability(
            course=task.course,
            actor=actor,
            capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
        )
    else:
        raise ResourceNotFound()
    return task.course.public_id


def report_preview_for_teaching(*, actor: User, course_id: str, task_id: str) -> dict[str, Any]:
    from apps.courses.models import Course

    try:
        course = Course.objects.get(public_id=course_id)
        task = ExperimentTask.objects.select_related(
            "student", "publication", "enrollment", "course"
        ).get(
            public_id=task_id, course=course
        )
    except (Course.DoesNotExist, ExperimentTask.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course,
        actor=actor,
        capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
    )
    if not _task_scope_matches(task):
        raise ResourceNotFound()
    if task.publication.report_required:
        version = (
            ReportVersion.objects.select_related(
                "student",
                "execution_run__session",
                "execution_snapshot",
                "execution_stdout_asset",
                "execution_stderr_asset",
                "execution_test_report_asset",
            )
            .prefetch_related("attachments__attachment__asset")
            .filter(task=task)
            .order_by("-version_no")
            .first()
        )
        if version is None:
            raise ResourceNotFound()
        if any(
            row.attachment.asset.scan_status != ObjectAsset.ScanStatus.CLEAN
            or row.attachment.asset.status != ObjectAsset.Status.ACTIVE
            or not _task_scope_matches(row.attachment.draft.task)
            for row in version.attachments.all()
        ):
            raise ResourceNotFound()
        if not _snapshot_is_valid(version.workspace_snapshot, task):
            raise ResourceNotFound()
        if version.execution_run_id and not _report_execution_is_consistent(version, task):
            raise ResourceNotFound()
        return {"kind": "REPORT", "task_id": task.public_id, "version": version}
    artifact = (
        SystemArtifact.objects.select_related("task", "student", "asset")
        .filter(task=task)
        .order_by("-created_at")
        .first()
    )
    if artifact is None:
        raise ResourceNotFound()
    if (
        artifact.student_id != task.student_id
        or not _snapshot_is_valid(artifact.workspace_snapshot, task)
        or artifact.asset_id != artifact.workspace_snapshot.asset_id
    ):
        raise ResourceNotFound()
    return {"kind": "SYSTEM_ARTIFACT", "task_id": task.public_id, "artifact": artifact}


def scan_anomaly_summary() -> dict[str, Any]:
    assets = ObjectAsset.objects.filter(owner_type=REPORT_OWNER).select_related()
    result: dict[str, Any] = {"counts": {}, "items": []}
    for status in ObjectAsset.ScanStatus.values:
        count = assets.filter(scan_status=status).count()
        if count:
            result["counts"][status] = count
    rows = assets.exclude(scan_status=ObjectAsset.ScanStatus.CLEAN).order_by("-created_at")[:100]
    result["items"] = [
        {
            "asset_id": asset.public_id,
            "task_id": asset.owner_ref,
            "scan_status": asset.scan_status,
            "failure_code": asset.failure_code,
            "created_at": asset.created_at,
        }
        for asset in rows
    ]
    return result

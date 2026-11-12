import hashlib
import secrets
import tempfile
import zipfile
from pathlib import PurePath
from typing import Any

from django.conf import settings
from django.db import transaction
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
from apps.courses.models import CourseStaffGrant
from apps.courses.selectors import require_course_capability
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask

from . import events
from .errors import (
    ReportStateConflict,
    ReportUploadInvalid,
)
from .metrics import REPORT_ATTACHMENT_SCANS_TOTAL
from .models import (
    ReportAttachment,
    ReportDraft,
    ReportVersionAttachment,
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
    from apps.experiments.assessment import _task
    return _task(actor, task_id, write=True)


def _require_report_task(task: ExperimentTask) -> None:
    from apps.experiments.models import PublicationTask
    if not PublicationTask.objects.filter(
        publication_chapter__publication_id=task.publication_id, task_type="PROGRAMMING",
    ).exists():
        raise ReportStateConflict(detail={"report": "programming_section_required"})


def _require_report_editable(task: ExperimentTask, actor: User) -> None:
    from apps.experiments.assessment import _task, _writable
    _writable(_task(actor, task.public_id, write=True), "PROGRAMMING")


def _task_scope_matches(task: ExperimentTask) -> bool:
    return (
        task.course_id == task.publication.course_id
        and task.course_id == task.enrollment.course_id
        and task.student_id == task.enrollment.student_id
    )


def _require_task_scope(task: ExperimentTask) -> None:
    if not _task_scope_matches(task):
        raise ReportStateConflict(detail={"task_scope": "course_or_student_mismatch"})


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
    _require_report_editable(task, actor)
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
    _require_report_editable(task, actor)
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
    if not _task_scope_matches(task):
        raise ResourceNotFound()
    _require_report_task(task)
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
                .get(public_id=locked.owner_ref)
            )
            _require_report_task(task)
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


def authorize_report_asset_download(asset: ObjectAsset, actor: User, portal: str) -> str:
    link = ReportAttachment.objects.select_related(
        "draft__task__course", "draft__task__publication", "draft__task__enrollment",
    ).filter(asset=asset, asset__owner_type=REPORT_OWNER).first()
    if link is None:
        raise ResourceNotFound()
    task = link.draft.task
    if asset.owner_ref != task.public_id or not _task_scope_matches(task):
        raise ResourceNotFound()
    if portal == "USER":
        if task.student_id != actor.pk or task.enrollment.status != "ACTIVE":
            raise ResourceNotFound()
    elif portal == "TEACHING":
        if not ReportVersionAttachment.objects.filter(attachment=link).exists():
            raise ResourceNotFound()
        require_course_capability(course=task.course, actor=actor,
                                  capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION)
    else:
        raise ResourceNotFound()
    return task.course.public_id


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

import hashlib
import re
import tempfile
import zipfile
from pathlib import PurePath
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.antivirus import AntivirusUnavailable, ClamAVScanner
from apps.core.audit import append_audit, append_failure
from apps.core.compensation import create_compensation
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.identifiers import new_ulid
from apps.core.models import CompensationTask, ObjectAsset
from apps.core.object_storage import iter_chunks, object_storage
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.core.tasks import run_compensations
from apps.courses.models import CourseStaffGrant
from apps.courses.services import ActorContext

from . import events
from .errors import TemplateStateConflict, TemplateUploadInvalid
from .models import Template, TemplateVersion
from .services import _audit, _course, _event

PURPOSE_FIELDS = {
    "MANUAL": "manual_asset",
    "STARTER": "starter_asset",
    "REPORT_TEMPLATE": "report_template_asset",
    # TESTS assets are referenced by execution_spec.tests_asset instead of a
    # mutable foreign-key slot on the version.
    "TESTS": None,
    "BUILD_CONTEXT": None,
}
ALLOWED_FILES = {
    "MANUAL": {
        ".pdf": "application/pdf",
        ".md": "text/markdown",
        ".txt": "text/plain",
    },
    "STARTER": {
        ".zip": "application/zip",
        ".tar": "application/x-tar",
        ".gz": "application/gzip",
        ".tgz": "application/gzip",
    },
    "REPORT_TEMPLATE": {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf": "application/pdf",
        ".md": "text/markdown",
        ".txt": "text/plain",
    },
    "TESTS": {
        ".json": "application/json",
        ".txt": "text/plain",
        ".zip": "application/zip",
        ".tar": "application/x-tar",
        ".gz": "application/gzip",
        ".tgz": "application/gzip",
    },
    "BUILD_CONTEXT": {
        ".zip": "application/zip",
        ".tar": "application/x-tar",
        ".gz": "application/gzip",
        ".tgz": "application/gzip",
    },
}
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _safe_name(value: str) -> str:
    name = PurePath(value.replace("\\", "/")).name
    if not name or len(name) > 255 or name in {".", ".."}:
        raise TemplateUploadInvalid(detail={"file_name": "invalid"})
    return name


def _validate_declaration(
    *, purpose: str, file_name: str, media_type: str, size_bytes: int, digest_sha256: str
) -> str:
    if purpose not in PURPOSE_FIELDS:
        raise TemplateUploadInvalid(detail={"purpose": "unsupported"})
    clean_name = _safe_name(file_name)
    suffix = PurePath(clean_name).suffix.casefold()
    expected_media_type = ALLOWED_FILES[purpose].get(suffix)
    if expected_media_type is None or media_type != expected_media_type:
        raise TemplateUploadInvalid(detail={"media_type": "extension_and_declared_type_mismatch"})
    if not 1 <= size_bytes <= settings.TEMPLATE_ASSET_MAX_BYTES:
        raise TemplateUploadInvalid(detail={"size_bytes": "outside_allowed_range"})
    if not DIGEST_PATTERN.fullmatch(digest_sha256):
        raise TemplateUploadInvalid(detail={"digest_sha256": "invalid"})
    return clean_name


@transaction.atomic
def create_asset_upload(
    *,
    course_id: str,
    template_id: str,
    version_id: str,
    actor: User,
    expected_version: int,
    purpose: str,
    file_name: str,
    media_type: str,
    size_bytes: int,
    digest_sha256: str,
    context: ActorContext,
) -> tuple[ObjectAsset, dict[str, Any]]:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        template = Template.objects.get(public_id=template_id, course=course)
        version = TemplateVersion.objects.select_for_update().get(
            public_id=version_id, template=template
        )
    except (Template.DoesNotExist, TemplateVersion.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    if version.row_version != expected_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_version,
                "actual_row_version": version.row_version,
            }
        )
    if version.status not in {TemplateVersion.Status.DRAFT, TemplateVersion.Status.PRECHECK_FAILED}:
        raise TemplateStateConflict(detail={"status": version.status})
    normalized_purpose = purpose.upper()
    normalized_digest = digest_sha256.casefold()
    clean_name = _validate_declaration(
        purpose=normalized_purpose,
        file_name=file_name,
        media_type=media_type,
        size_bytes=size_bytes,
        digest_sha256=normalized_digest,
    )
    asset_id = new_ulid()
    object_key = f"template-assets/{version.public_id}/{asset_id}/{clean_name}"
    asset = ObjectAsset.objects.create(
        public_id=asset_id,
        bucket=settings.MINIO_BUCKET,
        object_key=object_key,
        digest_sha256=normalized_digest,
        size_bytes=size_bytes,
        media_type=media_type,
        original_name=clean_name,
        owner_type="TEMPLATE_VERSION",
        owner_ref=version.public_id,
        purpose=normalized_purpose,
    )
    upload = object_storage(public=True).create_upload_post(
        bucket=asset.bucket,
        object_key=asset.object_key,
        media_type=asset.media_type,
        size_bytes=asset.size_bytes,
        expires_seconds=settings.TEMPLATE_UPLOAD_EXPIRES_SECONDS,
    )
    _audit(
        context,
        action="labtemplate.asset.upload.create",
        target_type="object_asset",
        target_ref=asset.public_id,
        course_ref=course.public_id,
        after={
            "template_version_id": version.public_id,
            "purpose": asset.purpose,
            "size_bytes": asset.size_bytes,
        },
    )
    _event(
        context,
        event_type=events.ASSET_UPLOAD_CREATED,
        aggregate_type="object_asset",
        aggregate_ref=asset.public_id,
        payload={
            "course_id": course.public_id,
            "template_version_id": version.public_id,
            "purpose": asset.purpose,
        },
    )
    return asset, upload


def asset_for_course(
    *, actor: User, course_id: str, template_id: str, asset_id: str
) -> tuple[ObjectAsset, TemplateVersion]:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        asset = ObjectAsset.objects.get(
            public_id=asset_id,
            owner_type="TEMPLATE_VERSION",
        )
        version = TemplateVersion.objects.select_related("template").get(
            public_id=asset.owner_ref,
            template__public_id=template_id,
            template__course=course,
        )
    except (ObjectAsset.DoesNotExist, TemplateVersion.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    return asset, version


@transaction.atomic
def complete_asset_upload(
    *,
    actor: User,
    course_id: str,
    template_id: str,
    asset_id: str,
    expected_version: int,
    context: ActorContext,
) -> ObjectAsset:
    asset, version = asset_for_course(
        actor=actor, course_id=course_id, template_id=template_id, asset_id=asset_id
    )
    asset = ObjectAsset.objects.select_for_update().get(pk=asset.pk)
    if asset.row_version != expected_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_version,
                "actual_row_version": asset.row_version,
            }
        )
    if asset.scan_status != ObjectAsset.ScanStatus.PENDING:
        raise TemplateStateConflict(detail={"scan_status": asset.scan_status})
    _audit(
        context,
        action="labtemplate.asset.scan.request",
        target_type="object_asset",
        target_ref=asset.public_id,
        course_ref=version.template.course.public_id,
        after={"template_version_id": version.public_id, "purpose": asset.purpose},
    )
    _event(
        context,
        event_type=events.ASSET_SCAN_REQUESTED,
        aggregate_type="object_asset",
        aggregate_ref=asset.public_id,
        payload={
            "course_id": version.template.course.public_id,
            "template_version_id": version.public_id,
        },
    )
    return asset


def _magic_matches(asset: ObjectAsset, stream: Any) -> bool:
    suffix = PurePath(asset.original_name).suffix.casefold()
    head = stream.read(512)
    stream.seek(0)
    if suffix == ".pdf":
        return head.startswith(b"%PDF-")
    if suffix in {".gz", ".tgz"}:
        return head.startswith(b"\x1f\x8b")
    if suffix == ".tar":
        return len(head) >= 262 and head[257:262] == b"ustar"
    if suffix in {".zip", ".docx"}:
        if not head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            return False
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
        return True
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return b"\x00" not in head


def _mark_asset_failed(asset: ObjectAsset, *, code: str, infected: bool) -> ObjectAsset:
    return compare_and_swap(
        ObjectAsset,
        pk=asset.pk,
        expected_version=asset.row_version,
        changes={
            "scan_status": (
                ObjectAsset.ScanStatus.INFECTED if infected else ObjectAsset.ScanStatus.FAILED
            ),
            "failure_code": code,
            "scan_completed_at": timezone.now(),
        },
    )


def _delete_or_compensate(asset: ObjectAsset, *, trace_id: str) -> None:
    try:
        object_storage().delete_object(
            bucket=asset.bucket,
            object_key=asset.object_key,
            version_id=asset.object_version,
        )
    except Exception:
        create_compensation(
            task_type="DELETE_TEMPLATE_ASSET",
            subject_type="OBJECT_ASSET",
            subject_ref=asset.public_id,
            payload={"asset_id": asset.public_id},
            trace_id=trace_id,
        )
        transaction.on_commit(lambda: run_compensations.delay(trace_id=trace_id), robust=True)


def _record_scan_result(
    asset: ObjectAsset, *, trace_id: str, result: str, error_code: str = ""
) -> None:
    append_audit(
        actor_ref="SYSTEM",
        actor_portal="WORKER",
        actor_context={},
        action="labtemplate.asset.scan.complete",
        target_type="object_asset",
        target_ref=asset.public_id,
        course_ref="",
        after={"result": result, "error_code": error_code},
        result="SUCCEEDED" if result == ObjectAsset.ScanStatus.CLEAN else "FAILED",
        error_code=error_code,
        trace_id=trace_id,
    )
    append_outbox_event(
        event_type=events.ASSET_SCAN_COMPLETED,
        aggregate_type="object_asset",
        aggregate_ref=asset.public_id,
        payload={"scan_status": result, "error_code": error_code},
        trace_id=trace_id,
    )
    enqueue_relay_after_commit(trace_id=trace_id)


def scan_and_attach_asset(*, asset_id: str, trace_id: str) -> ObjectAsset:
    asset = ObjectAsset.objects.get(public_id=asset_id, owner_type="TEMPLATE_VERSION")
    if asset.scan_status != ObjectAsset.ScanStatus.PENDING:
        return asset
    try:
        stored = object_storage().open_object(
            bucket=asset.bucket,
            object_key=asset.object_key,
        )
        with tempfile.SpooledTemporaryFile(max_size=settings.TEMPLATE_ASSET_MAX_BYTES) as stream:
            digest = hashlib.sha256()
            actual_size = 0
            for chunk in iter_chunks(stored.body):
                actual_size += len(chunk)
                if actual_size > settings.TEMPLATE_ASSET_MAX_BYTES:
                    raise TemplateUploadInvalid(detail={"size_bytes": "too_large"})
                digest.update(chunk)
                stream.write(chunk)
            if actual_size != asset.size_bytes or stored.content_length != asset.size_bytes:
                raise TemplateUploadInvalid(detail={"size_bytes": "mismatch"})
            if stored.content_type.split(";", 1)[0].strip() != asset.media_type:
                raise TemplateUploadInvalid(detail={"media_type": "mismatch"})
            if digest.hexdigest() != asset.digest_sha256:
                raise TemplateUploadInvalid(detail={"digest_sha256": "mismatch"})
            stream.seek(0)
            if not _magic_matches(asset, stream):
                raise TemplateUploadInvalid(detail={"magic": "mismatch"})
            stream.seek(0)
            result = ClamAVScanner().scan(iter_chunks(stream))
            if not result.clean:
                raise TemplateUploadInvalid(
                    detail={"malware": "detected", "signature": result.signature}
                )
    except TemplateUploadInvalid as exc:
        infected = exc.detail.get("malware") == "detected"
        with transaction.atomic():
            locked = ObjectAsset.objects.select_for_update().get(pk=asset.pk)
            changed = _mark_asset_failed(
                locked,
                code="ASSET_MALWARE_DETECTED" if infected else "ASSET_VALIDATION_FAILED",
                infected=infected,
            )
            append_failure(
                failure_type="TEMPLATE_ASSET_SCAN",
                subject_type="OBJECT_ASSET",
                subject_ref=asset.public_id,
                error_code=changed.failure_code,
                message="Template asset rejected",
                detail=exc.detail,
                retryable=False,
                trace_id=trace_id,
            )
            _record_scan_result(
                changed,
                trace_id=trace_id,
                result=changed.scan_status,
                error_code=changed.failure_code,
            )
        _delete_or_compensate(changed, trace_id=trace_id)
        return changed
    except AntivirusUnavailable:
        raise
    finally:
        body = locals().get("stored")
        if body is not None:
            body.body.close()

    rejected: ObjectAsset | None = None
    with transaction.atomic():
        asset = ObjectAsset.objects.select_for_update().get(pk=asset.pk)
        if asset.scan_status != ObjectAsset.ScanStatus.PENDING:
            return asset
        try:
            version = TemplateVersion.objects.select_for_update().get(
                public_id=asset.owner_ref,
                status__in=(TemplateVersion.Status.DRAFT, TemplateVersion.Status.PRECHECK_FAILED),
            )
        except TemplateVersion.DoesNotExist:
            rejected = _mark_asset_failed(asset, code="TEMPLATE_VERSION_NOT_DRAFT", infected=False)
            _record_scan_result(
                rejected,
                trace_id=trace_id,
                result=rejected.scan_status,
                error_code=rejected.failure_code,
            )
        else:
            changed = compare_and_swap(
                ObjectAsset,
                pk=asset.pk,
                expected_version=asset.row_version,
                changes={
                    "scan_status": ObjectAsset.ScanStatus.CLEAN,
                    "failure_code": "",
                    "object_version": stored.version_id,
                    "scan_completed_at": timezone.now(),
                },
            )
            field = PURPOSE_FIELDS[asset.purpose]
            if field is not None:
                compare_and_swap(
                    TemplateVersion,
                    pk=version.pk,
                    expected_version=version.row_version,
                    changes={field + "_id": asset.pk},
                )
            _record_scan_result(changed, trace_id=trace_id, result=changed.scan_status)
    if rejected is not None:
        _delete_or_compensate(rejected, trace_id=trace_id)
        return rejected
    return changed


def fail_unavailable_asset(*, asset_id: str, trace_id: str) -> ObjectAsset:
    with transaction.atomic():
        asset = ObjectAsset.objects.select_for_update().get(public_id=asset_id)
        if asset.scan_status != ObjectAsset.ScanStatus.PENDING:
            return asset
        changed = _mark_asset_failed(asset, code="ASSET_SCAN_UNAVAILABLE", infected=False)
        _record_scan_result(
            changed,
            trace_id=trace_id,
            result=changed.scan_status,
            error_code=changed.failure_code,
        )
    _delete_or_compensate(changed, trace_id=trace_id)
    return changed


def delete_template_asset_compensation(task: CompensationTask) -> None:
    asset = ObjectAsset.objects.get(public_id=task.subject_ref)
    object_storage().delete_object(
        bucket=asset.bucket,
        object_key=asset.object_key,
        version_id=asset.object_version,
    )

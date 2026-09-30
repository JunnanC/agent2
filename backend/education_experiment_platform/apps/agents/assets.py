import hashlib
import tempfile
from pathlib import PurePath
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.antivirus import ClamAVScanner
from apps.core.compensation import create_compensation
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, StateConflict
from apps.core.identifiers import new_ulid
from apps.core.models import ObjectAsset
from apps.core.object_storage import iter_chunks, object_storage
from apps.core.tasks import run_compensations
from apps.courses.services import ActorContext

from .models import AgentSource
from .services import _audit, _course_for_teacher, _event

ALLOWED_SOURCE_MEDIA = {
    ".md": "text/markdown",
    ".txt": "text/plain",
}


def _delete_or_compensate(asset: ObjectAsset, *, trace_id: str) -> None:
    try:
        object_storage().delete_object(
            bucket=asset.bucket,
            object_key=asset.object_key,
            version_id=asset.object_version,
        )
    except Exception:
        create_compensation(
            task_type="DELETE_AGENT_SOURCE_ASSET",
            subject_type="OBJECT_ASSET",
            subject_ref=asset.public_id,
            payload={"asset_id": asset.public_id},
            trace_id=trace_id,
        )
        transaction.on_commit(
            lambda: run_compensations.delay(trace_id=trace_id),
            robust=True,
        )
        return
    locked = ObjectAsset.objects.get(pk=asset.pk)
    compare_and_swap(
        ObjectAsset,
        pk=locked.pk,
        expected_version=locked.row_version,
        changes={"status": ObjectAsset.Status.PURGED},
    )


def delete_agent_source_asset_compensation(task: Any) -> None:
    asset = ObjectAsset.objects.get(public_id=task.subject_ref)
    object_storage().delete_object(
        bucket=asset.bucket,
        object_key=asset.object_key,
        version_id=asset.object_version,
    )


def _safe_name(value: str) -> str:
    name = PurePath(value.replace("\\", "/")).name
    if not name or name in {".", ".."} or len(name) > 255:
        raise StateConflict(detail={"file_name": "invalid"})
    return name


@transaction.atomic
def create_source_asset_upload(
    *,
    course_id: str,
    source_id: str,
    actor: User,
    file_name: str,
    media_type: str,
    size_bytes: int,
    digest_sha256: str,
    context: ActorContext,
) -> tuple[ObjectAsset, dict[str, Any]]:
    course = _course_for_teacher(actor=actor, course_id=course_id)
    try:
        source = AgentSource.objects.get(public_id=source_id, course=course)
    except AgentSource.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if (
        source.status == AgentSource.Status.RETIRED
        or source.knowledge_base.status == source.knowledge_base.Status.RETIRED
    ):
        raise StateConflict(detail={"source": "retired"})
    if source.source_type not in {
        AgentSource.SourceType.STATIC,
        AgentSource.SourceType.TEACHER_FAQ,
        AgentSource.SourceType.LAB_MANUAL,
    }:
        raise StateConflict(detail={"source_type": source.source_type})
    clean_name = _safe_name(file_name)
    expected_media = ALLOWED_SOURCE_MEDIA.get(PurePath(clean_name).suffix.casefold())
    if expected_media is None or media_type != expected_media:
        raise StateConflict(detail={"media_type": "extension_and_declared_type_mismatch"})
    if not 1 <= size_bytes <= settings.AGENT_SOURCE_MAX_BYTES:
        raise StateConflict(detail={"size_bytes": "outside_allowed_range"})
    digest = digest_sha256.casefold()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise StateConflict(detail={"digest_sha256": "invalid"})
    asset_id = new_ulid()
    asset = ObjectAsset.objects.create(
        public_id=asset_id,
        bucket=settings.MINIO_BUCKET,
        object_key=f"agent-sources/{source.public_id}/{asset_id}/{clean_name}",
        digest_sha256=digest,
        size_bytes=size_bytes,
        media_type=media_type,
        original_name=clean_name,
        owner_type="AGENT_SOURCE",
        owner_ref=source.public_id,
        purpose="KNOWLEDGE_SOURCE",
    )
    upload = object_storage(public=True).create_upload_post(
        bucket=asset.bucket,
        object_key=asset.object_key,
        media_type=asset.media_type,
        size_bytes=asset.size_bytes,
        expires_seconds=settings.AGENT_SOURCE_UPLOAD_EXPIRES_SECONDS,
    )
    _audit(
        context,
        action="agent.source_asset.upload.create",
        target_type="object_asset",
        target_ref=asset.public_id,
        course_ref=course.public_id,
        after={"source_id": source.public_id, "size_bytes": asset.size_bytes},
    )
    return asset, upload


@transaction.atomic
def complete_source_asset_upload(
    *,
    course_id: str,
    source_id: str,
    asset_id: str,
    actor: User,
    expected_version: int,
    context: ActorContext,
) -> ObjectAsset:
    course = _course_for_teacher(actor=actor, course_id=course_id)
    try:
        asset = ObjectAsset.objects.select_for_update().get(
            public_id=asset_id,
            owner_type="AGENT_SOURCE",
            owner_ref=source_id,
            scan_status=ObjectAsset.ScanStatus.PENDING,
        )
        source = AgentSource.objects.get(
            public_id=source_id,
            course=course,
        )
    except (ObjectAsset.DoesNotExist, AgentSource.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    if source.status == AgentSource.Status.RETIRED:
        raise StateConflict(detail={"source": "retired"})
    if asset.row_version != expected_version:
        from apps.core.errors import RowVersionConflict

        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_version,
                "actual_row_version": asset.row_version,
            }
        )
    _audit(
        context,
        action="agent.source_asset.scan.request",
        target_type="object_asset",
        target_ref=asset.public_id,
        course_ref=course.public_id,
    )
    from .tasks import scan_agent_source_asset

    transaction.on_commit(
        lambda: scan_agent_source_asset.apply_async(
            kwargs={"asset_id": asset.public_id, "trace_id": context.trace_id},
            queue="q_content",
            task_id=f"agent-source-scan-{asset.public_id}",
        )
    )
    return asset


def scan_source_asset(*, asset_id: str, trace_id: str) -> ObjectAsset:
    asset = ObjectAsset.objects.get(public_id=asset_id, owner_type="AGENT_SOURCE")
    if asset.scan_status != ObjectAsset.ScanStatus.PENDING:
        return asset
    stored = None
    try:
        stored = object_storage().open_object(bucket=asset.bucket, object_key=asset.object_key)
        with tempfile.SpooledTemporaryFile(max_size=settings.AGENT_SOURCE_MAX_BYTES) as stream:
            digest = hashlib.sha256()
            size = 0
            for chunk in iter_chunks(stored.body):
                size += len(chunk)
                if size > settings.AGENT_SOURCE_MAX_BYTES:
                    raise StateConflict(detail={"size_bytes": "too_large"})
                digest.update(chunk)
                stream.write(chunk)
            if size != asset.size_bytes or stored.content_length != asset.size_bytes:
                raise StateConflict(detail={"size_bytes": "mismatch"})
            if stored.content_type.split(";", 1)[0].strip() != asset.media_type:
                raise StateConflict(detail={"media_type": "mismatch"})
            if digest.hexdigest() != asset.digest_sha256:
                raise StateConflict(detail={"digest_sha256": "mismatch"})
            stream.seek(0)
            body = stream.read()
            body.decode("utf-8")
            if b"\x00" in body:
                raise StateConflict(detail={"content": "binary_not_allowed"})
            stream.seek(0)
            result = ClamAVScanner().scan(iter_chunks(stream))
            if not result.clean:
                raise StateConflict(detail={"malware": "detected"})
    except Exception as exc:
        locked = ObjectAsset.objects.get(pk=asset.pk)
        scan_status = ObjectAsset.ScanStatus.INFECTED if (
            isinstance(exc, StateConflict) and exc.detail.get("malware") == "detected"
        ) else ObjectAsset.ScanStatus.FAILED
        changed = compare_and_swap(
            ObjectAsset,
            pk=locked.pk,
            expected_version=locked.row_version,
            changes={
                "scan_status": scan_status,
                "failure_code": (
                    "AGENT_SOURCE_MALWARE" if scan_status == ObjectAsset.ScanStatus.INFECTED
                    else "AGENT_SOURCE_SCAN_FAILED"
                ),
                "scan_completed_at": timezone.now(),
            },
        )
        _delete_or_compensate(changed, trace_id=trace_id)
        raise
    finally:
        if stored is not None:
            stored.body.close()
    locked = ObjectAsset.objects.get(pk=asset.pk)
    changed = compare_and_swap(
        ObjectAsset,
        pk=locked.pk,
        expected_version=locked.row_version,
        changes={
            "scan_status": ObjectAsset.ScanStatus.CLEAN,
            "object_version": stored.version_id,
            "failure_code": "",
            "scan_completed_at": timezone.now(),
        },
    )
    context = ActorContext(actor_ref="SYSTEM", portal="WORKER", trace_id=trace_id)
    _event(
        context,
        event_type="agent.source_asset.scan.completed",
        aggregate_type="object_asset",
        aggregate_ref=changed.public_id,
        payload={"scan_status": changed.scan_status, "source_id": changed.owner_ref},
    )
    return changed  # type: ignore[return-value]

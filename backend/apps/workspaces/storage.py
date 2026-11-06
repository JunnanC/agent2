"""Workspace volume storage worker implementation.

The worker receives only a persisted storage-job id.  Runtime and object-store
handles are resolved from database facts, and all external I/O happens outside
the short database transactions that commit immutable facts.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import tarfile
import time
import zipfile
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.core.antivirus import AntivirusUnavailable, ClamAVScanner
from apps.core.assets import register_asset, set_scan_result
from apps.core.audit import append_failure
from apps.core.concurrency import compare_and_swap
from apps.core.models import ObjectAsset
from apps.core.object_storage import iter_chunks, object_storage
from apps.core.project_archive import MANIFEST, ProjectArchiveError, bundle, unpack
from apps.courses.services import ActorContext
from apps.labtemplates.toolchains import TOOLCHAINS_BY_LANGUAGE
from apps.provisioning.adapters import RuntimeAdapterFailure, runtime_for_driver
from apps.provisioning.models import ProvisioningInstance

from . import services
from .models import WorkspaceAutosaveLog, WorkspaceSession, WorkspaceSnapshot, WorkspaceStorageJob

WORKSPACE_PATH = "main.py"
PROJECT_PATH = "."
PROJECT_MANIFEST = MANIFEST
_HEX_DIGEST_LENGTH = 64


class WorkspaceStorageFailure(RuntimeError):
    """A stable, non-sensitive storage-worker failure."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code[:64]
        self.retryable = retryable
        super().__init__(self.code)


@dataclass(frozen=True)
class _Content:
    value: bytes
    digest: str
    media_type: str = "text/plain"

    @property
    def size(self) -> int:
        return len(self.value)


def _context(job: WorkspaceStorageJob) -> ActorContext:
    return ActorContext(
        actor_ref="workspace-storage-worker", portal="WORKER", trace_id=job.trace_id
    )


def _max_bytes() -> int:
    return max(1, int(getattr(settings, "WORKSPACE_SNAPSHOT_MAX_BYTES", 20 * 1024 * 1024)))


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_content(value: bytes, *, expected_digest: str = "") -> _Content:
    if len(value) > _max_bytes():
        raise WorkspaceStorageFailure("WORKSPACE_FILE_TOO_LARGE")
    try:
        value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceStorageFailure("WORKSPACE_FILE_INVALID") from exc
    digest = _digest(value)
    if expected_digest and not hmac.compare_digest(digest, expected_digest):
        raise WorkspaceStorageFailure("WORKSPACE_DIGEST_MISMATCH")
    return _Content(value=value, digest=digest)


def _scan(value: bytes) -> None:
    try:
        result = ClamAVScanner().scan(iter_chunks(io.BytesIO(value)))
    except AntivirusUnavailable as exc:
        raise WorkspaceStorageFailure("WORKSPACE_SCAN_UNAVAILABLE", retryable=True) from exc
    if not result.clean:
        raise WorkspaceStorageFailure("WORKSPACE_FILE_INFECTED")


def _safe_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/") or normalized.startswith("\\"):
        return False
    parts = normalized.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _project_archive(files: dict[str, bytes], *, include_manifest: bool = True) -> bytes:
    try:
        return bundle(files, max_bytes=_max_bytes(), manifest=include_manifest)
    except ProjectArchiveError as exc:
        raise WorkspaceStorageFailure(str(exc)) from exc


def _project_files(value: bytes, media_type: str = "application/x-tar") -> dict[str, bytes]:
    if media_type.startswith("text/"):
        return {WORKSPACE_PATH: _validate_content(value).value}
    try:
        return unpack(value, max_bytes=_max_bytes())
    except ProjectArchiveError as exc:
        raise WorkspaceStorageFailure(str(exc)) from exc


def _starter_main(value: bytes, media_type: str) -> bytes:
    """Extract only main.py from a starter archive with traversal checks."""

    if media_type.startswith("text/"):
        return value
    if media_type == "application/zip" or value.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(value)) as archive:
                zip_candidates: list[zipfile.ZipInfo] = []
                for info in archive.infolist():
                    name = info.filename.replace("\\", "/")
                    safe_name = name.rstrip("/") if info.is_dir() else name
                    if not _safe_member(safe_name):
                        raise WorkspaceStorageFailure("WORKSPACE_FILE_INVALID")
                    # Unix mode bits identify symlinks and special files.
                    mode = (info.external_attr >> 16) & 0o170000
                    if info.is_dir():
                        continue
                    if mode and mode != 0o100000:
                        raise WorkspaceStorageFailure("WORKSPACE_FILE_INVALID")
                    if name == WORKSPACE_PATH:
                        zip_candidates.append(info)
                if len(zip_candidates) != 1:
                    raise WorkspaceStorageFailure("WORKSPACE_FILE_MISSING")
                info = zip_candidates[0]
                if info.file_size > _max_bytes():
                    raise WorkspaceStorageFailure("WORKSPACE_FILE_TOO_LARGE")
                return archive.read(info)
        except WorkspaceStorageFailure:
            raise
        except (OSError, zipfile.BadZipFile) as exc:
            raise WorkspaceStorageFailure("WORKSPACE_FILE_INVALID") from exc
    try:
        with tarfile.open(fileobj=io.BytesIO(value), mode="r:*") as archive:
            tar_candidates: list[tarfile.TarInfo] = []
            for tar_info in archive.getmembers():
                name = tar_info.name.replace("\\", "/")
                safe_name = name.rstrip("/") if tar_info.isdir() else name
                if not _safe_member(safe_name):
                    raise WorkspaceStorageFailure("WORKSPACE_FILE_INVALID")
                if tar_info.isdir():
                    continue
                if not tar_info.isreg() or tar_info.issym() or tar_info.islnk():
                    raise WorkspaceStorageFailure("WORKSPACE_FILE_INVALID")
                if name == WORKSPACE_PATH:
                    tar_candidates.append(tar_info)
            if len(tar_candidates) != 1:
                raise WorkspaceStorageFailure("WORKSPACE_FILE_MISSING")
            tar_info = tar_candidates[0]
            if tar_info.size > _max_bytes():
                raise WorkspaceStorageFailure("WORKSPACE_FILE_TOO_LARGE")
            handle = archive.extractfile(tar_info)
            if handle is None:
                raise WorkspaceStorageFailure("WORKSPACE_FILE_MISSING")
            return handle.read(_max_bytes() + 1)
    except WorkspaceStorageFailure:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise WorkspaceStorageFailure("WORKSPACE_FILE_INVALID") from exc


def _read_object(asset: ObjectAsset) -> bytes:
    try:
        stored = object_storage().open_object(
            bucket=asset.bucket, object_key=asset.object_key, version_id=asset.object_version
        )
        chunks: list[bytes] = []
        total = 0
        with closing(stored.body) as body:
            while chunk := body.read(64 * 1024):
                total += len(chunk)
                if total > _max_bytes():
                    raise WorkspaceStorageFailure("WORKSPACE_FILE_TOO_LARGE")
                chunks.append(bytes(chunk))
        value = b"".join(chunks)
    except WorkspaceStorageFailure:
        raise
    except Exception as exc:  # noqa: BLE001 - storage backend details stay private
        raise WorkspaceStorageFailure("WORKSPACE_OBJECT_UNAVAILABLE", retryable=True) from exc
    if len(value) != asset.size_bytes or not hmac.compare_digest(
        _digest(value), asset.digest_sha256
    ):
        raise WorkspaceStorageFailure("WORKSPACE_OBJECT_INVALID")
    return value


def _runtime(
    job: WorkspaceStorageJob, *, allow_destroying: bool = False
) -> tuple[Any, str]:
    instance = (
        ProvisioningInstance.objects.select_related("runtime_adapter")
        .filter(pk=job.instance_id, task_id=job.task_id)
        .first()
    )
    allowed_statuses = {ProvisioningInstance.Status.READY}
    if allow_destroying:
        allowed_statuses.add(ProvisioningInstance.Status.DESTROYING)
    if instance is None or not instance.external_id or instance.status not in allowed_statuses:
        raise WorkspaceStorageFailure("WORKSPACE_VOLUME_UNAVAILABLE", retryable=True)
    adapter = runtime_for_driver(
        instance.runtime_adapter.driver, config_ref=instance.runtime_adapter.config_ref
    )
    return adapter, instance.external_id


def _capture(adapter: Any, external_id: str, *, project: bool = False) -> _Content:
    relative_path = PROJECT_PATH if project else WORKSPACE_PATH
    try:
        artifact = adapter.capture_workspace(
            external_id=external_id, relative_path=relative_path, max_bytes=_max_bytes()
        )
    except RuntimeAdapterFailure as exc:
        raise WorkspaceStorageFailure(exc.code, retryable=exc.retryable) from exc
    except Exception as exc:  # noqa: BLE001 - adapters normalize expected failures
        raise WorkspaceStorageFailure("WORKSPACE_CAPTURE_FAILED", retryable=True) from exc
    if artifact.relative_path != relative_path or artifact.size != len(artifact.content):
        raise WorkspaceStorageFailure("WORKSPACE_FILE_INVALID")
    if project:
        files = _project_files(bytes(artifact.content), "application/x-tar")
        value = _project_archive(files)
        content = _Content(value, _digest(value), "application/gzip")
    else:
        content = _validate_content(bytes(artifact.content), expected_digest=artifact.digest)
    _scan(content.value)
    return _Content(
        content.value, content.digest, content.media_type or artifact.media_type or "text/plain"
    )


def _put_asset(*, job: WorkspaceStorageJob, content: _Content) -> ObjectAsset:
    filename = "project.tar.gz" if content.media_type == "application/gzip" else WORKSPACE_PATH
    key = (
        f"workspaces/{job.task.public_id}/{job.session.public_id}/storage/"
        f"{job.public_id}/{content.digest}/{filename}"
    )
    stream = io.BytesIO(content.value)
    try:
        stored = object_storage().put_stream(
            bucket=settings.MINIO_BUCKET,
            object_key=key,
            stream=stream,
            media_type=content.media_type,
        )
        asset = register_asset(
            bucket=settings.MINIO_BUCKET,
            object_key=key,
            object_version=stored.version_id,
            digest_sha256=content.digest,
            size_bytes=content.size,
            owner_type="WORKSPACE_TASK",
            owner_ref=job.task.public_id,
            purpose="WORKSPACE_SNAPSHOT",
            media_type=content.media_type,
            original_name=filename,
        )
        asset = set_scan_result(
            asset_id=asset.pk,
            expected_version=asset.row_version,
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )
        return asset
    except Exception:
        # The object is immutable and may already have been uploaded.  The
        # orphan sweep removes it if registration did not commit.
        with suppress(Exception):
            object_storage().delete_object(
                bucket=settings.MINIO_BUCKET,
                object_key=key,
                version_id=getattr(locals().get("stored"), "version_id", ""),
            )
        raise


def _next_client_seq(task_id: int) -> int:
    return (
        int(
            WorkspaceAutosaveLog.objects.filter(task_id=task_id).aggregate(value=Max("client_seq"))[
                "value"
            ]
            or 0
        )
        + 1
    )


def _commit_snapshot(
    *,
    job_id: str,
    claim_version: int,
    asset: ObjectAsset,
    content: _Content,
    client_seq: int,
    base_version: int,
    language: str | None = None,
    finish: bool = True,
) -> WorkspaceSnapshot:
    """Commit one immutable snapshot and advance the owning Session."""

    with transaction.atomic():
        job = (
            WorkspaceStorageJob.objects.select_for_update()
            .select_related("task__course", "session")
            .get(public_id=job_id)
        )
        if job.status in WorkspaceStorageJob.TERMINAL_STATUSES:
            if job.result_snapshot_id:
                return WorkspaceSnapshot.objects.get(pk=job.result_snapshot_id)
            raise WorkspaceStorageFailure("WORKSPACE_STORAGE_JOB_TERMINAL")
        if job.status != WorkspaceStorageJob.Status.RUNNING or job.row_version != claim_version:
            raise WorkspaceStorageFailure("WORKSPACE_STORAGE_CLAIM_LOST", retryable=True)
        session = (
            WorkspaceSession.objects.select_for_update(of=("self",))
            .select_related("latest_snapshot")
            .get(pk=job.session_id)
        )
        if session.current_version != base_version:
            raise WorkspaceStorageFailure("WORKSPACE_CAPTURE_CONFLICT")
        selected = language or session.language
        snapshot = session.latest_snapshot
        project = (job.task.execution_spec or {}).get("schema_version") == 2
        unchanged = (
            (job.kind == WorkspaceStorageJob.Kind.CAPTURE or project)
            and snapshot is not None
            and snapshot.language == selected
            and (snapshot.asset_id == asset.pk or project)
            and snapshot.digest_sha256 == content.digest
            and snapshot.size_bytes == content.size
            and snapshot.media_type == content.media_type
            and snapshot.asset.status == ObjectAsset.Status.ACTIVE
            and snapshot.asset.scan_status == ObjectAsset.ScanStatus.CLEAN
            and snapshot.asset.digest_sha256 == content.digest
            and asset.status == ObjectAsset.Status.ACTIVE
            and asset.scan_status == ObjectAsset.ScanStatus.CLEAN
            and asset.digest_sha256 == content.digest
        )
        if not unchanged:
            snapshot = WorkspaceSnapshot.objects.create(
                task=job.task,
                session=session,
                asset=asset,
                version_no=session.current_version + 1,
                client_seq=client_seq,
                base_version=base_version,
                digest_sha256=content.digest,
                size_bytes=content.size,
                media_type=content.media_type,
                saved_at=timezone.now(),
                trace_id=job.trace_id,
                language=selected,
                initial=not WorkspaceSnapshot.objects.filter(
                    task=job.task, language=selected
                ).exists(),
            )
        WorkspaceAutosaveLog.objects.create(
            task=job.task,
            session=session,
            client_seq=client_seq,
            request_digest=content.digest,
            snapshot=snapshot,
            result=WorkspaceAutosaveLog.Result.CONFIRMED,
            trace_id=job.trace_id,
        )
        changed_session = compare_and_swap(
            WorkspaceSession,
            pk=session.pk,
            expected_version=session.row_version,
            changes={
                "current_version": snapshot.version_no,
                "latest_snapshot": snapshot,
                "last_seen_at": timezone.now(),
                "language": selected,
            },
        )
        if finish:
            current_job = WorkspaceStorageJob.objects.get(pk=job.pk)
            services.transition_storage_job(
                job_id=job.public_id,
                expected_version=current_job.row_version,
                to_status=WorkspaceStorageJob.Status.PASSED,
                context=_context(job),
                result_snapshot=snapshot,
            )
        del changed_session
        return snapshot


def _claim(job_id: str, trace_id: str = "") -> tuple[WorkspaceStorageJob | None, bool]:
    with transaction.atomic():
        try:
            job = WorkspaceStorageJob.objects.select_for_update().get(public_id=job_id)
        except WorkspaceStorageJob.DoesNotExist:
            return None, False
        if job.status in WorkspaceStorageJob.TERMINAL_STATUSES:
            return job, False
        if job.status == WorkspaceStorageJob.Status.RUNNING:
            stale_after = max(
                60,
                int(getattr(settings, "WORKSPACE_STORAGE_STALE_AFTER_SECONDS", 900)),
            )
            if job.started_at and job.started_at > timezone.now() - timedelta(seconds=stale_after):
                return job, False
        claimed = services.transition_storage_job(
            job_id=job.public_id,
            expected_version=job.row_version,
            to_status=WorkspaceStorageJob.Status.RUNNING,
            context=ActorContext(
                actor_ref="workspace-storage-worker",
                portal="WORKER",
                trace_id=trace_id or job.trace_id,
            ),
        )
        return claimed, True


@transaction.atomic
def _record_failure(
    job_id: str, exc: Exception, trace_id: str, claim_version: int
) -> WorkspaceStorageJob | None:
    job = WorkspaceStorageJob.objects.select_for_update().filter(public_id=job_id).first()
    if (
        job is None
        or job.status != WorkspaceStorageJob.Status.RUNNING
        or job.row_version != claim_version
    ):
        return job
    code = str(getattr(exc, "code", "WORKSPACE_STORAGE_FAILED"))[:64]
    retryable = bool(getattr(exc, "retryable", True))
    failure = append_failure(
        failure_type="WORKSPACE_STORAGE",
        subject_type="WORKSPACE_STORAGE_JOB",
        subject_ref=job_id,
        error_code=code,
        message=code,
        detail={"retryable": retryable},
        retryable=retryable,
        trace_id=trace_id,
    )
    return services.transition_storage_job(
        job_id=job.public_id,
        expected_version=job.row_version,
        to_status=WorkspaceStorageJob.Status.FAILED,
        context=ActorContext(
            actor_ref="workspace-storage-worker", portal="WORKER", trace_id=trace_id
        ),
        failure_record=failure,
    )


def _execute_initialize(job: WorkspaceStorageJob, *, claim_version: int) -> WorkspaceSnapshot:
    if (job.task.execution_spec or {}).get("schema_version") == 2:
        return _execute_project_change(job, claim_version=claim_version)
    asset = job.task.template_version.starter_asset
    if asset is not None and (
        asset.owner_type != "TEMPLATE_VERSION"
        or asset.owner_ref != job.task.template_version.public_id
        or asset.purpose != "STARTER"
        or asset.status != ObjectAsset.Status.ACTIVE
        or asset.scan_status != ObjectAsset.ScanStatus.CLEAN
    ):
        raise WorkspaceStorageFailure("WORKSPACE_STARTER_NOT_READY")
    session = WorkspaceSession.objects.select_related("latest_snapshot__asset").get(
        pk=job.session_id
    )
    previous = session.latest_snapshot
    if previous is not None:
        if (
            previous.asset.status != ObjectAsset.Status.ACTIVE
            or previous.asset.scan_status != ObjectAsset.ScanStatus.CLEAN
        ):
            raise WorkspaceStorageFailure("WORKSPACE_SNAPSHOT_NOT_READY")
        value = _read_object(previous.asset)
    else:
        value = (
            b"# Write your solution here.\n"
            if asset is None
            else _starter_main(_read_object(asset), asset.media_type)
        )
    content = _validate_content(value)
    _scan(content.value)
    adapter, external_id = _runtime(job)
    try:
        adapter.restore_workspace(
            external_id=external_id,
            relative_path=WORKSPACE_PATH,
            content=content.value,
            expected_digest=content.digest,
        )
    except RuntimeAdapterFailure as exc:
        raise WorkspaceStorageFailure(exc.code, retryable=exc.retryable) from exc
    captured = _capture(adapter, external_id)
    if not hmac.compare_digest(captured.digest, content.digest):
        raise WorkspaceStorageFailure("WORKSPACE_RESTORE_FAILED")
    # Sequence zero is reserved for the first initialization of this task.
    snapshot_asset = _put_asset(job=job, content=captured)
    return _commit_snapshot(
        job_id=job.public_id,
        claim_version=claim_version,
        asset=snapshot_asset,
        content=captured,
        client_seq=_next_client_seq(job.task_id) if previous else 0,
        base_version=session.current_version,
    )


def _initial_project(job: WorkspaceStorageJob, language: str) -> _Content:
    spec = job.task.execution_spec or {}
    frozen = spec.get("_runtime", {}).get("material_assets", [])
    visible = [item for item in frozen if item["role"] in {"STUDENT_FILES", "PUBLIC_DATA"}]
    if not frozen:
        # Published v2 rows created before material freezing still validate role and ownership.
        visible = [item for item in spec.get("materials", []) if item["role"] != "HIDDEN_SOURCE"]
    files: dict[str, bytes] = {}
    for item in visible:
        asset = ObjectAsset.objects.filter(
            public_id=item["asset_id"],
            owner_type="TEMPLATE_VERSION",
            owner_ref=job.task.template_version.public_id,
            status=ObjectAsset.Status.ACTIVE,
            scan_status=ObjectAsset.ScanStatus.CLEAN,
            purpose="STARTER" if item["role"] == "STUDENT_FILES" else "PUBLIC_DATA",
        ).first()
        if asset is None or any(
            item.get(key, getattr(asset, field)) != getattr(asset, field)
            for key, field in {
                "digest": "digest_sha256", "object_version": "object_version",
                "bucket": "bucket", "object_key": "object_key",
            }.items()
        ):
            raise WorkspaceStorageFailure("WORKSPACE_STARTER_NOT_READY")
        raw = _read_object(asset)
        if asset.media_type.startswith("text/") or asset.media_type == "application/json":
            name = asset.original_name or TOOLCHAINS_BY_LANGUAGE[language]["entrypoint"]
            material_files: dict[str, bytes] = {name: raw}
        else:
            material_files = _project_files(raw, asset.media_type)
        if set(files) & set(material_files):
            raise WorkspaceStorageFailure("WORKSPACE_FILE_INVALID")
        files.update(material_files)
    has_student_files = any(item["role"] == "STUDENT_FILES" for item in visible)
    if not frozen and not spec.get("materials") and job.task.template_version.starter_asset_id:
        asset = job.task.template_version.starter_asset
        if (
            asset.scan_status != ObjectAsset.ScanStatus.CLEAN
            or asset.status != ObjectAsset.Status.ACTIVE
            or asset.owner_type != "TEMPLATE_VERSION"
            or asset.owner_ref != job.task.template_version.public_id
            or asset.purpose != "STARTER"
        ):
            raise WorkspaceStorageFailure("WORKSPACE_STARTER_NOT_READY")
        files = _project_files(_read_object(asset), asset.media_type)
        has_student_files = True
    if not has_student_files:
        entrypoint = str(spec.get("entrypoint") or TOOLCHAINS_BY_LANGUAGE[language]["entrypoint"])
        starters = {
            "c": b"#include <stdio.h>\nint main(void) {\n    return 0;\n}\n",
            "cpp": b"#include <iostream>\nint main() {\n    return 0;\n}\n",
            "java": b"public class Main {\n"
            b"    public static void main(String[] args) {\n    }\n}\n",
            "python": b"# Write your solution here.\n",
            "go": b"package main\n\nfunc main() {\n}\n",
        }
        files[entrypoint] = starters[language]
    value = _project_archive(files)
    return _Content(value, _digest(value), "application/gzip")


def _execute_project_change(job: WorkspaceStorageJob, *, claim_version: int) -> WorkspaceSnapshot:
    session = WorkspaceSession.objects.get(pk=job.session_id)
    language = job.target_language or session.language
    adapter, external_id = _runtime(job)
    previous: _Content | None = None
    if job.kind != WorkspaceStorageJob.Kind.INITIALIZE:
        previous = _capture(adapter, external_id, project=True)
        asset = _put_asset(job=job, content=previous)
        _commit_snapshot(
            job_id=job.public_id,
            claim_version=claim_version,
            asset=asset,
            content=previous,
            client_seq=_next_client_seq(job.task_id),
            base_version=session.current_version,
            finish=False,
        )
        session.refresh_from_db()
    sources = WorkspaceSnapshot.objects.select_related("asset").filter(
        task=job.task, language=language
    )
    source = (
        sources.filter(initial=True).order_by("version_no").first()
        if job.kind == WorkspaceStorageJob.Kind.RESET
        else sources.order_by("-version_no").first()
    )
    if source is not None:
        if (
            source.asset.scan_status != ObjectAsset.ScanStatus.CLEAN
            or source.asset.status != ObjectAsset.Status.ACTIVE
        ):
            raise WorkspaceStorageFailure("WORKSPACE_SNAPSHOT_NOT_READY")
        value = _read_object(source.asset)
        _project_files(value)
        content = _Content(value, _digest(value), "application/gzip")
        if content.digest != source.digest_sha256:
            raise WorkspaceStorageFailure("WORKSPACE_DIGEST_MISMATCH")
    else:
        content = _initial_project(job, language)
    _scan(content.value)
    try:
        adapter.restore_workspace(
            external_id=external_id,
            relative_path=PROJECT_PATH,
            content=content.value,
            expected_digest=content.digest,
        )
        captured = _capture(adapter, external_id, project=True)
        if captured.digest != content.digest:
            raise WorkspaceStorageFailure("WORKSPACE_RESTORE_FAILED")
    except Exception:
        if previous is not None:
            adapter.restore_workspace(
                external_id=external_id,
                relative_path=PROJECT_PATH,
                content=previous.value,
                expected_digest=previous.digest,
            )
        raise
    asset = source.asset if source is not None else _put_asset(job=job, content=content)
    first = not WorkspaceSnapshot.objects.filter(task=job.task).exists()
    return _commit_snapshot(
        job_id=job.public_id,
        claim_version=claim_version,
        asset=asset,
        content=content,
        client_seq=0 if first else _next_client_seq(job.task_id),
        base_version=session.current_version,
        language=language,
    )


def _execute_capture(job: WorkspaceStorageJob, *, claim_version: int) -> WorkspaceSnapshot:
    adapter, external_id = _runtime(job)
    project = int((job.task.execution_spec or {}).get("schema_version", 1)) >= 2
    content = _capture(adapter, external_id, project=project)
    previous = WorkspaceSnapshot.objects.select_related("asset").filter(
        pk=WorkspaceSession.objects.get(pk=job.session_id).latest_snapshot_id,
        language=job.session.language,
        digest_sha256=content.digest,
        size_bytes=content.size,
        media_type=content.media_type,
        asset__digest_sha256=content.digest,
        asset__status=ObjectAsset.Status.ACTIVE,
        asset__scan_status=ObjectAsset.ScanStatus.CLEAN,
    ).first()
    asset = previous.asset if previous is not None else _put_asset(job=job, content=content)
    return _commit_snapshot(
        job_id=job.public_id,
        claim_version=claim_version,
        asset=asset,
        content=content,
        client_seq=int(job.client_seq or 0),
        base_version=int(job.base_version or 0),
    )


def _execute_restore(job: WorkspaceStorageJob, *, claim_version: int) -> WorkspaceSnapshot:
    source = (
        WorkspaceSnapshot.objects.select_related("asset")
        .filter(pk=job.source_snapshot_id, task_id=job.task_id)
        .first()
    )
    if (
        source is None
        or source.asset.status != ObjectAsset.Status.ACTIVE
        or source.asset.scan_status != ObjectAsset.ScanStatus.CLEAN
        or source.language != WorkspaceSession.objects.get(pk=job.session_id).language
    ):
        raise WorkspaceStorageFailure("WORKSPACE_SNAPSHOT_NOT_READY")
    if not hmac.compare_digest(source.digest_sha256, source.asset.digest_sha256):
        raise WorkspaceStorageFailure("WORKSPACE_SNAPSHOT_NOT_READY")
    project = source.asset.media_type == "application/gzip"
    value = _read_object(source.asset)
    if project:
        _project_files(value, "application/x-tar")
        if not hmac.compare_digest(_digest(value), source.digest_sha256):
            raise WorkspaceStorageFailure("WORKSPACE_DIGEST_MISMATCH")
        content = _Content(value, source.digest_sha256, "application/gzip")
    else:
        content = _validate_content(value, expected_digest=source.digest_sha256)
    adapter, external_id = _runtime(job)
    try:
        adapter.restore_workspace(
            external_id=external_id,
            relative_path=PROJECT_PATH if project else WORKSPACE_PATH,
            content=content.value,
            expected_digest=content.digest,
        )
    except RuntimeAdapterFailure as exc:
        raise WorkspaceStorageFailure(exc.code, retryable=exc.retryable) from exc
    captured = _capture(adapter, external_id, project=project)
    if not hmac.compare_digest(captured.digest, content.digest):
        raise WorkspaceStorageFailure("WORKSPACE_RESTORE_FAILED")
    return _commit_snapshot(
        job_id=job.public_id,
        claim_version=claim_version,
        asset=source.asset,
        content=content,
        client_seq=_next_client_seq(job.task_id),
        base_version=WorkspaceSession.objects.get(pk=job.session_id).current_version,
    )


def _execute_finalize(job: WorkspaceStorageJob, *, claim_version: int) -> WorkspaceSnapshot:
    # FINALIZE deliberately follows the same capture path, but does not require
    # an ACTIVE Session.  It is only scheduled by lifecycle cleanup.
    adapter, external_id = _runtime(job, allow_destroying=True)
    project = int((job.task.execution_spec or {}).get("schema_version", 1)) >= 2
    content = _capture(adapter, external_id, project=project)
    asset = _put_asset(job=job, content=content)
    session = WorkspaceSession.objects.get(pk=job.session_id)
    return _commit_snapshot(
        job_id=job.public_id,
        claim_version=claim_version,
        asset=asset,
        content=content,
        client_seq=_next_client_seq(job.task_id),
        base_version=session.current_version,
    )


def execute_storage_job(*, storage_job_id: str, trace_id: str = "") -> str:
    job, acquired = _claim(storage_job_id, trace_id)
    if job is None:
        return storage_job_id
    if not acquired:
        return job.public_id
    claim_version = job.row_version
    try:
        job = WorkspaceStorageJob.objects.select_related(
            "task__template_version", "instance__runtime_adapter"
        ).get(pk=job.pk)
        if job.kind == WorkspaceStorageJob.Kind.INITIALIZE:
            _execute_initialize(job, claim_version=claim_version)
        elif job.kind == WorkspaceStorageJob.Kind.CAPTURE:
            _execute_capture(job, claim_version=claim_version)
        elif job.kind == WorkspaceStorageJob.Kind.RESTORE:
            _execute_restore(job, claim_version=claim_version)
        elif job.kind == WorkspaceStorageJob.Kind.FINALIZE:
            _execute_finalize(job, claim_version=claim_version)
        elif job.kind in {WorkspaceStorageJob.Kind.SWITCH, WorkspaceStorageJob.Kind.RESET}:
            _execute_project_change(job, claim_version=claim_version)
        else:
            raise WorkspaceStorageFailure("WORKSPACE_STORAGE_KIND_INVALID")
    except Exception as exc:  # noqa: BLE001 - convert every worker error to a stable fact
        _record_failure(storage_job_id, exc, trace_id or job.trace_id, claim_version)
    return storage_job_id


def reconcile_storage_jobs(*, limit: int = 200) -> int:
    """Redispatch queued or abandoned jobs; row locking makes duplicate delivery safe."""

    now = timezone.now()
    dispatch_after = now - timedelta(seconds=30)
    stale_after = max(
        60,
        int(getattr(settings, "WORKSPACE_STORAGE_STALE_AFTER_SECONDS", 900)),
    )
    redispatch_after = max(
        30,
        int(getattr(settings, "WORKSPACE_STORAGE_REDISPATCH_SECONDS", 300)),
    )
    stale_before = now - timedelta(seconds=stale_after)
    dispatch_before = now - timedelta(seconds=redispatch_after)
    job_ids = list(
        WorkspaceStorageJob.objects.filter(
            (
                Q(status=WorkspaceStorageJob.Status.QUEUED, queued_at__lte=dispatch_after)
                | Q(status=WorkspaceStorageJob.Status.RUNNING, started_at__lte=stale_before)
            )
            & (Q(last_dispatched_at__isnull=True) | Q(last_dispatched_at__lte=dispatch_before))
        )
        .order_by("queued_at")
        .values_list("public_id", flat=True)[: max(1, limit)]
    )
    for job in WorkspaceStorageJob.objects.filter(public_id__in=job_ids):
        enqueue_storage_job(job)
    return len(job_ids)


def enqueue_storage_job(job: WorkspaceStorageJob) -> None:
    from .tasks import execute_workspace_storage_job

    def dispatch() -> None:
        with transaction.atomic():
            current = WorkspaceStorageJob.objects.select_for_update().filter(pk=job.pk).first()
            if current is None or current.status in WorkspaceStorageJob.TERMINAL_STATUSES:
                return
            compare_and_swap(
                WorkspaceStorageJob,
                pk=current.pk,
                expected_version=current.row_version,
                changes={"last_dispatched_at": timezone.now()},
            )
        execute_workspace_storage_job.apply_async(
            kwargs={"storage_job_id": job.public_id, "trace_id": job.trace_id},
            queue="q_workspace_storage",
            task_id=f"workspace-storage:{job.public_id}",
        )

    transaction.on_commit(dispatch)


def create_initialization_job(
    *, session: WorkspaceSession, context: Any
) -> WorkspaceStorageJob | None:
    """Create the one initialization job for a real runtime session."""

    driver = str(
        session.task.runtime_adapter_driver
        or getattr(getattr(session.task, "runtime_adapter", None), "driver", "")
    )
    if not driver or driver == "FAKE":
        return None
    existing = (
        WorkspaceStorageJob.objects.filter(
            session=session,
            kind=WorkspaceStorageJob.Kind.INITIALIZE,
            status__in=(
                WorkspaceStorageJob.Status.QUEUED,
                WorkspaceStorageJob.Status.RUNNING,
                WorkspaceStorageJob.Status.PASSED,
            ),
        )
        .order_by("-created_at")
        .first()
    )
    if existing is not None:
        return existing
    retry_no = (
        WorkspaceStorageJob.objects.filter(
            session=session, kind=WorkspaceStorageJob.Kind.INITIALIZE
        ).count()
        + 1
    )
    job = WorkspaceStorageJob.objects.create(
        kind=WorkspaceStorageJob.Kind.INITIALIZE,
        task=session.task,
        session=session,
        instance=session.instance,
        status=WorkspaceStorageJob.Status.QUEUED,
        idempotency_key=f"workspace-initialize:{session.public_id}:{retry_no}",
        request_digest=_digest(session.public_id.encode()),
        trace_id=str(getattr(context, "trace_id", "")),
    )
    enqueue_storage_job(job)
    return job


def create_finalize_job(*, session: WorkspaceSession, context: Any) -> WorkspaceStorageJob | None:
    driver = str(
        session.task.runtime_adapter_driver
        or getattr(getattr(session.task, "runtime_adapter", None), "driver", "")
    )
    if not driver or driver == "FAKE":
        return None
    if not WorkspaceStorageJob.objects.filter(
        session=session,
        kind=WorkspaceStorageJob.Kind.INITIALIZE,
        status=WorkspaceStorageJob.Status.PASSED,
    ).exists():
        return None
    job = (
        WorkspaceStorageJob.objects.filter(
            session=session,
            kind=WorkspaceStorageJob.Kind.FINALIZE,
            status__in=(
                WorkspaceStorageJob.Status.QUEUED,
                WorkspaceStorageJob.Status.RUNNING,
                WorkspaceStorageJob.Status.PASSED,
            ),
        )
        .order_by("-created_at")
        .first()
    )
    if job is not None:
        return job
    retry_no = (
        WorkspaceStorageJob.objects.filter(
            session=session, kind=WorkspaceStorageJob.Kind.FINALIZE
        ).count()
        + 1
    )
    job = WorkspaceStorageJob.objects.create(
        kind=WorkspaceStorageJob.Kind.FINALIZE,
        task=session.task,
        session=session,
        instance=session.instance,
        status=WorkspaceStorageJob.Status.QUEUED,
        idempotency_key=f"workspace-finalize:{session.public_id}:{retry_no}",
        request_digest=_digest((session.public_id + ":finalize").encode()),
        trace_id=str(getattr(context, "trace_id", "")),
    )
    enqueue_storage_job(job)
    return job


def finalize_workspace_before_destroy(*, task_id: str, context: Any) -> WorkspaceStorageJob | None:
    """Capture the last online file before a runtime container is destroyed.

    Lifecycle cleanup waits for existing writes, then dispatches this persisted
    job to the isolated storage worker before revoking the session or destroying
    the runtime.
    """

    session = (
        WorkspaceSession.objects.select_related(
            "task__runtime_adapter", "task__template_version", "instance"
        )
        .filter(task__public_id=task_id)
        .order_by("-created_at")
        .first()
    )
    if session is None:
        return None
    timeout = max(1, int(getattr(settings, "WORKSPACE_FINALIZE_TIMEOUT_SECONDS", 1200)))
    deadline = time.monotonic() + timeout
    while WorkspaceStorageJob.objects.filter(
        session=session,
        status__in=(WorkspaceStorageJob.Status.QUEUED, WorkspaceStorageJob.Status.RUNNING),
    ).exists():
        if time.monotonic() >= deadline:
            raise WorkspaceStorageFailure("WORKSPACE_FINALIZE_TIMEOUT", retryable=True)
        time.sleep(0.25)
    job = create_finalize_job(session=session, context=context)
    if job is None:
        return None
    while True:
        current = WorkspaceStorageJob.objects.select_related("failure_record").get(pk=job.pk)
        if current.status == WorkspaceStorageJob.Status.PASSED:
            return current
        if current.status in WorkspaceStorageJob.TERMINAL_STATUSES:
            code = (
                current.failure_record.error_code
                if current.failure_record_id
                else "WORKSPACE_FINALIZE_FAILED"
            )
            raise WorkspaceStorageFailure(
                code,
                retryable=bool(current.failure_record and current.failure_record.retryable),
            )
        if time.monotonic() >= deadline:
            raise WorkspaceStorageFailure("WORKSPACE_FINALIZE_TIMEOUT", retryable=True)
        time.sleep(0.25)

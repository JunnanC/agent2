"""Immutable source archives for assessment runs and submissions, independent of IDE sessions."""

import hashlib
import io
from contextlib import suppress
from typing import Any

from django.conf import settings
from django.db.models import Max
from django.utils import timezone

from apps.core.antivirus import ClamAVScanner
from apps.core.assets import register_asset, set_scan_result
from apps.core.concurrency import compare_and_swap
from apps.core.errors import StateConflict
from apps.core.models import ObjectAsset
from apps.core.object_storage import object_storage
from apps.core.project_archive import bundle
from apps.labtemplates.questions import project_files

from .models import WorkspaceSnapshot


def create_code_snapshot(*, task: Any, question: Any, draft: Any) -> WorkspaceSnapshot:
    files = project_files(draft.files)
    content = bundle(
        {path: value.encode("utf-8") for path, value in files.items()},
        max_bytes=settings.WORKSPACE_SNAPSHOT_MAX_BYTES,
    )
    digest = hashlib.sha256(content).hexdigest()
    existing = WorkspaceSnapshot.objects.filter(
        task=task, question=question, language=draft.language, digest_sha256=digest,
        asset__status="ACTIVE", asset__scan_status="CLEAN",
    ).first()
    if existing:
        return existing
    if not ClamAVScanner().scan([content]).clean:
        raise StateConflict(detail={"files": "scan_rejected"})
    counters = WorkspaceSnapshot.objects.filter(task=task).aggregate(
        version=Max("version_no"), sequence=Max("client_seq"),
    )
    version = (counters["version"] or 0) + 1
    sequence = (counters["sequence"] or 0) + 1
    key = (
        f"assessment/{task.public_id}/{question.public_id}/"
        f"{draft.language}/{version}/{digest}.tgz"
    )
    storage = object_storage()
    stored = storage.put_stream(
        bucket=settings.MINIO_BUCKET, object_key=key,
        stream=io.BytesIO(content), media_type="application/gzip",
    )
    asset = None
    try:
        asset = register_asset(
            bucket=settings.MINIO_BUCKET, object_key=key, object_version=stored.version_id,
            digest_sha256=digest, size_bytes=len(content), media_type="application/gzip",
            owner_type="WORKSPACE_TASK", owner_ref=task.public_id, purpose="SOURCE_SNAPSHOT",
        )
        asset = set_scan_result(
            asset_id=asset.pk, expected_version=asset.row_version, scan_status="CLEAN",
        )
        return WorkspaceSnapshot.objects.create(
            task=task, question=question, session=None, asset=asset,
            version_no=version, client_seq=sequence, base_version=version - 1,
            digest_sha256=digest, size_bytes=len(content), media_type="application/gzip",
            language=draft.language, saved_at=timezone.now(), trace_id="assessment-snapshot",
        )
    except Exception:
        if asset is not None:
            compare_and_swap(
                ObjectAsset, pk=asset.pk, expected_version=asset.row_version,
                changes={"status": "PURGE_PENDING"},
            )
        with suppress(Exception):
            storage.delete_object(
                bucket=settings.MINIO_BUCKET, object_key=key, version_id=stored.version_id,
            )
        raise

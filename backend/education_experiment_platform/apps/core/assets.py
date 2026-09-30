from datetime import datetime

from django.db import transaction

from .concurrency import compare_and_swap
from .errors import RowVersionConflict, StateConflict
from .models import ObjectAsset, ObjectPurgeLog


def register_asset(
    *,
    bucket: str,
    object_key: str,
    object_version: str,
    digest_sha256: str,
    size_bytes: int,
    owner_type: str,
    owner_ref: str,
    purpose: str,
    media_type: str = "",
    original_name: str = "",
    retention_until: datetime | None = None,
) -> ObjectAsset:
    if len(digest_sha256) != 64 or any(char not in "0123456789abcdef" for char in digest_sha256):
        raise ValueError("digest_sha256 must be a lowercase SHA-256 hex digest")
    return ObjectAsset.objects.create(
        bucket=bucket,
        object_key=object_key,
        object_version=object_version,
        digest_sha256=digest_sha256,
        size_bytes=size_bytes,
        owner_type=owner_type,
        owner_ref=owner_ref,
        purpose=purpose,
        media_type=media_type,
        original_name=original_name[:255],
        retention_until=retention_until,
    )


def set_scan_result(
    *,
    asset_id: object,
    expected_version: int,
    scan_status: str,
) -> ObjectAsset:
    if scan_status not in {
        ObjectAsset.ScanStatus.CLEAN,
        ObjectAsset.ScanStatus.INFECTED,
        ObjectAsset.ScanStatus.FAILED,
    }:
        raise StateConflict(detail={"scan_status": scan_status})
    return compare_and_swap(
        ObjectAsset,
        pk=asset_id,
        expected_version=expected_version,
        changes={"scan_status": scan_status},
    )


@transaction.atomic
def record_purge_result(
    *,
    asset_id: object,
    expected_version: int,
    result: str,
    trace_id: str,
    reason: str = "",
    error_code: str = "",
) -> ObjectPurgeLog:
    asset = ObjectAsset.objects.select_for_update().get(pk=asset_id)
    if asset.row_version != expected_version:
        raise RowVersionConflict(detail={"expected_row_version": expected_version})
    log = ObjectPurgeLog.objects.create(
        asset=asset,
        object_key=asset.object_key,
        object_version=asset.object_version,
        digest_sha256=asset.digest_sha256,
        result=result,
        reason=reason,
        error_code=error_code,
        trace_id=trace_id,
    )
    target_status = (
        ObjectAsset.Status.PURGED
        if result == ObjectPurgeLog.Result.PURGED
        else ObjectAsset.Status.PURGE_PENDING
    )
    compare_and_swap(
        ObjectAsset,
        pk=asset.pk,
        expected_version=expected_version,
        changes={"status": target_status},
    )
    return log

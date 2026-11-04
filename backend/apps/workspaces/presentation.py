"""Bounded reads for student-facing text and public test examples."""

import hashlib
import json

from apps.core.models import ObjectAsset
from apps.core.object_storage import S3ObjectStorage


def asset_text(asset: ObjectAsset | None, *, limit: int = 256 * 1024) -> str | None:
    if (
        asset is None
        or asset.status != ObjectAsset.Status.ACTIVE
        or asset.scan_status != ObjectAsset.ScanStatus.CLEAN
        or asset.size_bytes > limit
    ):
        return None
    try:
        stored = S3ObjectStorage(timeout_seconds=3).open_object(
            bucket=asset.bucket, object_key=asset.object_key, version_id=asset.object_version
        )
        try:
            value = stored.body.read(limit + 1)
        finally:
            stored.body.close()
        if len(value) > limit or hashlib.sha256(value).hexdigest() != asset.digest_sha256:
            return None
        return value.decode("utf-8-sig")
    except Exception:  # noqa: BLE001 - unavailable assets must not leak storage details
        return None


def public_examples(value: str) -> tuple[int, list[dict[str, str]]]:
    try:
        payload = json.loads(value)
    except (ValueError, TypeError):
        return 0, []
    cases = payload.get("cases", []) if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        return 0, []
    examples = [
        {
            "name": f"用例 {index + 1}",
            "input": str(case.get("input", case.get("stdin", "")) or "")[:65536],
            "expected": str(case.get("expected", case.get("output", "")))[:65536],
        }
        for index, case in enumerate(cases[:3])
        if isinstance(case, dict)
    ]
    return len(cases), examples

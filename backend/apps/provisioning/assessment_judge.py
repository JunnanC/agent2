"""Private group evaluation; expected output remains outside every student container."""

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from django.conf import settings

from apps.core.models import ObjectAsset
from apps.core.object_storage import object_storage
from apps.labtemplates.questions import invalid, score_value

from .stdio import StdioExecutor, StdioResult, stdio_outputs_match


def read_private_tests(
    *, asset_id: str, template_version_id: str,
) -> tuple[ObjectAsset, dict[str, Any]]:
    try:
        asset = ObjectAsset.objects.get(
            public_id=asset_id, owner_type="TEMPLATE_VERSION", owner_ref=template_version_id,
            purpose="TESTS", status="ACTIVE", scan_status="CLEAN",
        )
    except ObjectAsset.DoesNotExist:
        invalid("tests_asset_id", "clean_owned_tests_required")
    if asset.size_bytes > settings.TEMPLATE_ASSET_MAX_BYTES:
        invalid("tests", "too_large")
    stored = object_storage().open_object(
        bucket=asset.bucket, object_key=asset.object_key, version_id=asset.object_version,
    )
    try:
        content = stored.body.read(settings.TEMPLATE_ASSET_MAX_BYTES + 1)
    finally:
        stored.body.close()
    if (
        len(content) != asset.size_bytes
        or hashlib.sha256(content).hexdigest() != asset.digest_sha256
    ):
        invalid("tests", "digest_mismatch")
    try:
        data = json.loads(content)
    except (UnicodeError, ValueError):
        invalid("tests", "invalid_json")
    return asset, data


def validated_groups(data: Any, scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or set(data) != {"groups"}:
        invalid("tests", "groups_required")
    groups = data["groups"]
    if not isinstance(groups, list) or len(groups) != len(scores):
        invalid("tests", "group_set_mismatch")
    score_map = {entry["id"]: score_value(entry["score"]) for entry in scores}
    seen: set[str] = set()
    total_cases = 0
    for group in groups:
        if (
            not isinstance(group, dict) or set(group) != {"id", "cases"}
            or not isinstance(group["id"], str) or group["id"] not in score_map
            or group["id"] in seen or not isinstance(group["cases"], list) or not group["cases"]
        ):
            invalid("tests", "invalid_group")
        seen.add(group["id"])
        for case in group["cases"]:
            if (
                not isinstance(case, dict) or set(case) != {"input", "output"}
                or any(not isinstance(v, str) or len(v.encode()) > 1048576 for v in case.values())
            ):
                invalid("tests", "invalid_case")
        total_cases += len(group["cases"])
    if total_cases > 1000:
        invalid("tests", "too_many_cases")
    return groups


def grade_groups(
    *, executor: StdioExecutor, language: str, files: dict[str, str],
    groups: list[dict[str, Any]], scores: list[dict[str, Any]], limits: Mapping[str, int],
) -> dict[str, Any]:
    cases = [case for group in groups for case in group["cases"]]
    compilation, results = executor.execute(
        language=language, files=files, inputs=[case["input"] for case in cases],
        timeout_seconds=limits["timeout_seconds"], memory_mb=limits["memory_mb"],
    )
    if compilation:
        return {"score": "0", "status": "COMPILE_ERROR", "groups": []}
    if len(results) != len(cases):
        raise RuntimeError("Assessment runner returned an incomplete result set")
    total = Decimal("0")
    summaries = []
    offset = 0
    score_map = {group["id"]: score_value(group["score"]) for group in scores}
    for group in groups:
        relevant: list[StdioResult] = results[offset:offset + len(group["cases"])]
        passed = all(
            result.status == "PASSED" and stdio_outputs_match(result.stdout, case["output"])
            for result, case in zip(relevant, group["cases"], strict=True)
        )
        value = score_map[group["id"]] if passed else Decimal("0")
        total += value
        summaries.append({"id": group["id"], "passed": passed, "score": str(value)})
        offset += len(group["cases"])
    return {"score": str(total), "status": "COMPLETED", "groups": summaries}

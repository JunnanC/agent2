"""Teacher-only storage of hidden test groups using existing scanned object assets."""

import hashlib
import io
import json
from typing import Any

from django.conf import settings
from django.db import transaction

from apps.core.antivirus import ClamAVScanner
from apps.core.assets import register_asset, set_scan_result
from apps.core.concurrency import compare_and_swap
from apps.core.identifiers import new_ulid
from apps.core.object_storage import object_storage
from apps.courses.models import CourseStaffGrant
from apps.provisioning.assessment_judge import validated_groups

from .questions import invalid
from .services import _content_guard, _content_version, _course


@transaction.atomic
def store_question_tests(
    *, actor: Any, course_id: str, version_id: str, expected_version: int,
    groups: list[dict[str, Any]], scores: list[dict[str, Any]], context: Any,
) -> dict[str, Any]:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    version = _content_guard(_content_version(course, version_id, actor), expected_version, context)
    validated_groups({"groups": groups}, scores)
    content = json.dumps({"groups": groups}, ensure_ascii=False).encode()
    if len(content) > settings.TEMPLATE_ASSET_MAX_BYTES:
        invalid("tests", "too_large")
    if not ClamAVScanner().scan([content]).clean:
        invalid("tests", "scan_rejected")
    key = f"assessment-tests/{version_id}/{new_ulid()}.json"
    storage = object_storage()
    stored = storage.put_stream(
        bucket=settings.MINIO_BUCKET, object_key=key, stream=io.BytesIO(content),
        media_type="application/json",
    )
    asset = register_asset(
        bucket=settings.MINIO_BUCKET, object_key=key, object_version=stored.version_id,
        digest_sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
        owner_type="TEMPLATE_VERSION", owner_ref=version_id, purpose="TESTS",
        media_type="application/json",
    )
    set_scan_result(asset_id=asset.pk, expected_version=asset.row_version, scan_status="CLEAN")
    changed = compare_and_swap(
        type(version), pk=version.pk, expected_version=version.row_version, changes={},
    )
    return {"asset_id": asset.public_id, "row_version": changed.row_version}


def clone_marking_spec(question: Any, target_version: Any) -> dict[str, Any]:
    from .questions import QUESTION_TYPES

    if question.task_type not in QUESTION_TYPES or question.task_type != "PROGRAMMING":
        return dict(question.marking_spec)
    from apps.provisioning.assessment_judge import read_private_tests

    _, tests = read_private_tests(
        asset_id=question.marking_spec["tests_asset_id"],
        template_version_id=question.chapter.template_version.public_id,
    )
    content = json.dumps(tests, ensure_ascii=False).encode()
    key = f"assessment-tests/{target_version.public_id}/{new_ulid()}.json"
    stored = object_storage().put_stream(
        bucket=settings.MINIO_BUCKET, object_key=key, stream=io.BytesIO(content),
        media_type="application/json",
    )
    asset = register_asset(
        bucket=settings.MINIO_BUCKET, object_key=key, object_version=stored.version_id,
        digest_sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
        owner_type="TEMPLATE_VERSION", owner_ref=target_version.public_id, purpose="TESTS",
        media_type="application/json",
    )
    set_scan_result(asset_id=asset.pk, expected_version=asset.row_version, scan_status="CLEAN")
    return {**question.marking_spec, "tests_asset_id": asset.public_id}

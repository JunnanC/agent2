import hashlib
import io
import json
import math
import re
from collections.abc import Callable, Mapping
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from jsonschema import Draft202012Validator, SchemaError

from apps.accounts.models import User
from apps.core.assets import register_asset, set_scan_result
from apps.core.audit import append_audit, append_failure, hash_client_ip
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.identifiers import new_ulid
from apps.core.models import ObjectAsset
from apps.core.object_storage import object_storage
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.courses.models import Course, CourseCopyItem, CourseCopyJob, CourseStaffGrant
from apps.courses.ports import published_material_versions
from apps.courses.selectors import require_course_capability, visible_course
from apps.courses.services import ActorContext
from apps.governance.models import ImageAsset, ResourceProfile, RuntimeAdapter
from apps.governance.ports import template_governance_snapshot

from . import events
from .errors import (
    TemplateAssetNotReady,
    TemplateDeleteForbidden,
    TemplateDigestMismatch,
    TemplateNameExists,
    TemplatePrecheckFailed,
    TemplateStateConflict,
    TemplateValidationError,
)
from .metrics import PRECHECK_ACTIVE, PRECHECK_DURATION, PRECHECK_RUNS
from .models import (
    AutoCheckRule,
    ExperimentImage,
    Template,
    TemplateChapter,
    TemplatePrecheckRun,
    TemplateTask,
    TemplateVersion,
)
from .toolchains import (
    TOOLCHAINS_BY_LANGUAGE,
    resolve_language_policy,
    validate_frozen_language_policy,
)

VERSION_FIELDS = {
    "runtime_type",
    "runtime_adapter_id",
    "image_id",
    "resource_profile_id",
    "dependencies",
    "execution_spec",
    "network_policy",
    "workspace_capabilities",
    "material_version_ids",
    "report_policy",
    "review_policy",
    "retention_days",
}
ASSET_FIELDS = ("manual_asset", "starter_asset", "report_template_asset")
LEGACY_EXECUTION_SPEC_KEYS = frozenset({
    "language",
    "entrypoint",
    "timeout_seconds",
    "memory_mb",
    "cpu_millicores",
    "comparator",
    "tests_asset",
    "network_mode",
})
_PYTHON_ENTRYPOINT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,126}\.py$")
_PROJECT_ENTRYPOINT = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")


def _normalize_execution_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TemplateValidationError(detail={"execution_spec": "object_required"})
    if value.get("schema_version") == 2:
        return _normalize_execution_spec_v2(value)
    unknown = sorted(set(value) - LEGACY_EXECUTION_SPEC_KEYS)
    missing = sorted(LEGACY_EXECUTION_SPEC_KEYS - set(value))
    if unknown:
        raise TemplateValidationError(detail={"execution_spec": {"unknown": unknown}})
    if missing:
        raise TemplateValidationError(detail={"execution_spec": {"required": missing}})
    language = value.get("language")
    entrypoint = value.get("entrypoint")
    comparator = value.get("comparator")
    network_mode = value.get("network_mode")
    tests_asset = value.get("tests_asset")
    if language != "python":
        raise TemplateValidationError(detail={"execution_spec": {"language": "unsupported"}})
    if not isinstance(entrypoint, str) or not _PYTHON_ENTRYPOINT.fullmatch(entrypoint):
        raise TemplateValidationError(
            detail={"execution_spec": {"entrypoint": "single_python_file_required"}}
        )
    if comparator != "token":
        raise TemplateValidationError(detail={"execution_spec": {"comparator": "unsupported"}})
    if network_mode != "DENY_ALL":
        raise TemplateValidationError(
            detail={"execution_spec": {"network_mode": "must_be_DENY_ALL"}}
        )
    if not isinstance(tests_asset, str) or not re.fullmatch(r"[0-9A-Za-z]{26}", tests_asset):
        raise TemplateValidationError(
            detail={"execution_spec": {"tests_asset": "invalid_public_id"}}
        )
    numeric = ("timeout_seconds", "memory_mb", "cpu_millicores")
    if any(
        isinstance(value.get(name), bool)
        or not isinstance(value.get(name), int)
        or value.get(name, 0) < 1
        for name in numeric
    ):
        raise TemplateValidationError(
            detail={"execution_spec": {"resources": "positive_integers_required"}}
        )
    if value["timeout_seconds"] > settings.TEMPLATE_CHECK_TIMEOUT_MAX_SECONDS:
        raise TemplateValidationError(detail={"execution_spec": {"timeout_seconds": "too_large"}})
    return {
        "language": language,
        "entrypoint": entrypoint,
        "timeout_seconds": int(value["timeout_seconds"]),
        "memory_mb": int(value["memory_mb"]),
        "cpu_millicores": int(value["cpu_millicores"]),
        "comparator": comparator,
        "tests_asset": tests_asset,
        "network_mode": network_mode,
    }


def _normalize_execution_spec_v2(value: dict[str, Any]) -> dict[str, Any]:
    allowed = LEGACY_EXECUTION_SPEC_KEYS | {
        "schema_version",
        "toolchain_version",
        "language_standard",
        "absolute_tolerance",
        "relative_tolerance",
        "toolchain",
        "materials",
    }
    unknown = sorted(set(value) - allowed)
    missing = sorted((LEGACY_EXECUTION_SPEC_KEYS - {"entrypoint"}) - set(value))
    if unknown or missing:
        detail: dict[str, Any] = {}
        if unknown:
            detail["unknown"] = unknown
        if missing:
            detail["required"] = missing
        raise TemplateValidationError(detail={"execution_spec": detail})
    if value.get("schema_version") != 2:
        raise TemplateValidationError(detail={"execution_spec": {"schema_version": "unsupported"}})
    language = value.get("language")
    if language is not None and not isinstance(language, str):
        raise TemplateValidationError(detail={"language": "invalid"})
    toolchain_version = value.get("toolchain_version")
    language_standard = value.get("language_standard")
    if toolchain_version is not None and not isinstance(toolchain_version, str):
        raise TemplateValidationError(detail={"toolchain_version": "invalid"})
    if language_standard is not None and not isinstance(language_standard, str):
        raise TemplateValidationError(detail={"language_standard": "invalid"})
    policy = (
        validate_frozen_language_policy(value["toolchain"], language=language)
        if "toolchain" in value
        else resolve_language_policy(
            language=language,
            toolchain_version=toolchain_version,
            language_standard=language_standard,
        )
    )
    if "toolchain" in value and (
        toolchain_version != policy["toolchain_version"]
        or language_standard != policy["language_standard"]
    ):
        raise TemplateValidationError(detail={"toolchain": "resolved_policy_mismatch"})
    entrypoint = value.get("entrypoint")
    if language is None:
        if entrypoint is not None:
            raise TemplateValidationError(detail={"entrypoint": "must_be_null_for_student_select"})
    else:
        extension = {
            "c": ".c",
            "cpp": ".cpp",
            "java": ".java",
            "python": ".py",
            "go": ".go",
        }[language]
        if (
            not isinstance(entrypoint, str)
            or not _PROJECT_ENTRYPOINT.fullmatch(entrypoint)
            or ".." in entrypoint.split("/")
            or not entrypoint.endswith(extension)
        ):
            raise TemplateValidationError(detail={"entrypoint": "invalid_for_language"})
    comparator = value.get("comparator")
    if comparator not in {"token", "numeric"}:
        raise TemplateValidationError(detail={"comparator": "unsupported"})
    tolerances: dict[str, float] = {}
    for key in ("absolute_tolerance", "relative_tolerance"):
        number = value.get(key, 1e-6)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise TemplateValidationError(detail={key: "non_negative_finite_number_required"})
        try:
            normalized_number = float(number)
        except OverflowError as exc:
            raise TemplateValidationError(
                detail={key: "non_negative_finite_number_required"}
            ) from exc
        if not math.isfinite(normalized_number) or normalized_number < 0:
            raise TemplateValidationError(detail={key: "non_negative_finite_number_required"})
        tolerances[key] = normalized_number
    if value.get("network_mode") != "DENY_ALL":
        raise TemplateValidationError(detail={"network_mode": "must_be_DENY_ALL"})
    materials = value.get("materials", [])
    if not isinstance(materials, list):
        raise TemplateValidationError(detail={"materials": "list_required"})
    clean_materials: list[dict[str, str]] = []
    seen_assets: set[str] = set()
    for material in materials:
        if not isinstance(material, dict) or set(material) != {"asset_id", "role"}:
            raise TemplateValidationError(detail={"materials": "invalid_entry"})
        asset_id, role = material.get("asset_id"), material.get("role")
        if not isinstance(asset_id, str) or not re.fullmatch(r"[0-9A-Za-z]{26}", asset_id):
            raise TemplateValidationError(detail={"materials": "invalid_asset_id"})
        if not isinstance(role, str) or role not in {
            "STUDENT_FILES",
            "HIDDEN_SOURCE",
            "PUBLIC_DATA",
        }:
            raise TemplateValidationError(detail={"materials": "unsupported_role"})
        if asset_id in seen_assets:
            raise TemplateValidationError(detail={"materials": "duplicate_asset"})
        seen_assets.add(asset_id)
        clean_materials.append({"asset_id": asset_id, "role": role})
    tests_asset = value.get("tests_asset")
    if not isinstance(tests_asset, str) or not re.fullmatch(r"[0-9A-Za-z]{26}", tests_asset):
        raise TemplateValidationError(detail={"tests_asset": "invalid_public_id"})
    numeric = ("timeout_seconds", "memory_mb", "cpu_millicores")
    if any(
        isinstance(value.get(name), bool)
        or not isinstance(value.get(name), int)
        or value.get(name, 0) < 1
        for name in numeric
    ):
        raise TemplateValidationError(detail={"resources": "positive_integers_required"})
    if value["timeout_seconds"] > settings.TEMPLATE_CHECK_TIMEOUT_MAX_SECONDS:
        raise TemplateValidationError(detail={"timeout_seconds": "too_large"})
    return {
        "schema_version": 2,
        "language": language,
        "toolchain_version": policy["toolchain_version"],
        "language_standard": policy["language_standard"],
        "toolchain": policy,
        "materials": clean_materials,
        "entrypoint": entrypoint,
        "timeout_seconds": int(value["timeout_seconds"]),
        "memory_mb": int(value["memory_mb"]),
        "cpu_millicores": int(value["cpu_millicores"]),
        "comparator": comparator,
        **tolerances,
        "tests_asset": tests_asset,
        "network_mode": "DENY_ALL",
    }


def build_execution_command(execution_spec: Mapping[str, Any]) -> list[str]:
    """Return a command only for toolchains verified in the current runtime."""
    normalized = _normalize_execution_spec(dict(execution_spec))
    if normalized.get("schema_version") == 2:
        if normalized["toolchain"]["mode"] == "STUDENT_SELECT":
            if normalized["toolchain"]["allowed_languages"] == ["python"]:
                return ["python", "main.py"]
            raise TemplateValidationError(detail={"toolchain": "runtime_not_available"})
        if normalized["language"] != "python":
            raise TemplateValidationError(detail={"toolchain": "runtime_not_available"})
        if normalized["comparator"] != "token":
            raise TemplateValidationError(detail={"comparator": "runtime_not_available"})
    return ["python", normalized["entrypoint"]]


def build_execution_plan(execution_spec: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return a fixed compile/run argv pair; never invokes a shell."""
    normalized = _normalize_execution_spec(dict(execution_spec))
    language = normalized.get("language")
    entrypoint = str(normalized.get("entrypoint") or "")
    if language == "python":
        return {"compile": [], "run": ["python", entrypoint]}
    if language == "c":
        return {
            "compile": ["gcc", "-std=c17", "-O2", entrypoint, "-o", "/tmp/.cache/program"],
            "run": ["/tmp/.cache/program"],
        }
    if language == "cpp":
        return {
            "compile": ["g++", "-std=c++20", "-O2", entrypoint, "-o", "/tmp/.cache/program"],
            "run": ["/tmp/.cache/program"],
        }
    if language == "java":
        return {
            "compile": ["javac", "-d", "/tmp/.cache/classes", entrypoint],
            "run": ["java", "-cp", "/tmp/.cache/classes", "Main"],
        }
    if language == "go":
        return {
            "compile": ["go", "build", "-o", "/tmp/.cache/program", entrypoint],
            "run": ["/tmp/.cache/program"],
        }
    raise TemplateValidationError(detail={"toolchain": "unsupported"})


def _course(course_id: str, actor: User, capability: str) -> Course:
    course = visible_course(actor=actor, portal="TEACHING", course_id=course_id)
    require_course_capability(course=course, actor=actor, capability=capability)
    return course


def _audit(
    context: ActorContext,
    *,
    action: str,
    target_type: str,
    target_ref: str,
    course_ref: str,
    before: Any = None,
    after: Any = None,
) -> None:
    append_audit(
        actor_ref=context.actor_ref,
        actor_portal=context.portal,
        actor_context={},
        action=action,
        target_type=target_type,
        target_ref=target_ref,
        course_ref=course_ref,
        before=before,
        after=after,
        result="SUCCEEDED",
        trace_id=context.trace_id,
        client_ip_hash=hash_client_ip(context.client_ip, salt=settings.AUDIT_IP_HASH_SALT),
        user_agent_summary=context.user_agent,
    )


def _event(
    context: ActorContext,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_ref: str,
    payload: dict[str, Any],
) -> None:
    append_outbox_event(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_ref=aggregate_ref,
        payload=payload,
        trace_id=context.trace_id,
    )
    enqueue_relay_after_commit(trace_id=context.trace_id)


def _expected(actual: int, expected: int) -> None:
    if actual != expected:
        raise RowVersionConflict(
            detail={"expected_row_version": expected, "actual_row_version": actual}
        )


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _material_digest_refs(refs: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"digest_sha256": str(item.get("digest_sha256", ""))}
        for item in sorted(refs, key=lambda item: str(item.get("digest_sha256", "")))
    ]


def _material_refs(course: Course, ids: list[str]) -> list[dict[str, str]]:
    normalized = list(dict.fromkeys(ids))
    rows = published_material_versions(course=course, public_ids=normalized)
    if len(rows) != len(normalized):
        raise TemplateValidationError(
            detail={"material_version_ids": "not_published_or_cross_course"}
        )
    by_id = {item.public_id: item for item in rows}
    return [
        {"version_id": item_id, "digest_sha256": by_id[item_id].digest_sha256}
        for item_id in sorted(normalized)
    ]


def _version_changes(course: Course, data: dict[str, Any]) -> dict[str, Any]:
    clean = {key: value for key, value in data.items() if key in VERSION_FIELDS}
    if "execution_spec" in clean:
        clean["execution_spec"] = _normalize_execution_spec(clean["execution_spec"])
    if "material_version_ids" in clean:
        clean["material_refs"] = _material_refs(course, list(clean.pop("material_version_ids")))
    resource_lookups = (
        (
            "runtime_adapter_id",
            RuntimeAdapter,
            {"status": RuntimeAdapter.Status.ENABLED},
        ),
        (
            "image_id",
            ImageAsset,
            {
                "approval_status": ImageAsset.ApprovalStatus.APPROVED,
                "scan_status": ImageAsset.ScanStatus.CLEAN,
            },
        ),
        (
            "resource_profile_id",
            ResourceProfile,
            {"status": ResourceProfile.Status.ACTIVE},
        ),
    )
    for field, model, filters in resource_lookups:
        if field not in clean:
            continue
        if clean[field] is None:
            continue
        resource = model.objects.filter(public_id=clean[field], **filters).first()
        if resource is None:
            raise TemplateValidationError(detail={field: "not_available"})
        clean[field] = resource.pk
    return clean


def _archive_template_name(template: Template) -> str:
    suffix = f"[archived {template.public_id[-8:]}]"
    return f"{template.name[:160 - len(suffix)]}{suffix}"


def _release_withdrawn_names(*, course: Course, name: str) -> None:
    """Rename withdrawn templates so a soft-deleted name can be reused.

    Templates are soft-deleted into WITHDRAWN and hidden from listings, but the
    (course, name) unique constraint keeps their name reserved. Releasing the
    name here prevents the confusing "state conflict" on re-creation.
    """
    archived = list(
        Template.objects.select_for_update()
        .filter(course=course, status=Template.Status.WITHDRAWN, name=name.strip())
    )
    for item in archived:
        compare_and_swap(
            Template,
            pk=item.pk,
            expected_version=item.row_version,
            changes={"name": _archive_template_name(item)},
        )


@transaction.atomic
def create_template(
    *,
    course_id: str,
    actor: User,
    name: str,
    category: str,
    description: str,
    context: ActorContext,
) -> Template:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    clean_name = name.strip()
    _release_withdrawn_names(course=course, name=clean_name)
    try:
        item = Template.objects.create(
            course=course,
            name=clean_name,
            category=category.strip(),
            description=description.strip(),
            owner=actor,
        )
    except IntegrityError as exc:
        raise TemplateNameExists(detail={"name": clean_name}) from exc
    _audit(
        context,
        action="labtemplate.create",
        target_type="labtemplate",
        target_ref=item.public_id,
        course_ref=course.public_id,
        after={"name": item.name, "status": item.status},
    )
    _event(
        context,
        event_type=events.TEMPLATE_CREATED,
        aggregate_type="labtemplate",
        aggregate_ref=item.public_id,
        payload={"course_id": course.public_id, "template_id": item.public_id},
    )
    return item


@transaction.atomic
def update_template(
    *,
    course_id: str,
    template_id: str,
    actor: User,
    expected_version: int,
    changes: dict[str, Any],
    context: ActorContext,
) -> Template:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        item = Template.objects.select_for_update().get(public_id=template_id, course=course)
    except Template.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _expected(item.row_version, expected_version)
    if item.status != Template.Status.DRAFT:
        raise TemplateStateConflict(detail={"status": item.status})
    clean = {
        key: str(value).strip()
        for key, value in changes.items()
        if key in {"name", "category", "description"}
    }
    try:
        changed = compare_and_swap(
            Template, pk=item.pk, expected_version=expected_version, changes=clean
        )
    except IntegrityError as exc:
        raise TemplateNameExists(detail={"name": clean.get("name", "")}) from exc
    _audit(
        context,
        action="labtemplate.update",
        target_type="labtemplate",
        target_ref=item.public_id,
        course_ref=course.public_id,
        before={"name": item.name},
        after=clean,
    )
    _event(
        context,
        event_type=events.TEMPLATE_UPDATED,
        aggregate_type="labtemplate",
        aggregate_ref=item.public_id,
        payload={"course_id": course.public_id, "template_id": item.public_id},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def delete_template(
    *,
    course_id: str,
    template_id: str,
    actor: User,
    expected_version: int,
    context: ActorContext,
) -> Template:
    """Soft-delete a template the actor owns (hard deletes are forbidden).

    DRAFT templates can be deleted directly; otherwise the teacher must first
    withdraw the published version through ``withdraw_version``.
    """

    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        template = Template.objects.select_for_update().get(public_id=template_id, course=course)
    except Template.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _expected(template.row_version, expected_version)
    if template.owner_id != actor.pk:
        raise TemplateDeleteForbidden(detail={"reason": "ONLY_OWNER"})
    if template.status != Template.Status.DRAFT:
        raise TemplateStateConflict(
            detail={"status": template.status, "hint": "已发布模板需先撤回版本再删除"}
        )
    changed = compare_and_swap(
        Template,
        pk=template.pk,
        expected_version=expected_version,
        changes={"status": Template.Status.WITHDRAWN},
    )
    _release_withdrawn_names(course=course, name=template.name)
    _audit(
        context,
        action="labtemplate.delete",
        target_type="labtemplate",
        target_ref=template.public_id,
        course_ref=course.public_id,
        before={"status": template.status},
        after={"status": Template.Status.WITHDRAWN},
    )
    _event(
        context,
        event_type=events.TEMPLATE_DELETED,
        aggregate_type="labtemplate",
        aggregate_ref=template.public_id,
        payload={"course_id": course.public_id, "template_id": template.public_id},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def save_execution_spec(
    *,
    course_id: str,
    template_id: str,
    version_id: str,
    actor: User,
    expected_version: int,
    spec: dict[str, Any],
    tests_json: str,
    context: ActorContext,
) -> TemplateVersion:
    """Server-side shortcut: register a default TESTS asset and freeze execution_spec.

    Most of the editor UI cannot upload binary assets; the demo-less quick path
    accepts the tests JSON payload inline, writes it via the internal MinIO
    client (no cross-origin upload), registers the asset CLEAN (validated JSON,
    small payload), and CAS-updates the draft version's execution_spec.
    """

    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        template = Template.objects.select_for_update().get(public_id=template_id, course=course)
        version = TemplateVersion.objects.select_for_update().get(
            public_id=version_id, template=template
        )
    except (Template.DoesNotExist, TemplateVersion.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    version = _content_guard(version, expected_version, context)

    raw_spec = {key: value for key, value in spec.items() if key != "tests_json"}
    raw_spec["tests_asset"] = "0" * 26
    normalized_spec = _normalize_execution_spec(raw_spec)
    if normalized_spec.get("schema_version") == 2:
        _execution_material_snapshots(version, normalized_spec["materials"])
    try:
        probe = json.loads(tests_json)
    except json.JSONDecodeError as exc:
        raise TemplateValidationError(detail={"tests_json": "invalid_json"}) from exc
    cases = probe.get("cases") if isinstance(probe, dict) else None
    if not isinstance(cases, list):
        raise TemplateValidationError(detail={"tests_json": "cases_required"})
    for item in cases:
        if not isinstance(item, dict) or not isinstance(
            item.get("input"), str
        ) or not isinstance(item.get("expected"), str):
            raise TemplateValidationError(detail={"tests_json": "case_shape"})
    content = json.dumps(probe, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    if len(content) > settings.TEMPLATE_ASSET_MAX_BYTES:
        raise TemplateValidationError(detail={"tests_json": "too_large"})

    object_key = f"template-assets/{version.public_id}/{new_ulid()}/tests.json"
    stored = object_storage().put_stream(
        bucket=settings.MINIO_BUCKET,
        object_key=object_key,
        stream=io.BytesIO(content),
        media_type="application/json",
    )
    asset = register_asset(
        bucket=settings.MINIO_BUCKET,
        object_key=object_key,
        object_version=stored.version_id,
        digest_sha256=digest,
        size_bytes=len(content),
        owner_type="TEMPLATE_VERSION",
        owner_ref=version.public_id,
        purpose="TESTS",
        media_type="application/json",
        original_name="tests.json",
    )
    asset = set_scan_result(
        asset_id=asset.pk,
        expected_version=asset.row_version,
        scan_status=ObjectAsset.ScanStatus.CLEAN,
    )
    raw_spec["tests_asset"] = asset.public_id
    clean_spec = _normalize_execution_spec(raw_spec)
    changed = compare_and_swap(
        TemplateVersion,
        pk=version.pk,
        expected_version=version.row_version,
        changes={"execution_spec": clean_spec},
    )
    _audit(
        context,
        action="labtemplate.execution_spec.save",
        target_type="labtemplate_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"tests_asset": asset.public_id},
    )
    _event(
        context,
        event_type=events.VERSION_UPDATED,
        aggregate_type="labtemplate_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id, "tests_asset": asset.public_id},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def create_version(
    *,
    course_id: str,
    template_id: str,
    actor: User,
    data: dict[str, Any],
    context: ActorContext,
) -> TemplateVersion:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        template = Template.objects.select_for_update().get(public_id=template_id, course=course)
    except Template.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    latest = template.versions.order_by("-version_no").first()
    version_no = 1 if latest is None else latest.version_no + 1
    clean = _version_changes(course, data)
    version = TemplateVersion.objects.create(
        template=template,
        version_no=version_no,
        created_by=actor,
        **clean,
    )
    _audit(
        context,
        action="labtemplate.version.create",
        target_type="labtemplate_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"version_no": version.version_no, "status": version.status},
    )
    _event(
        context,
        event_type=events.VERSION_CREATED,
        aggregate_type="labtemplate_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id, "template_id": template.public_id},
    )
    return version


@transaction.atomic
def update_version(
    *,
    course_id: str,
    version_id: str,
    actor: User,
    expected_version: int,
    changes: dict[str, Any],
    context: ActorContext,
) -> TemplateVersion:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        version = TemplateVersion.objects.select_for_update().get(
            public_id=version_id, template__course=course
        )
    except TemplateVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    version = _content_guard(version, expected_version, context)
    clean = _version_changes(course, changes)
    changed = compare_and_swap(
        TemplateVersion, pk=version.pk, expected_version=version.row_version, changes=clean
    )
    _audit(
        context,
        action="labtemplate.version.update",
        target_type="labtemplate_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        before={"row_version": expected_version},
        after={"fields": sorted(clean)},
    )
    _event(
        context,
        event_type=events.VERSION_UPDATED,
        aggregate_type="labtemplate_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id, "version_id": version.public_id},
    )
    return changed  # type: ignore[return-value]


def _content_version(course: Course, version_id: str, actor: User) -> TemplateVersion:
    try:
        return TemplateVersion.objects.select_for_update().get(
            public_id=version_id, template__course=course
        )
    except TemplateVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def _content_guard(
    version: TemplateVersion, expected_version: int, context: ActorContext
) -> TemplateVersion:
    """Validate content editing and unfreeze PRECHECK_PASSED after edits.

    Editing chapters, tasks, runtime fields, or rules invalidates the frozen
    precheck digest. A PRECHECK_PASSED version rolls back to DRAFT with
    spec_digest cleared, so the teacher re-runs the precheck before publishing.
    PRECHECK_FAILED versions keep editing without status changes (their digest
    is already invalid), and PUBLISHED versions stay immutable.
    """
    _expected(version.row_version, expected_version)
    if version.status in {TemplateVersion.Status.DRAFT, TemplateVersion.Status.PRECHECK_FAILED}:
        return version
    if version.status != TemplateVersion.Status.PRECHECK_PASSED:
        raise TemplateStateConflict(detail={"status": version.status})
    changed = compare_and_swap(
        TemplateVersion,
        pk=version.pk,
        expected_version=version.row_version,
        changes={"status": TemplateVersion.Status.DRAFT, "spec_digest": None},
    )  # type: ignore[assignment]
    _audit(
        context,
        action="labtemplate.version.reopen",
        target_type="labtemplate_version",
        target_ref=version.public_id,
        course_ref=version.template.course_id,
        before={"status": version.status},
        after={"status": TemplateVersion.Status.DRAFT, "reason": "content_edit"},
    )
    _event(
        context,
        event_type=events.VERSION_UPDATED,
        aggregate_type="labtemplate_version",
        aggregate_ref=version.public_id,
        payload={"course_id": version.template.course.public_id, "reason": "content_edit"},
    )
    return changed


def _profile(course: Course, value: str | None) -> ResourceProfile | None:
    if value is None:
        return None
    profile = ResourceProfile.objects.filter(
        public_id=value, status=ResourceProfile.Status.ACTIVE
    ).first()
    if profile is None:
        raise TemplateValidationError(detail={"resource_profile_id": "not_available"})
    return profile


def _chapter_payload(data: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "title",
        "description",
        "learning_objectives",
        "sort_order",
        "status",
        "resource_profile_id",
    }
    clean = {key: data[key] for key in allowed if key in data}
    if "title" in clean:
        clean["title"] = str(clean["title"]).strip()
        if not clean["title"]:
            raise TemplateValidationError(detail={"title": "required"})
    if "sort_order" in clean:
        try:
            clean["sort_order"] = int(clean["sort_order"])
        except (TypeError, ValueError) as exc:
            raise TemplateValidationError(
                detail={"sort_order": "positive_integer_required"}
            ) from exc
        if clean["sort_order"] < 1:
            raise TemplateValidationError(detail={"sort_order": "positive_integer_required"})
    return clean


def _task_payload(data: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "title",
        "description",
        "instructions",
        "task_type",
        "sort_order",
        "status",
        "execution_spec",
        "resource_profile_id",
        "submission_policy",
        "grading_policy",
        "question_spec",
        "marking_spec",
        "max_score",
        "active",
    }
    clean = {key: data[key] for key in allowed if key in data}
    for field in ("title", "task_type"):
        if field in clean:
            clean[field] = str(clean[field]).strip()
            if not clean[field]:
                raise TemplateValidationError(detail={field: "required"})
    if "sort_order" in clean:
        try:
            clean["sort_order"] = int(clean["sort_order"])
        except (TypeError, ValueError) as exc:
            raise TemplateValidationError(
                detail={"sort_order": "positive_integer_required"}
            ) from exc
        if clean["sort_order"] < 1:
            raise TemplateValidationError(detail={"sort_order": "positive_integer_required"})
    return clean


def _assessment_payload(clean: dict[str, Any], item: TemplateTask | None = None) -> None:
    from .questions import QUESTION_TYPES, normalize_question

    kind = clean.get("task_type", item.task_type if item else "")
    if kind not in QUESTION_TYPES:
        if any(key in clean for key in ("question_spec", "marking_spec", "max_score")):
            raise TemplateValidationError(detail={"task_type": "assessment_type_required"})
        return
    public, marking, points = normalize_question(
        task_type=kind,
        public=clean.get("question_spec", item.question_spec if item else {}),
        marking=clean.get("marking_spec", item.marking_spec if item else {}),
        max_score=clean.get("max_score", item.max_score if item else 0),
    )
    clean.update(question_spec=public, marking_spec=marking, max_score=points)


@transaction.atomic
def create_chapter(
    *,
    course_id: str,
    version_id: str,
    actor: User,
    expected_version: int,
    data: dict[str, Any],
    context: ActorContext,
) -> TemplateChapter:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    version = _content_guard(
        _content_version(course, version_id, actor), expected_version, context
    )
    clean = _chapter_payload(data)
    if "sort_order" not in clean:
        clean["sort_order"] = (
            version.chapters.order_by("-sort_order").values_list("sort_order", flat=True).first()
            or 0
        ) + 1
    if "resource_profile_id" in clean:
        clean["resource_profile"] = _profile(course, clean.pop("resource_profile_id"))
    try:
        item = TemplateChapter.objects.create(template_version=version, **clean)
    except IntegrityError as exc:
        raise TemplateValidationError(detail={"sort_order": "unique_positive_required"}) from exc
    compare_and_swap(
        TemplateVersion, pk=version.pk, expected_version=version.row_version, changes={}
    )
    _audit(
        context,
        action="labtemplate.chapter.create",
        target_type="labtemplate_chapter",
        target_ref=item.public_id,
        course_ref=course.public_id,
        after={"version_id": version.public_id},
    )
    _event(
        context,
        event_type=events.CHAPTER_CREATED,
        aggregate_type="labtemplate_chapter",
        aggregate_ref=item.public_id,
        payload={"version_id": version.public_id},
    )
    return item


@transaction.atomic
def update_chapter(
    *,
    course_id: str,
    chapter_id: str,
    actor: User,
    expected_version: int,
    changes: dict[str, Any],
    context: ActorContext,
) -> TemplateChapter:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        item = (
            TemplateChapter.objects.select_for_update()
            .select_related("template_version")
            .get(public_id=chapter_id, template_version__template__course=course)
        )
    except TemplateChapter.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    template_version = _content_guard(item.template_version, expected_version, context)
    clean = _chapter_payload(changes)
    if "resource_profile_id" in clean:
        resource_profile_id = clean.pop("resource_profile_id")
        profile = _profile(course, resource_profile_id) if resource_profile_id else None
        clean["resource_profile_id"] = profile.pk if profile is not None else None
    try:
        changed = compare_and_swap(
            TemplateChapter, pk=item.pk, expected_version=item.row_version, changes=clean
        )
        changed_version = compare_and_swap(
            TemplateVersion,
            pk=item.template_version_id,
            expected_version=template_version.row_version,
            changes={},
        )
        _audit(
            context,
            action="labtemplate.chapter.update",
            target_type="labtemplate_chapter",
            target_ref=item.public_id,
            course_ref=course.public_id,
            after={"fields": sorted(clean)},
        )
        _event(
            context,
            event_type=events.CHAPTER_UPDATED,
            aggregate_type="labtemplate_chapter",
            aggregate_ref=item.public_id,
            payload={"version_id": changed_version.public_id},
        )
        return changed  # type: ignore[return-value]
    except IntegrityError as exc:
        raise TemplateValidationError(detail={"sort_order": "unique_positive_required"}) from exc


@transaction.atomic
def create_task(
    *,
    course_id: str,
    chapter_id: str,
    actor: User,
    expected_version: int,
    data: dict[str, Any],
    context: ActorContext,
) -> TemplateTask:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        chapter = (
            TemplateChapter.objects.select_for_update()
            .select_related("template_version")
            .get(public_id=chapter_id, template_version__template__course=course)
        )
    except TemplateChapter.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    template_version = _content_guard(chapter.template_version, expected_version, context)
    clean = _task_payload(data)
    _assessment_payload(clean)
    if "sort_order" not in clean:
        clean["sort_order"] = (
            chapter.tasks.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
        ) + 1
    if "resource_profile_id" in clean:
        clean["resource_profile"] = _profile(course, clean.pop("resource_profile_id"))
    try:
        item = TemplateTask.objects.create(chapter=chapter, **clean)
    except IntegrityError as exc:
        raise TemplateValidationError(detail={"sort_order": "unique_positive_required"}) from exc
    compare_and_swap(
        TemplateVersion,
        pk=chapter.template_version_id,
        expected_version=template_version.row_version,
        changes={},
    )
    _audit(
        context,
        action="labtemplate.task.create",
        target_type="labtemplate_task",
        target_ref=item.public_id,
        course_ref=course.public_id,
        after={"chapter_id": chapter.public_id},
    )
    _event(
        context,
        event_type=events.TASK_CREATED,
        aggregate_type="labtemplate_task",
        aggregate_ref=item.public_id,
        payload={"chapter_id": chapter.public_id},
    )
    return item


@transaction.atomic
def update_task(
    *,
    course_id: str,
    task_id: str,
    actor: User,
    expected_version: int,
    changes: dict[str, Any],
    context: ActorContext,
) -> TemplateTask:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        item = (
            TemplateTask.objects.select_for_update()
            .select_related("chapter__template_version")
            .get(public_id=task_id, chapter__template_version__template__course=course)
        )
    except TemplateTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    template_version = _content_guard(item.chapter.template_version, expected_version, context)
    clean = _task_payload(changes)
    _assessment_payload(clean, item)
    if "resource_profile_id" in clean:
        resource_profile_id = clean.pop("resource_profile_id")
        profile = _profile(course, resource_profile_id) if resource_profile_id else None
        clean["resource_profile_id"] = profile.pk if profile is not None else None
    try:
        changed = compare_and_swap(
            TemplateTask, pk=item.pk, expected_version=item.row_version, changes=clean
        )
        changed_version = compare_and_swap(
            TemplateVersion,
            pk=item.chapter.template_version_id,
            expected_version=template_version.row_version,
            changes={},
        )
        _audit(
            context,
            action="labtemplate.task.update",
            target_type="labtemplate_task",
            target_ref=item.public_id,
            course_ref=course.public_id,
            after={"fields": sorted(clean)},
        )
        _event(
            context,
            event_type=events.TASK_UPDATED,
            aggregate_type="labtemplate_task",
            aggregate_ref=item.public_id,
            payload={"version_id": changed_version.public_id},
        )
        return changed  # type: ignore[return-value]
    except IntegrityError as exc:
        raise TemplateValidationError(detail={"sort_order": "unique_positive_required"}) from exc


def _reorder(
    *,
    course: Course,
    version: TemplateVersion,
    parent: TemplateChapter | None,
    ids: list[str],
    model: type[TemplateChapter] | type[TemplateTask],
    context: ActorContext,
) -> TemplateVersion:
    if len(ids) != len(set(ids)) or not ids:
        raise TemplateValidationError(detail={"ids": "complete_unique_order_required"})
    query = model.objects.select_for_update().filter(public_id__in=ids)
    if model is TemplateTask:
        query = query.filter(active=True)
    if parent is None:
        query = query.filter(template_version=version)  # type: ignore[union-attr]
    else:
        query = query.filter(chapter=parent)  # type: ignore[union-attr]
    rows = list(query)
    expected_count = (
        version.chapters.count() if parent is None else parent.tasks.filter(active=True).count()
    )
    if len(rows) != len(ids) or len(rows) != expected_count:
        raise TemplateValidationError(detail={"ids": "complete_unique_order_required"})
    rows_by_id = {row.public_id: row for row in rows}
    for public_id in ids:
        row = rows_by_id[public_id]
        compare_and_swap(
            model,
            pk=row.pk,
            expected_version=row.row_version,
            changes={
                "sort_order": row.sort_order
                + expected_count
                + max(row.sort_order, expected_count)
                + 1
            },
        )
    for index, public_id in enumerate(ids, start=1):
        row = model.objects.get(pk=rows_by_id[public_id].pk)
        compare_and_swap(
            model, pk=row.pk, expected_version=row.row_version, changes={"sort_order": index}
        )
    changed = compare_and_swap(
        TemplateVersion, pk=version.pk, expected_version=version.row_version, changes={}
    )
    target = parent.public_id if parent is not None else version.public_id
    _audit(
        context,
        action="labtemplate.content.reorder",
        target_type="labtemplate_chapter" if parent is None else "labtemplate_task",
        target_ref=target,
        course_ref=course.public_id,
        after={"ids": ids},
    )
    _event(
        context,
        event_type=events.CONTENT_REORDERED,
        aggregate_type="labtemplate_version",
        aggregate_ref=version.public_id,
        payload={"parent_id": target, "ids": ids},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def reorder_chapters(
    *,
    course_id: str,
    version_id: str,
    actor: User,
    expected_version: int,
    chapter_ids: list[str],
    context: ActorContext,
) -> TemplateVersion:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    version = _content_version(course, version_id, actor)
    version = _content_guard(version, expected_version, context)
    return _reorder(
        course=course,
        version=version,
        parent=None,
        ids=chapter_ids,
        model=TemplateChapter,
        context=context,
    )


@transaction.atomic
def reorder_tasks(
    *,
    course_id: str,
    chapter_id: str,
    actor: User,
    expected_version: int,
    task_ids: list[str],
    context: ActorContext,
) -> TemplateVersion:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        chapter = (
            TemplateChapter.objects.select_for_update()
            .select_related("template_version")
            .get(public_id=chapter_id, template_version__template__course=course)
        )
    except TemplateChapter.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    template_version = _content_guard(chapter.template_version, expected_version, context)
    return _reorder(
        course=course,
        version=template_version,
        parent=chapter,
        ids=task_ids,
        model=TemplateTask,
        context=context,
    )


def _rule_payload(data: dict[str, Any]) -> dict[str, Any]:
    required = {
        "position",
        "checker_type",
        "input_schema",
        "output_schema",
        "timeout_seconds",
        "resource_limit",
        "network_policy",
        "display_policy",
        "failure_semantics",
    }
    if not required.issubset(data):
        raise TemplateValidationError(detail={"rule_required": sorted(required - data.keys())})
    clean = {key: data[key] for key in required}
    clean["checker_type"] = str(clean["checker_type"]).strip().upper()
    clean["position_key"] = str(clean["position"])
    clean["rule_digest"] = _digest(clean)
    return clean


@transaction.atomic
def replace_rules(
    *,
    course_id: str,
    version_id: str,
    actor: User,
    expected_version: int,
    rules: list[dict[str, Any]],
    context: ActorContext,
) -> TemplateVersion:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        version = TemplateVersion.objects.select_for_update().get(
            public_id=version_id, template__course=course
        )
    except TemplateVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    version = _content_guard(version, expected_version, context)
    payloads = [_rule_payload(item) for item in rules]
    positions = [int(item["position"]) for item in payloads]
    if len(positions) != len(set(positions)) or any(position < 1 for position in positions):
        raise TemplateValidationError(detail={"position": "unique_positive_required"})
    for rule in AutoCheckRule.objects.select_for_update().filter(
        template_version=version, is_active=True
    ):
        compare_and_swap(
            AutoCheckRule,
            pk=rule.pk,
            expected_version=rule.row_version,
            changes={"is_active": False, "position_key": f"removed:{rule.public_id}"},
        )
    AutoCheckRule.objects.bulk_create([
        AutoCheckRule(template_version=version, **item) for item in payloads
    ])
    changed = compare_and_swap(
        TemplateVersion, pk=version.pk, expected_version=version.row_version, changes={}
    )
    _audit(
        context,
        action="labtemplate.rules.replace",
        target_type="labtemplate_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"rule_count": len(payloads)},
    )
    _event(
        context,
        event_type=events.RULES_UPDATED,
        aggregate_type="labtemplate_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id, "rule_count": len(payloads)},
    )
    return changed  # type: ignore[return-value]


def _asset_snapshot(asset: ObjectAsset | None) -> dict[str, Any] | None:
    if asset is None:
        return None
    if (
        asset.status != ObjectAsset.Status.ACTIVE
        or asset.scan_status != ObjectAsset.ScanStatus.CLEAN
    ):
        raise TemplateAssetNotReady(detail={"asset_id": asset.public_id})
    return {
        "digest_sha256": asset.digest_sha256,
        "size_bytes": asset.size_bytes,
        "media_type": asset.media_type,
        "object_version": asset.object_version,
    }


def _execution_material_snapshots(
    version: TemplateVersion, materials: list[dict[str, str]]
) -> list[dict[str, Any]]:
    purposes = {
        "STUDENT_FILES": "STARTER",
        "HIDDEN_SOURCE": "HIDDEN_SOURCE",
        "PUBLIC_DATA": "PUBLIC_DATA",
    }
    snapshots = []
    for item in materials:
        try:
            asset = ObjectAsset.objects.get(
                public_id=item["asset_id"],
                owner_type="TEMPLATE_VERSION",
                owner_ref=version.public_id,
                purpose=purposes[item["role"]],
            )
        except ObjectAsset.DoesNotExist as exc:
            raise TemplateValidationError(
                detail={"materials": {item["asset_id"]: "not_found_or_wrong_role"}}
            ) from exc
        snapshots.append({
            "asset_id": asset.public_id,
            "role": item["role"],
            "purpose": asset.purpose,
            "asset": _asset_snapshot(asset),
        })
    return snapshots


def _validated_snapshot(
    version: TemplateVersion,
    *,
    stage: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    def report(name: str, result: str) -> None:
        if stage is not None:
            stage(name, result)

    from .questions import assessment_snapshot

    assessment = assessment_snapshot(version, run_reference=stage is not None)
    if assessment is not None:
        report("QUESTIONS", "PASSED")
        return assessment

    course = version.template.course
    report("SCOPE", "RUNNING")
    material_ids = [str(item.get("version_id", "")) for item in version.material_refs]
    current_materials = _material_refs(course, material_ids)
    if current_materials != version.material_refs:
        raise TemplateDigestMismatch(detail={"material_refs": "changed"})
    report("SCOPE", "PASSED")

    report("ASSETS", "RUNNING")
    assets = {field: _asset_snapshot(getattr(version, field)) for field in ASSET_FIELDS}
    report("ASSETS", "PASSED")

    execution_spec = _normalize_execution_spec(version.execution_spec)
    execution_materials = _execution_material_snapshots(
        version, execution_spec.get("materials", [])
    ) if execution_spec.get("schema_version") == 2 else []

    report("GOVERNANCE", "RUNNING")
    governance = template_governance_snapshot(
        course=course,
        runtime_adapter_id=version.runtime_adapter.public_id,
        image_id=version.image.public_id,
        resource_profile_id=version.resource_profile.public_id,
    )
    if governance is None:
        raise TemplatePrecheckFailed(detail={"governance": "resource_not_approved"})
    adapter = governance["adapter"]
    image = governance["image"]
    profile: ResourceProfile = governance["profile"]
    cpu_limit = getattr(profile, "cpu_limit_millicores", None) or profile.cpu_millicores
    memory_limit = getattr(profile, "memory_limit_mb", None) or profile.memory_mb
    if adapter.runtime_type != version.runtime_type or profile.runtime_type != version.runtime_type:
        raise TemplateValidationError(detail={"runtime_type": "resource_mismatch"})
    if version.runtime_type != RuntimeAdapter.RuntimeType.CONTAINER:
        raise TemplateValidationError(
            detail={"execution_spec": {"runtime_type": "container_required"}}
        )
    if execution_spec["timeout_seconds"] > settings.TEMPLATE_CHECK_TIMEOUT_MAX_SECONDS:
        raise TemplateValidationError(detail={"execution_spec": {"timeout_seconds": "too_large"}})
    if execution_spec["memory_mb"] > memory_limit:
        raise TemplateValidationError(detail={"execution_spec": {"memory_mb": "exceeds_profile"}})
    if execution_spec["cpu_millicores"] > cpu_limit:
        raise TemplateValidationError(
            detail={"execution_spec": {"cpu_millicores": "exceeds_profile"}}
        )
    try:
        tests_asset = ObjectAsset.objects.get(
            public_id=execution_spec["tests_asset"],
            owner_type="TEMPLATE_VERSION",
            owner_ref=version.public_id,
            purpose="TESTS",
        )
    except ObjectAsset.DoesNotExist as exc:
        raise TemplateValidationError(
            detail={"execution_spec": {"tests_asset": "not_found_or_cross_version"}}
        ) from exc
    if (
        tests_asset.status != ObjectAsset.Status.ACTIVE
        or tests_asset.scan_status != ObjectAsset.ScanStatus.CLEAN
    ):
        raise TemplateAssetNotReady(detail={"tests_asset": tests_asset.public_id})
    report("GOVERNANCE", "PASSED")

    mode = version.network_policy.get("mode", "DENY_ALL")
    report("RULES", "RUNNING")
    rules: list[dict[str, Any]] = []
    for rule in version.auto_check_rules.filter(is_active=True).order_by("position"):
        try:
            Draft202012Validator.check_schema(rule.input_schema)
            Draft202012Validator.check_schema(rule.output_schema)
        except SchemaError as exc:
            raise TemplateValidationError(
                detail={"rule_id": rule.public_id, "schema": "invalid"}
            ) from exc
        if rule.timeout_seconds > settings.TEMPLATE_CHECK_TIMEOUT_MAX_SECONDS:
            raise TemplateValidationError(
                detail={"rule_id": rule.public_id, "timeout": "too_large"}
            )
        limits = rule.resource_limit
        if (
            int(limits.get("cpu_millicores", 0)) > cpu_limit
            or int(limits.get("memory_mb", 0)) > memory_limit
            or int(limits.get("disk_gb", 0)) > profile.disk_gb
        ):
            raise TemplateValidationError(
                detail={"rule_id": rule.public_id, "resource": "too_large"}
            )
        if rule.network_policy.get("mode", "DENY_ALL") not in {"DENY_ALL", mode}:
            raise TemplateValidationError(
                detail={"rule_id": rule.public_id, "network": "too_broad"}
            )
        if rule.failure_semantics.get("on_failure") not in {"FAIL_CHECK", "WARN"}:
            raise TemplateValidationError(detail={"rule_id": rule.public_id, "failure": "invalid"})
        rules.append({
            "position": rule.position,
            "checker_type": rule.checker_type,
            "input_schema": rule.input_schema,
            "output_schema": rule.output_schema,
            "timeout_seconds": rule.timeout_seconds,
            "resource_limit": rule.resource_limit,
            "network_policy": rule.network_policy,
            "display_policy": rule.display_policy,
            "failure_semantics": rule.failure_semantics,
            "rule_digest": rule.rule_digest,
        })
    report("RULES", "PASSED")

    report("POLICY", "RUNNING")
    policy = version.network_policy
    mode = policy.get("mode", "DENY_ALL")
    if mode not in {"DENY_ALL", "ALLOWLIST"} or policy.get("privileged", False) is not False:
        raise TemplateValidationError(detail={"network_policy": "unsafe"})
    if profile.network_mode == ResourceProfile.NetworkMode.DENY_ALL and mode != "DENY_ALL":
        raise TemplateValidationError(detail={"network_policy": "profile_denies_egress"})
    platform_rules = [item.rules for item in governance["security_policies"]]
    if (
        any(item.get("default_egress") == "DENY_ALL" for item in platform_rules)
        and mode != "DENY_ALL"
    ):
        raise TemplateValidationError(detail={"network_policy": "policy_denies_egress"})
    allowed = {_canonical(item) for item in governance["allowlist"]}
    requested = {_canonical(item) for item in policy.get("targets", [])}
    if mode == "ALLOWLIST" and not requested.issubset(allowed):
        raise TemplateValidationError(detail={"network_policy": "target_not_approved"})
    if version.workspace_capabilities.get("require_gateway", True) is not True:
        raise TemplateValidationError(detail={"workspace_capabilities": "gateway_required"})
    capability_names = {
        "webide",
        "notebook",
        "terminal",
        "preview",
        "snapshot",
        "checkpoint",
    }
    declared_capabilities = {
        key: value
        for key, value in version.workspace_capabilities.items()
        if key != "require_gateway"
    }
    if set(declared_capabilities) - capability_names or any(
        not isinstance(value, bool) for value in declared_capabilities.values()
    ):
        raise TemplateValidationError(detail={"workspace_capabilities": "invalid_contract"})
    if not any(
        declared_capabilities.get(name) for name in ("webide", "notebook", "terminal", "preview")
    ):
        raise TemplateValidationError(detail={"workspace_capabilities": "interactive_required"})
    report("POLICY", "PASSED")

    # V2 runs use compile/run plans; the legacy command builder only supports Python.
    execution_plans = {}
    if execution_spec.get("schema_version") == 2:
        policy = execution_spec["toolchain"]
        for language in policy["allowed_languages"]:
            selected = dict(execution_spec)
            if policy["mode"] == "STUDENT_SELECT":
                selected.update(
                    language=language,
                    entrypoint=TOOLCHAINS_BY_LANGUAGE[language]["entrypoint"],
                    toolchain=resolve_language_policy(
                        language=language,
                        toolchain_version=policy["default_versions"][language],
                        language_standard=None,
                    ),
                )
                selected.update(
                    toolchain_version=selected["toolchain"]["toolchain_version"],
                    language_standard=selected["toolchain"]["language_standard"],
                )
            execution_plans[language] = build_execution_plan(selected)

    from .questions import QUESTION_TYPES, normalize_question

    question_specs = []
    for question in TemplateTask.objects.filter(
        chapter__template_version=version, task_type__in=QUESTION_TYPES,
    ).order_by("chapter__sort_order", "sort_order", "id"):
        public, marking, points = normalize_question(
            task_type=question.task_type, public=question.question_spec,
            marking=question.marking_spec, max_score=question.max_score,
        )
        question_specs.append({
            "id": question.public_id, "chapter_id": question.chapter.public_id,
            "title": question.title, "description": question.description,
            "instructions": question.instructions, "sort_order": question.sort_order,
            "task_type": question.task_type, "question_spec": public,
            "marking_spec": marking, "max_score": str(points),
        })

    return {
        **({"questions": question_specs} if question_specs else {}),
        "runtime_type": version.runtime_type,
        "runtime_adapter": {"code": adapter.code, "driver": adapter.driver},
        "image_digest": image.digest,
        "resource_profile": {
            "code": profile.code,
            "cpu_millicores": profile.cpu_millicores,
            "memory_mb": profile.memory_mb,
            "cpu_request_millicores": getattr(profile, "cpu_request_millicores", None)
            or profile.cpu_millicores,
            "cpu_limit_millicores": cpu_limit,
            "memory_request_mb": getattr(profile, "memory_request_mb", None) or profile.memory_mb,
            "memory_limit_mb": memory_limit,
            "disk_gb": profile.disk_gb,
            "network_mode": profile.network_mode,
        },
        "dependencies": version.dependencies,
        "execution_spec": execution_spec,
        "execution_materials": execution_materials,
        "execution_command": (
            [] if execution_plans else list(build_execution_command(execution_spec))
        ),
        **({"execution_plans": execution_plans} if execution_plans else {}),
        "execution_tests_asset": {
            "public_id": tests_asset.public_id,
            "digest_sha256": tests_asset.digest_sha256,
            "object_version": tests_asset.object_version,
        },
        "network_policy": version.network_policy,
        "workspace_capabilities": version.workspace_capabilities,
        "material_refs": _material_digest_refs(version.material_refs),
        "assets": assets,
        "report_policy": version.report_policy,
        "review_policy": version.review_policy,
        "retention_days": version.retention_days,
        "rules": rules,
    }


def compute_spec_digest(version: TemplateVersion) -> str:
    return _digest(_validated_snapshot(version))


def _draft_request_digest(version: TemplateVersion) -> str:
    return _digest({
        "version_id": version.public_id,
        "row_version": version.row_version,
        "rules": list(
            version.auto_check_rules.filter(is_active=True)
            .order_by("position")
            .values_list("rule_digest", flat=True)
        ),
    })


@transaction.atomic
def request_precheck(
    *,
    course_id: str,
    version_id: str,
    actor: User,
    expected_version: int,
    context: ActorContext,
) -> TemplatePrecheckRun:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        version = (
            TemplateVersion.objects.select_for_update()
            .select_related("template__course")
            .prefetch_related("auto_check_rules", "chapters__tasks")
            .get(public_id=version_id, template__course=course)
        )
    except TemplateVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _expected(version.row_version, expected_version)
    if version.status not in {TemplateVersion.Status.DRAFT, TemplateVersion.Status.PRECHECK_FAILED}:
        raise TemplateStateConflict(detail={"status": version.status})
    if TemplatePrecheckRun.objects.filter(
        template_version=version,
        status__in=(
            TemplatePrecheckRun.Status.QUEUED,
            TemplatePrecheckRun.Status.RUNNING,
            TemplatePrecheckRun.Status.RETRY,
        ),
    ).exists():
        raise TemplateStateConflict(detail={"precheck": "already_running"})
    run = TemplatePrecheckRun.objects.create(
        template_version=version,
        requested_by=actor,
        requested_digest=_draft_request_digest(version),
        trace_id=context.trace_id,
    )
    compare_and_swap(
        TemplateVersion,
        pk=version.pk,
        expected_version=expected_version,
        changes={"status": TemplateVersion.Status.PRECHECKING, "spec_digest": None},
    )
    _audit(
        context,
        action="labtemplate.precheck.request",
        target_type="template_precheck_run",
        target_ref=run.public_id,
        course_ref=course.public_id,
        after={"version_id": version.public_id, "status": run.status},
    )
    _event(
        context,
        event_type=events.PRECHECK_REQUESTED,
        aggregate_type="labtemplate_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id, "run_id": run.public_id},
    )
    return run


def _set_run(run: TemplatePrecheckRun, **changes: Any) -> TemplatePrecheckRun:
    return compare_and_swap(
        TemplatePrecheckRun, pk=run.pk, expected_version=run.row_version, changes=changes
    )  # type: ignore[return-value]


def _stage(run: TemplatePrecheckRun, name: str, result: str) -> TemplatePrecheckRun:
    stages = [
        *run.stage_results,
        {"stage": name, "result": result, "at": timezone.now().isoformat()},
    ]
    return _set_run(run, current_stage=name, stage_results=stages)


def execute_precheck(*, run_id: str) -> TemplatePrecheckRun:
    with transaction.atomic():
        try:
            run = (
                TemplatePrecheckRun.objects.select_for_update()
                .select_related(
                    "template_version__template__course",
                    "template_version__runtime_adapter",
                    "template_version__image",
                    "template_version__resource_profile",
                    "template_version__manual_asset",
                    "template_version__starter_asset",
                    "template_version__report_template_asset",
                )
                .prefetch_related("template_version__auto_check_rules")
                .get(public_id=run_id)
            )
        except TemplatePrecheckRun.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        if run.status in {
            TemplatePrecheckRun.Status.PASSED,
            TemplatePrecheckRun.Status.FAILED,
        }:
            return run
        if run.attempt_count >= run.max_attempts:
            return _set_run(
                run,
                status=TemplatePrecheckRun.Status.FAILED,
                error_code="PRECHECK_MAX_ATTEMPTS_EXCEEDED",
                retryable=False,
                completed_at=timezone.now(),
            )
        run = _set_run(
            run,
            status=TemplatePrecheckRun.Status.RUNNING,
            attempt_count=run.attempt_count + 1,
            started_at=run.started_at or timezone.now(),
            retryable=False,
        )
        PRECHECK_ACTIVE.inc()
    started = timezone.now()
    try:
        with transaction.atomic():
            run = TemplatePrecheckRun.objects.select_for_update().get(pk=run.pk)
            version = (
                TemplateVersion.objects.select_for_update()
                .select_related(
                    "template__course",
                    "runtime_adapter",
                    "image",
                    "resource_profile",
                    "manual_asset",
                    "starter_asset",
                    "report_template_asset",
                )
                .prefetch_related("auto_check_rules")
                .get(pk=run.template_version_id)
            )

            def report(stage_name: str, result: str) -> None:
                nonlocal run
                if result == "RUNNING":
                    run = _set_run(run, current_stage=stage_name)
                else:
                    run = _stage(run, stage_name, result)

            snapshot = _validated_snapshot(version, stage=report)
            run = _set_run(run, current_stage="DIGEST")
            digest = _digest(snapshot)
            duplicate = TemplateVersion.objects.filter(
                template=version.template,
                spec_digest=digest,
            ).exclude(pk=version.pk)
            if duplicate.exists():
                raise TemplateDigestMismatch(detail={"spec_digest": "duplicate"})
            run = _stage(run, "DIGEST", "PASSED")
            try:
                with transaction.atomic():
                    compare_and_swap(
                        TemplateVersion,
                        pk=version.pk,
                        expected_version=version.row_version,
                        changes={
                            "status": TemplateVersion.Status.PRECHECK_PASSED,
                            "spec_digest": digest,
                        },
                    )
            except IntegrityError as exc:
                raise TemplateDigestMismatch(detail={"spec_digest": "duplicate"}) from exc
            run = _set_run(
                run,
                status=TemplatePrecheckRun.Status.PASSED,
                completed_at=timezone.now(),
                error_code="",
                error_detail_masked={},
            )
            append_outbox_event(
                event_type=events.PRECHECK_COMPLETED,
                aggregate_type="labtemplate_version",
                aggregate_ref=version.public_id,
                payload={
                    "course_id": version.template.course.public_id,
                    "run_id": run.public_id,
                    "status": "PASSED",
                },
                trace_id=run.trace_id,
            )
            enqueue_relay_after_commit(trace_id=run.trace_id)
            PRECHECK_RUNS.labels(result="passed").inc()
            return run
    except (
        TemplateValidationError,
        TemplateAssetNotReady,
        TemplatePrecheckFailed,
        TemplateDigestMismatch,
    ) as exc:
        failed_stage = run.current_stage or "VALIDATION"
        completed_stages = list(run.stage_results)
        with transaction.atomic():
            run = TemplatePrecheckRun.objects.select_for_update().get(pk=run.pk)
            version = TemplateVersion.objects.select_for_update().get(pk=run.template_version_id)
            stages = [
                *completed_stages,
                {
                    "stage": failed_stage,
                    "result": "FAILED",
                    "at": timezone.now().isoformat(),
                },
            ]
            run = _set_run(
                run,
                status=TemplatePrecheckRun.Status.FAILED,
                current_stage=failed_stage,
                stage_results=stages,
                error_code=exc.code,
                error_detail_masked=exc.detail,
                retryable=False,
                completed_at=timezone.now(),
            )
            compare_and_swap(
                TemplateVersion,
                pk=version.pk,
                expected_version=version.row_version,
                changes={"status": TemplateVersion.Status.PRECHECK_FAILED, "spec_digest": None},
            )
            append_failure(
                failure_type="TEMPLATE_PRECHECK",
                subject_type="TEMPLATE_VERSION",
                subject_ref=version.public_id,
                error_code=exc.code,
                message=exc.response_message,
                detail=exc.detail,
                retryable=False,
                trace_id=run.trace_id,
            )
            PRECHECK_RUNS.labels(result="failed").inc()
            return run
    finally:
        PRECHECK_ACTIVE.dec()
        PRECHECK_DURATION.observe((timezone.now() - started).total_seconds())


@transaction.atomic
def publish_version(
    *, course_id: str, version_id: str, actor: User, expected_version: int, context: ActorContext
) -> TemplateVersion:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        version = (
            TemplateVersion.objects.select_for_update()
            .select_related(
                "template__course",
                "runtime_adapter",
                "image",
                "resource_profile",
                "manual_asset",
                "starter_asset",
                "report_template_asset",
            )
            .prefetch_related("auto_check_rules")
            .get(public_id=version_id, template__course=course)
        )
    except TemplateVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _expected(version.row_version, expected_version)
    if version.status != TemplateVersion.Status.PRECHECK_PASSED or not version.spec_digest:
        raise TemplateStateConflict(detail={"status": version.status})
    if not version.chapters.exists():
        raise TemplateValidationError(
            message="模板规格无效：当前版本没有任何章节，请先在「内容结构」添加章节",
            detail={"chapters": "at_least_one_required"},
        )
    # Publishing the version cascades any DRAFT chapters/tasks to PUBLISHED:
    # the per-item publish endpoints were never shipped, and the version-level
    # publish is the single release action teachers use.
    chapters_to_publish = list(
        TemplateChapter.objects.select_for_update()
        .filter(template_version=version)
        .exclude(status=TemplateChapter.Status.PUBLISHED)
    )
    tasks_to_publish = list(
        TemplateTask.objects.select_for_update()
        .filter(chapter__template_version=version)
        .exclude(status=TemplateTask.Status.PUBLISHED)
    )
    for chapter in chapters_to_publish:
        compare_and_swap(
            TemplateChapter,
            pk=chapter.pk,
            expected_version=chapter.row_version,
            changes={"status": TemplateChapter.Status.PUBLISHED},
        )
    for task in tasks_to_publish:
        compare_and_swap(
            TemplateTask,
            pk=task.pk,
            expected_version=task.row_version,
            changes={"status": TemplateTask.Status.PUBLISHED},
        )
    if version.image_id and not ExperimentImage.objects.filter(
        template_version=version, status=ExperimentImage.Status.READY
    ).exists():
        ExperimentImage.objects.create(
            template_version=version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry=version.image.registry,
            repository=version.image.repository,
            requested_tag=version.image.display_tag or "stable",
            resolved_digest=version.image.digest,
            image_asset=version.image,
            status=ExperimentImage.Status.READY,
            scan_status=ExperimentImage.ScanStatus.CLEAN,
            trace_id=context.trace_id,
            created_by=actor,
        )
    publish_snapshot = _validated_snapshot(version)
    if _digest(publish_snapshot) != version.spec_digest:
        raise TemplateDigestMismatch()
    now = timezone.now()
    changed = compare_and_swap(
        TemplateVersion,
        pk=version.pk,
        expected_version=expected_version,
        changes={
            "status": TemplateVersion.Status.PUBLISHED,
            "published_by": actor,
            "published_at": now,
        },
    )
    Template.objects.filter(pk=version.template_id).update(
        status=Template.Status.PUBLISHED,
        current_version_id=version.pk,
        row_version=F("row_version") + 1,
    )
    _audit(
        context,
        action="labtemplate.version.publish",
        target_type="labtemplate_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={
            "status": "PUBLISHED",
            "spec_digest": version.spec_digest,
            "chapters_published": len(chapters_to_publish),
            "tasks_published": len(tasks_to_publish),
        },
    )
    _event(
        context,
        event_type=events.VERSION_PUBLISHED,
        aggregate_type="labtemplate_version",
        aggregate_ref=version.public_id,
        payload={
            "course_id": course.public_id,
            "version_id": version.public_id,
            "spec_digest": version.spec_digest,
            "execution_spec": publish_snapshot["execution_spec"],
            "execution_materials": publish_snapshot["execution_materials"],
            "execution_command": publish_snapshot["execution_command"],
                **({"execution_plans": publish_snapshot["execution_plans"]}
                   if "execution_plans" in publish_snapshot else {}),
            "execution_tests_asset": publish_snapshot["execution_tests_asset"],
        },
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def withdraw_version(
    *, course_id: str, version_id: str, actor: User, expected_version: int, context: ActorContext
) -> TemplateVersion:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        version = (
            TemplateVersion.objects.select_for_update()
            .select_related("template")
            .get(public_id=version_id, template__course=course)
        )
    except TemplateVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _expected(version.row_version, expected_version)
    if version.status != TemplateVersion.Status.PUBLISHED:
        raise TemplateStateConflict(detail={"status": version.status})
    changed = compare_and_swap(
        TemplateVersion,
        pk=version.pk,
        expected_version=expected_version,
        changes={
            "status": TemplateVersion.Status.WITHDRAWN,
            "withdrawn_by": actor,
            "withdrawn_at": timezone.now(),
        },
    )
    if version.template.current_version_id == version.pk:
        previous = (
            version.template.versions.filter(status=TemplateVersion.Status.PUBLISHED)
            .exclude(pk=version.pk)
            .order_by("-version_no")
            .first()
        )
        Template.objects.filter(pk=version.template_id).update(
            status=Template.Status.PUBLISHED if previous else Template.Status.WITHDRAWN,
            current_version=previous,
            row_version=F("row_version") + 1,
        )
    _audit(
        context,
        action="labtemplate.version.withdraw",
        target_type="labtemplate_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"status": "WITHDRAWN"},
    )
    _event(
        context,
        event_type=events.VERSION_WITHDRAWN,
        aggregate_type="labtemplate_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id, "version_id": version.public_id},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def clone_version(
    *,
    course_id: str,
    version_id: str,
    actor: User,
    expected_version: int,
    context: ActorContext,
) -> TemplateVersion:
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        source = (
            TemplateVersion.objects.select_related("template")
            .prefetch_related("auto_check_rules", "chapters__tasks")
            .get(public_id=version_id, template__course=course)
        )
    except TemplateVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _expected(source.row_version, expected_version)
    if source.status in {TemplateVersion.Status.DRAFT, TemplateVersion.Status.PRECHECKING}:
        raise TemplateStateConflict(detail={"status": source.status})
    template = Template.objects.select_for_update().get(pk=source.template_id)
    latest = template.versions.order_by("-version_no").first()
    clone = TemplateVersion.objects.create(
        template=template,
        version_no=(latest.version_no if latest else 0) + 1,
        runtime_type=source.runtime_type,
        runtime_adapter=source.runtime_adapter,
        image=source.image,
        resource_profile=source.resource_profile,
        dependencies=source.dependencies,
        # TESTS assets are owned by the source version and cannot be reused by
        # a new mutable version; the clone must choose a new scanned asset.
        execution_spec=source.execution_spec,
        network_policy=source.network_policy,
        workspace_capabilities=source.workspace_capabilities,
        material_refs=source.material_refs,
        manual_asset=source.manual_asset,
        starter_asset=source.starter_asset,
        report_template_asset=source.report_template_asset,
        report_policy=source.report_policy,
        review_policy=source.review_policy,
        retention_days=source.retention_days,
        created_by=actor,
    )
    AutoCheckRule.objects.bulk_create([
        AutoCheckRule(
            template_version=clone,
            position=rule.position,
            position_key=str(rule.position),
            checker_type=rule.checker_type,
            input_schema=rule.input_schema,
            output_schema=rule.output_schema,
            timeout_seconds=rule.timeout_seconds,
            resource_limit=rule.resource_limit,
            network_policy=rule.network_policy,
            display_policy=rule.display_policy,
            failure_semantics=rule.failure_semantics,
            rule_digest=rule.rule_digest,
        )
        for rule in source.auto_check_rules.filter(is_active=True)
    ])
    source_chapters = list(source.chapters.all().order_by("sort_order"))
    TemplateChapter.objects.bulk_create([
        TemplateChapter(
            template_version=clone,
            title=chapter.title,
            description=chapter.description,
            learning_objectives=chapter.learning_objectives,
            sort_order=chapter.sort_order,
            status=TemplateChapter.Status.DRAFT,
            resource_profile=chapter.resource_profile,
        )
        for chapter in source_chapters
    ])
    cloned_chapters = list(clone.chapters.all().order_by("sort_order"))
    chapter_map = {
        source_chapter.pk: cloned_chapter
        for source_chapter, cloned_chapter in zip(source_chapters, cloned_chapters, strict=True)
    }
    from .assessment_assets import clone_marking_spec

    TemplateTask.objects.bulk_create([
        TemplateTask(
            chapter=chapter_map[task.chapter_id],
            title=task.title,
            description=task.description,
            instructions=task.instructions,
            task_type=task.task_type,
            sort_order=task.sort_order,
            status=TemplateTask.Status.DRAFT,
            execution_spec=task.execution_spec,
            resource_profile=task.resource_profile,
            submission_policy=task.submission_policy,
            grading_policy=task.grading_policy,
            question_spec=task.question_spec,
            marking_spec=clone_marking_spec(task, clone),
            max_score=task.max_score,
        )
        for source_chapter in source_chapters
        for task in source_chapter.tasks.filter(active=True).order_by("sort_order")
    ])
    _audit(
        context,
        action="labtemplate.version.clone",
        target_type="labtemplate_version",
        target_ref=clone.public_id,
        course_ref=course.public_id,
        after={"source_version_id": source.public_id},
    )
    _event(
        context,
        event_type=events.VERSION_CLONED,
        aggregate_type="labtemplate_version",
        aggregate_ref=clone.public_id,
        payload={"course_id": course.public_id, "source_version_id": source.public_id},
    )
    return clone


def copy_templates(
    job: CourseCopyJob, source: Course, target: Course, actor: User, context: ActorContext
) -> None:
    if not job.options.get("include_templates", True):
        return
    material_map = {
        item.source_ref: item.target_ref
        for item in job.items.filter(item_type="MATERIAL_VERSION", status="SUCCEEDED")
    }
    for source_template in Template.objects.filter(course=source).select_related("current_version"):
        target_template = Template.objects.create(
            course=target,
            name=source_template.name,
            category=source_template.category,
            description=source_template.description,
            owner=actor,
        )
        CourseCopyItem.objects.create(
            job=job,
            item_type="TEMPLATE",
            source_ref=source_template.public_id,
            target_ref=target_template.public_id,
            status="SUCCEEDED",
        )
        current = source_template.current_version
        if current is None:
            continue
        refs = [
            {"version_id": material_map[ref["version_id"]], "digest_sha256": ref["digest_sha256"]}
            for ref in current.material_refs
            if ref.get("version_id") in material_map
        ]
        clone = TemplateVersion.objects.create(
            template=target_template,
            version_no=1,
            runtime_type=current.runtime_type,
            runtime_adapter=current.runtime_adapter,
            image=current.image,
            resource_profile=current.resource_profile,
            dependencies=current.dependencies,
            # Course-copy does not copy object storage bytes.  Do not retain a
            # cross-course tests_asset reference in the new draft.
            execution_spec={},
            network_policy=current.network_policy,
            workspace_capabilities=current.workspace_capabilities,
            material_refs=refs,
            manual_asset=current.manual_asset,
            starter_asset=current.starter_asset,
            report_template_asset=current.report_template_asset,
            report_policy=current.report_policy,
            review_policy=current.review_policy,
            retention_days=current.retention_days,
            created_by=actor,
        )
        for rule in current.auto_check_rules.filter(is_active=True):
            AutoCheckRule.objects.create(
                template_version=clone,
                position=rule.position,
                position_key=str(rule.position),
                checker_type=rule.checker_type,
                input_schema=rule.input_schema,
                output_schema=rule.output_schema,
                timeout_seconds=rule.timeout_seconds,
                resource_limit=rule.resource_limit,
                network_policy=rule.network_policy,
                display_policy=rule.display_policy,
                failure_semantics=rule.failure_semantics,
                rule_digest=rule.rule_digest,
            )
        from .assessment_assets import clone_marking_spec

        for chapter in current.chapters.order_by("sort_order"):
            copied_chapter = TemplateChapter.objects.create(
                template_version=clone, title=chapter.title, description=chapter.description,
                learning_objectives=chapter.learning_objectives, sort_order=chapter.sort_order,
                resource_profile=chapter.resource_profile,
            )
            for question in chapter.tasks.filter(active=True).order_by("sort_order"):
                TemplateTask.objects.create(
                    chapter=copied_chapter, title=question.title, description=question.description,
                    instructions=question.instructions, task_type=question.task_type,
                    sort_order=question.sort_order, question_spec=question.question_spec,
                    marking_spec=clone_marking_spec(question, clone), max_score=question.max_score,
                    resource_profile=question.resource_profile,
                    submission_policy=question.submission_policy,
                    grading_policy=question.grading_policy,
                )
        CourseCopyItem.objects.create(
            job=job,
            item_type="TEMPLATE_VERSION",
            source_ref=current.public_id,
            target_ref=clone.public_id,
            status="SUCCEEDED",
        )

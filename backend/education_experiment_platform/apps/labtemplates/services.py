import hashlib
import json
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from jsonschema import Draft202012Validator, SchemaError

from apps.accounts.models import User
from apps.core.audit import append_audit, append_failure, hash_client_ip
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.models import ObjectAsset
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
    TemplateDigestMismatch,
    TemplatePrecheckFailed,
    TemplateStateConflict,
    TemplateValidationError,
)
from .metrics import PRECHECK_ACTIVE, PRECHECK_DURATION, PRECHECK_RUNS
from .models import AutoCheckRule, Template, TemplatePrecheckRun, TemplateVersion

VERSION_FIELDS = {
    "runtime_type",
    "runtime_adapter_id",
    "image_id",
    "resource_profile_id",
    "dependencies",
    "network_policy",
    "workspace_capabilities",
    "material_version_ids",
    "report_policy",
    "review_policy",
    "retention_days",
}
ASSET_FIELDS = ("manual_asset", "starter_asset", "report_template_asset")


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
        resource = model.objects.filter(public_id=clean[field], **filters).first()
        if resource is None:
            raise TemplateValidationError(detail={field: "not_available"})
        clean[field] = resource.pk
    return clean


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
    try:
        item = Template.objects.create(
            course=course,
            name=name.strip(),
            category=category.strip(),
            description=description.strip(),
            owner=actor,
        )
    except IntegrityError as exc:
        raise TemplateStateConflict(detail={"name": "already_exists"}) from exc
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
        raise TemplateStateConflict(detail={"name": "already_exists"}) from exc
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
    required = {"runtime_type", "runtime_adapter_id", "image_id", "resource_profile_id"}
    if not required.issubset(clean):
        raise TemplateValidationError(detail={"required": sorted(required - clean.keys())})
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
    _expected(version.row_version, expected_version)
    if version.status != TemplateVersion.Status.DRAFT:
        raise TemplateStateConflict(detail={"status": version.status})
    clean = _version_changes(course, changes)
    changed = compare_and_swap(
        TemplateVersion, pk=version.pk, expected_version=expected_version, changes=clean
    )
    _audit(
        context,
        action="labtemplate.version.update",
        target_type="labtemplate_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        before={"row_version": version.row_version},
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
    _expected(version.row_version, expected_version)
    if version.status != TemplateVersion.Status.DRAFT:
        raise TemplateStateConflict(detail={"status": version.status})
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
        TemplateVersion, pk=version.pk, expected_version=expected_version, changes={}
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


def _validated_snapshot(
    version: TemplateVersion,
    *,
    stage: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    def report(name: str, result: str) -> None:
        if stage is not None:
            stage(name, result)

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
    if adapter.runtime_type != version.runtime_type or profile.runtime_type != version.runtime_type:
        raise TemplateValidationError(detail={"runtime_type": "resource_mismatch"})
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
            int(limits.get("cpu_millicores", 0)) > profile.cpu_millicores
            or int(limits.get("memory_mb", 0)) > profile.memory_mb
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
    report("POLICY", "PASSED")

    return {
        "runtime_type": version.runtime_type,
        "runtime_adapter": {"code": adapter.code, "driver": adapter.driver},
        "image_digest": image.digest,
        "resource_profile": {
            "code": profile.code,
            "cpu_millicores": profile.cpu_millicores,
            "memory_mb": profile.memory_mb,
            "disk_gb": profile.disk_gb,
            "network_mode": profile.network_mode,
        },
        "dependencies": version.dependencies,
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
            .prefetch_related("auto_check_rules")
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
    if compute_spec_digest(version) != version.spec_digest:
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
        after={"status": "PUBLISHED", "spec_digest": version.spec_digest},
    )
    _event(
        context,
        event_type=events.VERSION_PUBLISHED,
        aggregate_type="labtemplate_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id, "version_id": version.public_id},
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
            .prefetch_related("auto_check_rules")
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
        CourseCopyItem.objects.create(
            job=job,
            item_type="TEMPLATE_VERSION",
            source_ref=current.public_id,
            target_ref=clone.public_id,
            status="SUCCEEDED",
        )

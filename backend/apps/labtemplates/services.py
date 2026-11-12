import hashlib
import json
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

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
    ExperimentImage,
    Template,
    TemplateChapter,
    TemplatePrecheckRun,
    TemplateTask,
    TemplateVersion,
)

VERSION_FIELDS = {
    "runtime_type",
    "runtime_adapter_id",
    "image_id",
    "resource_profile_id",
    "dependencies",
    "network_policy",
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
        raise TemplateValidationError(detail={"task_type": "assessment_type_required"})
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


def _validated_snapshot(version: TemplateVersion, stage: Any = None) -> dict[str, Any]:
    from .questions import assessment_snapshot
    snapshot = assessment_snapshot(version, run_reference=stage is not None)
    if snapshot is None:
        raise TemplateValidationError(detail={"questions": "at_least_one_required"})
    if stage:
        stage("QUESTIONS", "PASSED")
    return snapshot


def compute_spec_digest(version: TemplateVersion) -> str:
    return _digest(_validated_snapshot(version))


def _draft_request_digest(version: TemplateVersion) -> str:
    return _digest({"version_id": version.public_id, "row_version": version.row_version})


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
            .prefetch_related("chapters__tasks")
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
            .prefetch_related("chapters__tasks")
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
        network_policy=source.network_policy,
        material_refs=source.material_refs,
        manual_asset=source.manual_asset,
        starter_asset=source.starter_asset,
        report_template_asset=source.report_template_asset,
        report_policy=source.report_policy,
        review_policy=source.review_policy,
        retention_days=source.retention_days,
        created_by=actor,
    )
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
            network_policy=current.network_policy,
            material_refs=refs,
            manual_asset=current.manual_asset,
            starter_asset=current.starter_asset,
            report_template_asset=current.report_template_asset,
            report_policy=current.report_policy,
            review_policy=current.review_policy,
            retention_days=current.retention_days,
            created_by=actor,
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

from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import User
from apps.core.audit import append_audit, hash_client_ip
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.courses.models import Course, CourseCopyItem, CourseCopyJob, CourseStaffGrant
from apps.courses.selectors import require_course_capability, visible_course
from apps.courses.services import ActorContext

from . import events
from .errors import (
    RubricStateConflict,
    RubricValidationError,
)
from .models import (
    Rubric,
    RubricCriterion,
    RubricVersion,
)


def _course(course_id: str, actor: User) -> Course:
    course = visible_course(actor=actor, portal="TEACHING", course_id=course_id)
    require_course_capability(
        course=course,
        actor=actor,
        capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
    )
    return course


def _audit(
    context: ActorContext,
    *,
    action: str,
    target_type: str,
    target_ref: str,
    course_ref: str,
    after: Any,
) -> None:
    append_audit(
        actor_ref=context.actor_ref,
        actor_portal=context.portal,
        actor_context={},
        action=action,
        target_type=target_type,
        target_ref=target_ref,
        course_ref=course_ref,
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


@transaction.atomic
def create_rubric(
    *, course_id: str, actor: User, name: str, description: str, context: ActorContext
) -> Rubric:
    course = _course(course_id, actor)
    try:
        rubric = Rubric.objects.create(
            course=course,
            name=name.strip(),
            description=description.strip(),
            owner=actor,
        )
    except IntegrityError as exc:
        raise RubricStateConflict(detail={"name": "already_exists"}) from exc
    _audit(
        context,
        action="rubric.create",
        target_type="rubric",
        target_ref=rubric.public_id,
        course_ref=course.public_id,
        after={"name": rubric.name},
    )
    _event(
        context,
        event_type=events.RUBRIC_CREATED,
        aggregate_type="rubric",
        aggregate_ref=rubric.public_id,
        payload={"course_id": course.public_id},
    )
    return rubric


def _criteria_payload(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positions = [int(item.get("position", 0)) for item in criteria]
    if (
        not criteria
        or any(position < 1 for position in positions)
        or len(positions) != len(set(positions))
    ):
        raise RubricValidationError(detail={"position": "unique_positive_required"})
    result: list[dict[str, Any]] = []
    for item in criteria:
        max_score = Decimal(str(item.get("max_score", 0)))
        weight = int(item.get("weight_basis_points", 0))
        title = str(item.get("title", "")).strip()
        if not title or max_score <= 0 or not 1 <= weight <= 10000:
            raise RubricValidationError(detail={"criterion": "positive_score_and_weight_required"})
        result.append({
            "position": int(item["position"]),
            "position_key": str(item["position"]),
            "title": title,
            "description": str(item.get("description", "")).strip(),
            "guidance": str(item.get("guidance", "")).strip(),
            "max_score": max_score,
            "weight_basis_points": weight,
        })
    return result


@transaction.atomic
def create_rubric_version(
    *,
    course_id: str,
    rubric_id: str,
    actor: User,
    title: str,
    description: str,
    total_score: Decimal,
    criteria: list[dict[str, Any]],
    context: ActorContext,
) -> RubricVersion:
    course = _course(course_id, actor)
    try:
        rubric = Rubric.objects.select_for_update().get(public_id=rubric_id, course=course)
    except Rubric.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    latest = rubric.versions.order_by("-version_no").first()
    version = RubricVersion.objects.create(
        rubric=rubric,
        version_no=(latest.version_no if latest else 0) + 1,
        title=title.strip(),
        description=description.strip(),
        total_score=total_score,
        created_by=actor,
    )
    RubricCriterion.objects.bulk_create([
        RubricCriterion(rubric_version=version, **item) for item in _criteria_payload(criteria)
    ])
    _audit(
        context,
        action="rubric.version.create",
        target_type="rubric_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"version_no": version.version_no},
    )
    _event(
        context,
        event_type=events.RUBRIC_VERSION_CREATED,
        aggregate_type="rubric_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id, "rubric_id": rubric.public_id},
    )
    return version


@transaction.atomic
def clone_rubric_version(
    *,
    course_id: str,
    rubric_id: str,
    source_version_id: str,
    actor: User,
    context: ActorContext,
) -> RubricVersion:
    course = _course(course_id, actor)
    try:
        rubric = Rubric.objects.select_for_update().get(public_id=rubric_id, course=course)
        source = (
            RubricVersion.objects.select_related("rubric")
            .prefetch_related("criteria")
            .get(public_id=source_version_id, rubric=rubric)
        )
    except (Rubric.DoesNotExist, RubricVersion.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    latest = rubric.versions.order_by("-version_no").first()
    version = RubricVersion.objects.create(
        rubric=rubric,
        version_no=(latest.version_no if latest else 0) + 1,
        title=source.title,
        description=source.description,
        total_score=source.total_score,
        created_by=actor,
    )
    RubricCriterion.objects.bulk_create([
        RubricCriterion(
            rubric_version=version,
            position=item.position,
            position_key=str(item.position),
            title=item.title,
            description=item.description,
            guidance=item.guidance,
            max_score=item.max_score,
            weight_basis_points=item.weight_basis_points,
        )
        for item in source.criteria.filter(is_active=True)
    ])
    _audit(
        context,
        action="rubric.version.clone",
        target_type="rubric_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"source_version_id": source.public_id, "version_no": version.version_no},
    )
    _event(
        context,
        event_type=events.RUBRIC_VERSION_CREATED,
        aggregate_type="rubric_version",
        aggregate_ref=version.public_id,
        payload={
            "course_id": course.public_id,
            "rubric_id": rubric.public_id,
            "source_version_id": source.public_id,
        },
    )
    return version


@transaction.atomic
def update_rubric_version(
    *,
    course_id: str,
    version_id: str,
    actor: User,
    expected_version: int,
    title: str,
    description: str,
    total_score: Decimal,
    criteria: list[dict[str, Any]],
    context: ActorContext,
) -> RubricVersion:
    course = _course(course_id, actor)
    try:
        version = RubricVersion.objects.select_for_update().get(
            public_id=version_id, rubric__course=course
        )
    except RubricVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _expected(version.row_version, expected_version)
    if version.status != RubricVersion.Status.DRAFT:
        raise RubricStateConflict(detail={"status": version.status})
    payload = _criteria_payload(criteria)
    for criterion in RubricCriterion.objects.select_for_update().filter(
        rubric_version=version, is_active=True
    ):
        compare_and_swap(
            RubricCriterion,
            pk=criterion.pk,
            expected_version=criterion.row_version,
            changes={
                "is_active": False,
                "position_key": f"removed:{criterion.public_id}",
            },
        )
    RubricCriterion.objects.bulk_create([
        RubricCriterion(rubric_version=version, **item) for item in payload
    ])
    changed = compare_and_swap(
        RubricVersion,
        pk=version.pk,
        expected_version=expected_version,
        changes={
            "title": title.strip(),
            "description": description.strip(),
            "total_score": total_score,
        },
    )
    _audit(
        context,
        action="rubric.version.update",
        target_type="rubric_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"criteria_count": len(payload)},
    )
    _event(
        context,
        event_type=events.RUBRIC_VERSION_UPDATED,
        aggregate_type="rubric_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def publish_rubric_version(
    *, course_id: str, version_id: str, actor: User, expected_version: int, context: ActorContext
) -> RubricVersion:
    course = _course(course_id, actor)
    try:
        version = (
            RubricVersion.objects.select_for_update()
            .select_related("rubric")
            .prefetch_related("criteria")
            .get(public_id=version_id, rubric__course=course)
        )
    except RubricVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _expected(version.row_version, expected_version)
    if version.status != RubricVersion.Status.DRAFT:
        raise RubricStateConflict(detail={"status": version.status})
    criteria = list(version.criteria.filter(is_active=True))
    if not criteria or sum(item.weight_basis_points for item in criteria) != 10000:
        raise RubricValidationError(detail={"weight_basis_points": "must_total_10000"})
    if sum((item.max_score for item in criteria), Decimal("0")) != version.total_score:
        raise RubricValidationError(detail={"total_score": "criterion_sum_mismatch"})
    changed = compare_and_swap(
        RubricVersion,
        pk=version.pk,
        expected_version=expected_version,
        changes={
            "status": RubricVersion.Status.PUBLISHED,
            "published_by": actor,
            "published_at": timezone.now(),
        },
    )
    Rubric.objects.filter(pk=version.rubric_id).update(
        status=Rubric.Status.PUBLISHED,
        current_version_id=version.pk,
        row_version=F("row_version") + 1,
    )
    _audit(
        context,
        action="rubric.version.publish",
        target_type="rubric_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"status": "PUBLISHED"},
    )
    _event(
        context,
        event_type=events.RUBRIC_VERSION_PUBLISHED,
        aggregate_type="rubric_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id},
    )
    return changed  # type: ignore[return-value]


def copy_rubrics(
    job: CourseCopyJob, source: Course, target: Course, actor: User, context: ActorContext
) -> None:
    if not job.options.get("include_rubrics", True):
        return
    for source_rubric in Rubric.objects.filter(course=source).select_related("current_version"):
        target_rubric = Rubric.objects.create(
            course=target,
            name=source_rubric.name,
            description=source_rubric.description,
            owner=actor,
        )
        CourseCopyItem.objects.create(
            job=job,
            item_type="RUBRIC",
            source_ref=source_rubric.public_id,
            target_ref=target_rubric.public_id,
            status="SUCCEEDED",
        )
        current = source_rubric.current_version
        if current is None:
            continue
        clone = RubricVersion.objects.create(
            rubric=target_rubric,
            version_no=1,
            title=current.title,
            description=current.description,
            total_score=current.total_score,
            created_by=actor,
        )
        RubricCriterion.objects.bulk_create([
            RubricCriterion(
                rubric_version=clone,
                position=item.position,
                position_key=str(item.position),
                title=item.title,
                description=item.description,
                guidance=item.guidance,
                max_score=item.max_score,
                weight_basis_points=item.weight_basis_points,
            )
            for item in current.criteria.filter(is_active=True)
        ])
        CourseCopyItem.objects.create(
            job=job,
            item_type="RUBRIC_VERSION",
            source_ref=current.public_id,
            target_ref=clone.public_id,
            status="SUCCEEDED",
        )

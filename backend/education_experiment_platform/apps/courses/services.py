from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.accounts.models import TeacherQualification, User
from apps.core.audit import append_audit, hash_client_ip
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit

from . import events
from .errors import (
    CourseStateConflict,
    EnrollmentAlreadyLive,
    EnrollmentBlocked,
    EnrollmentCapacityFull,
    EnrollmentStateConflict,
)
from .metrics import COURSE_ENROLLMENT_DECISIONS_TOTAL
from .models import (
    Course,
    CourseStaff,
    CourseStaffEvent,
    CourseStaffGrant,
    CourseStaffGrantEvent,
    Enrollment,
    EnrollmentEvent,
)
from .ports import Blocker, course_archive_blockers, enrollment_blockers
from .selectors import require_course_capability, require_owner


@dataclass(frozen=True)
class ActorContext:
    actor_ref: str
    portal: str
    trace_id: str
    client_ip: str = ""
    user_agent: str = ""


def _audit(
    context: ActorContext,
    *,
    action: str,
    target_type: str,
    target_ref: str,
    course_ref: str,
    before: Any = None,
    after: Any = None,
    result: str = "SUCCEEDED",
    error_code: str = "",
) -> None:
    append_audit(
        actor_ref=context.actor_ref,
        actor_portal=context.portal,
        actor_context={},
        action=action,
        course_ref=course_ref,
        target_type=target_type,
        target_ref=target_ref,
        before=before,
        after=after,
        result=result,
        error_code=error_code,
        client_ip_hash=hash_client_ip(context.client_ip, salt=settings.AUDIT_IP_HASH_SALT),
        user_agent_summary=context.user_agent,
        trace_id=context.trace_id,
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


def _active_teacher(user: User) -> None:
    if user.account_status != User.AccountStatus.ACTIVE:
        raise CourseStateConflict(detail={"account_status": user.account_status})
    if not TeacherQualification.objects.filter(
        user=user,
        status=TeacherQualification.Status.ACTIVE,
    ).exists():
        raise CourseStateConflict(detail={"teacher_qualification": "ACTIVE_REQUIRED"})


def _ensure_expected(actual: int, expected: int) -> None:
    if actual != expected:
        raise RowVersionConflict(
            detail={"expected_row_version": expected, "actual_row_version": actual}
        )


def _staff_event(
    *,
    staff: CourseStaff,
    from_role: str,
    from_status: str,
    actor: User,
    reason: str,
    context: ActorContext,
) -> None:
    CourseStaffEvent.objects.create(
        staff=staff,
        course=staff.course,
        from_role=from_role,
        to_role=staff.role,
        from_status=from_status,
        to_status=staff.status,
        actor=actor,
        reason=reason.strip(),
        trace_id=context.trace_id,
    )


def _grant_event(
    *,
    grant: CourseStaffGrant,
    from_status: str,
    actor: User,
    reason: str,
    context: ActorContext,
) -> None:
    CourseStaffGrantEvent.objects.create(
        grant=grant,
        course=grant.course_staff.course,
        from_status=from_status,
        to_status=grant.status,
        actor=actor,
        reason=reason.strip(),
        trace_id=context.trace_id,
    )


def _enrollment_event(
    *,
    enrollment: Enrollment,
    from_status: str,
    reason_code: str,
    actor: User,
    blockers: list[Blocker],
    context: ActorContext,
) -> None:
    EnrollmentEvent.objects.create(
        enrollment=enrollment,
        course=enrollment.course,
        from_status=from_status,
        to_status=enrollment.status,
        actor=actor,
        reason_code=reason_code,
        blockers_snapshot=[item.as_dict() for item in blockers],
        trace_id=context.trace_id,
    )


@transaction.atomic
def create_course(
    *,
    actor: User,
    code: str,
    title: str,
    summary: str,
    description: str,
    visibility: str,
    enrollment_mode: str,
    capacity: int | None,
    enrollment_start: Any,
    enrollment_end: Any,
    teaching_start: Any,
    teaching_end: Any,
    context: ActorContext,
) -> Course:
    actor = User.objects.select_for_update().get(pk=actor.pk)
    _active_teacher(actor)
    try:
        course = Course.objects.create(
            code=code.strip().upper(),
            title=title.strip(),
            summary=summary.strip(),
            description=description.strip(),
            owner=actor,
            visibility=visibility,
            enrollment_mode=enrollment_mode,
            capacity=capacity,
            enrollment_start=enrollment_start,
            enrollment_end=enrollment_end,
            teaching_start=teaching_start,
            teaching_end=teaching_end,
        )
    except IntegrityError as exc:
        raise CourseStateConflict(detail={"code": code.strip().upper()}) from exc
    owner = CourseStaff.objects.create(
        course=course,
        user=actor,
        role=CourseStaff.Role.OWNER,
        status=CourseStaff.Status.ACTIVE,
        appointed_by=actor,
        appointed_at=timezone.now(),
    )
    _staff_event(
        staff=owner,
        from_role="",
        from_status="",
        actor=actor,
        reason="course created",
        context=context,
    )
    _audit(
        context,
        action="course.create",
        target_type="course",
        target_ref=course.public_id,
        course_ref=course.public_id,
        after={"code": course.code, "status": course.status, "owner": actor.public_id},
    )
    _event(
        context,
        event_type=events.COURSE_CREATED,
        aggregate_type="course",
        aggregate_ref=course.public_id,
        payload={"course_id": course.public_id, "status": course.status},
    )
    return course


@transaction.atomic
def update_course(
    *,
    course_id: str,
    actor: User,
    expected_version: int,
    changes: dict[str, Any],
    context: ActorContext,
) -> Course:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    require_owner(course=course, actor=actor)
    if course.status not in {Course.Status.DRAFT, Course.Status.PUBLISHED}:
        raise CourseStateConflict(detail={"status": course.status})
    allowed = {
        "title",
        "summary",
        "description",
        "visibility",
        "enrollment_mode",
        "capacity",
        "enrollment_start",
        "enrollment_end",
        "teaching_start",
        "teaching_end",
    }
    clean = {key: value for key, value in changes.items() if key in allowed}
    changed = compare_and_swap(
        Course,
        pk=course.pk,
        expected_version=expected_version,
        changes=clean,
    )
    _audit(
        context,
        action="course.update",
        target_type="course",
        target_ref=course.public_id,
        course_ref=course.public_id,
        before={key: getattr(course, key) for key in clean},
        after={key: getattr(changed, key) for key in clean},
    )
    return changed  # type: ignore[return-value]


def _transition_course(
    *,
    course_id: str,
    actor: User,
    expected_version: int,
    from_status: str,
    to_status: str,
    timestamp_field: str,
    event_type: str,
    context: ActorContext,
) -> Course:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    require_owner(course=course, actor=actor)
    if course.status != from_status:
        raise CourseStateConflict(detail={"status": course.status})
    changed = compare_and_swap(
        Course,
        pk=course.pk,
        expected_version=expected_version,
        changes={"status": to_status, timestamp_field: timezone.now()},
    )
    _audit(
        context,
        action=f"course.{to_status.casefold()}",
        target_type="course",
        target_ref=course.public_id,
        course_ref=course.public_id,
        before={"status": course.status},
        after={"status": to_status},
    )
    _event(
        context,
        event_type=event_type,
        aggregate_type="course",
        aggregate_ref=course.public_id,
        payload={"course_id": course.public_id, "status": to_status},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def publish_course(**kwargs: Any) -> Course:
    return _transition_course(
        **kwargs,
        from_status=Course.Status.DRAFT,
        to_status=Course.Status.PUBLISHED,
        timestamp_field="published_at",
        event_type=events.COURSE_PUBLISHED,
    )


@transaction.atomic
def close_course(**kwargs: Any) -> Course:
    return _transition_course(
        **kwargs,
        from_status=Course.Status.PUBLISHED,
        to_status=Course.Status.CLOSED,
        timestamp_field="closed_at",
        event_type=events.COURSE_CLOSED,
    )


def archive_check(*, course: Course) -> list[Blocker]:
    blockers = []
    if course.status != Course.Status.CLOSED:
        blockers.append(
            Blocker(
                type="COURSE_NOT_CLOSED",
                count=1,
                refs=(course.public_id,),
                message="课程必须先关闭",
            )
        )
    blockers.extend(course_archive_blockers(course))
    return blockers


@transaction.atomic
def archive_course(
    *, course_id: str, actor: User, expected_version: int, context: ActorContext
) -> Course:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    require_owner(course=course, actor=actor)
    blockers = archive_check(course=course)
    if blockers:
        raise CourseStateConflict(detail={"blockers": [item.as_dict() for item in blockers]})
    return _transition_course(
        course_id=course_id,
        actor=actor,
        expected_version=expected_version,
        from_status=Course.Status.CLOSED,
        to_status=Course.Status.ARCHIVED,
        timestamp_field="archived_at",
        event_type=events.COURSE_ARCHIVED,
        context=context,
    )


@transaction.atomic
def transfer_course_ownership(
    *,
    course_id: str,
    new_owner_id: str,
    actor: User,
    expected_version: int,
    reason: str,
    context: ActorContext,
) -> Course:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    current_staff = require_owner(course=course, actor=actor)
    try:
        new_owner = User.objects.select_for_update().get(public_id=new_owner_id)
    except User.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if new_owner.pk == actor.pk:
        raise CourseStateConflict(detail={"owner_id": new_owner_id})
    _active_teacher(new_owner)
    _ensure_expected(course.row_version, expected_version)
    now = timezone.now()
    old_staff = compare_and_swap(
        CourseStaff,
        pk=current_staff.pk,
        expected_version=current_staff.row_version,
        changes={
            "status": CourseStaff.Status.REVOKED,
            "revoked_by": actor,
            "revoked_at": now,
        },
    )
    _staff_event(
        staff=old_staff,
        from_role=current_staff.role,
        from_status=current_staff.status,
        actor=actor,
        reason=reason,
        context=context,
    )
    target_staff = (
        CourseStaff.objects.select_for_update()
        .filter(
            course=course,
            user=new_owner,
        )
        .first()
    )
    if target_staff is None:
        target_staff = CourseStaff.objects.create(
            course=course,
            user=new_owner,
            role=CourseStaff.Role.OWNER,
            status=CourseStaff.Status.ACTIVE,
            appointed_by=actor,
            appointed_at=now,
        )
        previous_role = ""
        previous_status = ""
    else:
        previous_role = target_staff.role
        previous_status = target_staff.status
        target_staff = compare_and_swap(
            CourseStaff,
            pk=target_staff.pk,
            expected_version=target_staff.row_version,
            changes={
                "role": CourseStaff.Role.OWNER,
                "status": CourseStaff.Status.ACTIVE,
                "appointed_by": actor,
                "appointed_at": now,
                "revoked_by": None,
                "revoked_at": None,
            },
        )
    _staff_event(
        staff=target_staff,
        from_role=previous_role,
        from_status=previous_status,
        actor=actor,
        reason=reason,
        context=context,
    )
    changed = compare_and_swap(
        Course,
        pk=course.pk,
        expected_version=expected_version,
        changes={"owner": new_owner},
    )
    _audit(
        context,
        action="course.owner.transfer",
        target_type="course",
        target_ref=course.public_id,
        course_ref=course.public_id,
        before={"owner_id": actor.public_id},
        after={"owner_id": new_owner.public_id, "reason": reason},
    )
    _event(
        context,
        event_type=events.COURSE_STAFF_CHANGED,
        aggregate_type="course",
        aggregate_ref=course.public_id,
        payload={"course_id": course.public_id, "owner_id": new_owner.public_id},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def appoint_course_assistant(
    *, course_id: str, user_id: str, actor: User, reason: str, context: ActorContext
) -> CourseStaff:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        user = User.objects.select_for_update().get(public_id=user_id)
    except (Course.DoesNotExist, User.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_owner(course=course, actor=actor)
    _active_teacher(user)
    if user.pk == course.owner_id:
        raise CourseStateConflict(detail={"user_id": user_id})
    now = timezone.now()
    staff = CourseStaff.objects.select_for_update().filter(course=course, user=user).first()
    if staff is None:
        staff = CourseStaff.objects.create(
            course=course,
            user=user,
            role=CourseStaff.Role.ASSISTANT,
            status=CourseStaff.Status.ACTIVE,
            appointed_by=actor,
            appointed_at=now,
        )
        previous_status = ""
        previous_role = ""
    else:
        if staff.status == CourseStaff.Status.ACTIVE:
            raise CourseStateConflict(detail={"staff_status": staff.status})
        previous_status = staff.status
        previous_role = staff.role
        staff = compare_and_swap(
            CourseStaff,
            pk=staff.pk,
            expected_version=staff.row_version,
            changes={
                "role": CourseStaff.Role.ASSISTANT,
                "status": CourseStaff.Status.ACTIVE,
                "appointed_by": actor,
                "appointed_at": now,
                "revoked_by": None,
                "revoked_at": None,
            },
        )
    _staff_event(
        staff=staff,
        from_role=previous_role,
        from_status=previous_status,
        actor=actor,
        reason=reason,
        context=context,
    )
    _audit(
        context,
        action="course.staff.appoint",
        target_type="course_staff",
        target_ref=staff.public_id,
        course_ref=course.public_id,
        after={"user_id": user.public_id, "role": staff.role, "status": staff.status},
    )
    _event(
        context,
        event_type=events.COURSE_STAFF_CHANGED,
        aggregate_type="course",
        aggregate_ref=course.public_id,
        payload={"course_id": course.public_id, "staff_id": staff.public_id},
    )
    return staff  # type: ignore[return-value]


@transaction.atomic
def grant_course_capability(
    *,
    course_id: str,
    staff_id: str,
    capability: str,
    expires_at: Any,
    actor: User,
    reason: str,
    context: ActorContext,
) -> CourseStaffGrant:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        staff = CourseStaff.objects.select_for_update().get(
            public_id=staff_id,
            course=course,
        )
    except (Course.DoesNotExist, CourseStaff.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_owner(course=course, actor=actor)
    if staff.role != CourseStaff.Role.ASSISTANT or staff.status != CourseStaff.Status.ACTIVE:
        raise CourseStateConflict(detail={"staff_status": staff.status, "role": staff.role})
    if capability not in CourseStaffGrant.Capability.values:
        raise CourseStateConflict(detail={"capability": capability})
    grant = (
        CourseStaffGrant.objects.select_for_update()
        .filter(
            course_staff=staff,
            capability=capability,
        )
        .first()
    )
    now = timezone.now()
    if grant is None:
        grant = CourseStaffGrant.objects.create(
            course_staff=staff,
            capability=capability,
            status=CourseStaffGrant.Status.ACTIVE,
            expires_at=expires_at,
            granted_by=actor,
            granted_at=now,
        )
        previous = ""
    else:
        if grant.status == CourseStaffGrant.Status.ACTIVE:
            raise CourseStateConflict(detail={"grant_status": grant.status})
        previous = grant.status
        grant = compare_and_swap(
            CourseStaffGrant,
            pk=grant.pk,
            expected_version=grant.row_version,
            changes={
                "status": CourseStaffGrant.Status.ACTIVE,
                "expires_at": expires_at,
                "granted_by": actor,
                "granted_at": now,
                "revoked_by": None,
                "revoked_at": None,
            },
        )
    _grant_event(
        grant=grant,
        from_status=previous,
        actor=actor,
        reason=reason,
        context=context,
    )
    _audit(
        context,
        action="course.grant.create",
        target_type="course_staff_grant",
        target_ref=grant.public_id,
        course_ref=course.public_id,
        after={"capability": capability, "status": grant.status},
    )
    return grant  # type: ignore[return-value]


@transaction.atomic
def revoke_course_capability(
    *,
    course_id: str,
    staff_id: str,
    grant_id: str,
    actor: User,
    expected_version: int,
    reason: str,
    context: ActorContext,
) -> CourseStaffGrant:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        grant = (
            CourseStaffGrant.objects.select_for_update()
            .select_related("course_staff__course")
            .get(
                public_id=grant_id,
                course_staff__public_id=staff_id,
                course_staff__course=course,
            )
        )
    except (Course.DoesNotExist, CourseStaffGrant.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_owner(course=course, actor=actor)
    if grant.status != CourseStaffGrant.Status.ACTIVE:
        raise CourseStateConflict(detail={"grant_status": grant.status})
    changed = compare_and_swap(
        CourseStaffGrant,
        pk=grant.pk,
        expected_version=expected_version,
        changes={
            "status": CourseStaffGrant.Status.REVOKED,
            "revoked_by": actor,
            "revoked_at": timezone.now(),
        },
    )
    _grant_event(
        grant=changed,
        from_status=grant.status,
        actor=actor,
        reason=reason,
        context=context,
    )
    _audit(
        context,
        action="course.grant.revoke",
        target_type="course_staff_grant",
        target_ref=grant.public_id,
        course_ref=course.public_id,
        before={"status": grant.status},
        after={"status": changed.status, "reason": reason},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def revoke_course_staff(
    *,
    course_id: str,
    staff_id: str,
    actor: User,
    expected_version: int,
    reason: str,
    context: ActorContext,
) -> CourseStaff:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        staff = CourseStaff.objects.select_for_update().get(public_id=staff_id, course=course)
    except (Course.DoesNotExist, CourseStaff.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_owner(course=course, actor=actor)
    if staff.role == CourseStaff.Role.OWNER or staff.status != CourseStaff.Status.ACTIVE:
        raise CourseStateConflict(detail={"role": staff.role, "status": staff.status})
    now = timezone.now()
    for grant in CourseStaffGrant.objects.select_for_update().filter(
        course_staff=staff,
        status=CourseStaffGrant.Status.ACTIVE,
    ):
        revoked = compare_and_swap(
            CourseStaffGrant,
            pk=grant.pk,
            expected_version=grant.row_version,
            changes={
                "status": CourseStaffGrant.Status.REVOKED,
                "revoked_by": actor,
                "revoked_at": now,
            },
        )
        _grant_event(
            grant=revoked,
            from_status=grant.status,
            actor=actor,
            reason=reason,
            context=context,
        )
    changed = compare_and_swap(
        CourseStaff,
        pk=staff.pk,
        expected_version=expected_version,
        changes={
            "status": CourseStaff.Status.REVOKED,
            "revoked_by": actor,
            "revoked_at": now,
        },
    )
    _staff_event(
        staff=changed,
        from_role=staff.role,
        from_status=staff.status,
        actor=actor,
        reason=reason,
        context=context,
    )
    _audit(
        context,
        action="course.staff.revoke",
        target_type="course_staff",
        target_ref=staff.public_id,
        course_ref=course.public_id,
        before={"status": staff.status},
        after={"status": changed.status, "reason": reason},
    )
    _event(
        context,
        event_type=events.COURSE_STAFF_CHANGED,
        aggregate_type="course",
        aggregate_ref=course.public_id,
        payload={"course_id": course.public_id, "staff_id": staff.public_id},
    )
    return changed  # type: ignore[return-value]


def _enrollment_window_open(course: Course) -> bool:
    now = timezone.now()
    return (
        course.status == Course.Status.PUBLISHED
        and (course.enrollment_start is None or course.enrollment_start <= now)
        and (course.enrollment_end is None or course.enrollment_end >= now)
    )


def prerequisite_blockers(*, course: Course, student: User) -> list[dict[str, object]]:
    # P03-B replaces this empty relation set with persisted prerequisite evaluation.
    return []


def _ensure_capacity(course: Course) -> None:
    if course.capacity is None:
        return
    active = Enrollment.objects.filter(
        course=course,
        status=Enrollment.Status.ACTIVE,
    ).count()
    if active >= course.capacity:
        COURSE_ENROLLMENT_DECISIONS_TOTAL.labels(
            mode=course.enrollment_mode,
            result="capacity_full",
        ).inc()
        raise EnrollmentCapacityFull(detail={"course_id": course.public_id})


@transaction.atomic
def apply_for_course(
    *,
    course_id: str,
    student: User,
    application_message: str,
    context: ActorContext,
    invitation_code: str = "",
) -> Enrollment:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    student = User.objects.select_for_update().get(pk=student.pk)
    if student.account_status != User.AccountStatus.ACTIVE or not _enrollment_window_open(course):
        raise CourseStateConflict(detail={"status": course.status})
    blockers = prerequisite_blockers(course=course, student=student)
    if blockers:
        from .errors import PrerequisiteNotSatisfied

        raise PrerequisiteNotSatisfied(detail={"blockers": blockers})
    if invitation_code:
        from .content_services import consume_invitation

        consume_invitation(course=course, code=invitation_code)
    existing = (
        Enrollment.objects.select_for_update()
        .filter(
            course=course,
            student=student,
            status__in=(Enrollment.Status.PENDING, Enrollment.Status.ACTIVE),
        )
        .first()
    )
    if existing is not None:
        raise EnrollmentAlreadyLive(detail={"enrollment_id": existing.public_id})
    cycle_no = (
        Enrollment.objects.filter(course=course, student=student).aggregate(value=Max("cycle_no"))[
            "value"
        ]
        or 0
    ) + 1
    status = (
        Enrollment.Status.ACTIVE
        if course.enrollment_mode == Course.EnrollmentMode.OPEN
        else Enrollment.Status.PENDING
    )
    if status == Enrollment.Status.ACTIVE:
        _ensure_capacity(course)
    now = timezone.now()
    try:
        enrollment = Enrollment.objects.create(
            course=course,
            student=student,
            cycle_no=cycle_no,
            status=status,
            application_message=application_message.strip(),
            applied_at=now,
            activated_at=now if status == Enrollment.Status.ACTIVE else None,
        )
    except IntegrityError as exc:
        raise EnrollmentAlreadyLive() from exc
    reason = "OPEN_ENROLLMENT" if status == Enrollment.Status.ACTIVE else "APPLICATION_SUBMITTED"
    _enrollment_event(
        enrollment=enrollment,
        from_status="",
        reason_code=reason,
        actor=student,
        blockers=[],
        context=context,
    )
    _audit(
        context,
        action="enrollment.apply",
        target_type="enrollment",
        target_ref=enrollment.public_id,
        course_ref=course.public_id,
        after={"status": status, "cycle_no": cycle_no},
    )
    event_type = (
        events.ENROLLMENT_ACTIVATED
        if status == Enrollment.Status.ACTIVE
        else events.ENROLLMENT_APPLIED
    )
    _event(
        context,
        event_type=event_type,
        aggregate_type="enrollment",
        aggregate_ref=enrollment.public_id,
        payload={
            "enrollment_id": enrollment.public_id,
            "course_id": course.public_id,
            "student_id": student.public_id,
            "status": status,
        },
    )
    COURSE_ENROLLMENT_DECISIONS_TOTAL.labels(mode=course.enrollment_mode, result=status).inc()
    return enrollment


@transaction.atomic
def withdraw_application(
    *,
    enrollment_id: str,
    student: User,
    expected_version: int,
    context: ActorContext,
) -> Enrollment:
    try:
        enrollment = (
            Enrollment.objects.select_for_update()
            .select_related("course")
            .get(
                public_id=enrollment_id,
                student=student,
            )
        )
    except Enrollment.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if enrollment.status != Enrollment.Status.PENDING:
        raise EnrollmentStateConflict(detail={"status": enrollment.status})
    changed = compare_and_swap(
        Enrollment,
        pk=enrollment.pk,
        expected_version=expected_version,
        changes={"status": Enrollment.Status.WITHDRAWN, "ended_at": timezone.now()},
    )
    _enrollment_event(
        enrollment=changed,
        from_status=enrollment.status,
        reason_code="APPLICATION_WITHDRAWN",
        actor=student,
        blockers=[],
        context=context,
    )
    _record_enrollment_end(enrollment, changed, student, "enrollment.withdraw", context)
    return changed  # type: ignore[return-value]


@transaction.atomic
def review_enrollment(
    *,
    course_id: str,
    enrollment_id: str,
    decision: str,
    note: str,
    actor: User,
    expected_version: int,
    context: ActorContext,
) -> Enrollment:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        enrollment = (
            Enrollment.objects.select_for_update()
            .select_related("student")
            .get(
                public_id=enrollment_id,
                course=course,
            )
        )
    except (Course.DoesNotExist, Enrollment.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course,
        actor=actor,
        capability=CourseStaffGrant.Capability.MANAGE_ENROLLMENT,
    )
    if enrollment.status != Enrollment.Status.PENDING:
        raise EnrollmentStateConflict(detail={"status": enrollment.status})
    if decision not in {"APPROVE", "REJECT"}:
        raise EnrollmentStateConflict(detail={"decision": decision})
    next_status = Enrollment.Status.ACTIVE if decision == "APPROVE" else Enrollment.Status.REJECTED
    if next_status == Enrollment.Status.ACTIVE:
        _ensure_capacity(course)
        blockers = prerequisite_blockers(course=course, student=enrollment.student)
        if blockers:
            from .errors import PrerequisiteNotSatisfied

            raise PrerequisiteNotSatisfied(detail={"blockers": blockers})
    now = timezone.now()
    changed = compare_and_swap(
        Enrollment,
        pk=enrollment.pk,
        expected_version=expected_version,
        changes={
            "status": next_status,
            "reviewed_by": actor,
            "reviewed_at": now,
            "activated_at": now if next_status == Enrollment.Status.ACTIVE else None,
            "ended_at": now if next_status == Enrollment.Status.REJECTED else None,
            "decision_note": note.strip(),
        },
    )
    _enrollment_event(
        enrollment=changed,
        from_status=enrollment.status,
        reason_code=f"APPLICATION_{decision}",
        actor=actor,
        blockers=[],
        context=context,
    )
    _audit(
        context,
        action="enrollment.review",
        target_type="enrollment",
        target_ref=enrollment.public_id,
        course_ref=course.public_id,
        before={"status": enrollment.status},
        after={"status": next_status, "decision": decision, "note": note},
    )
    _event(
        context,
        event_type=(
            events.ENROLLMENT_ACTIVATED
            if next_status == Enrollment.Status.ACTIVE
            else events.ENROLLMENT_REJECTED
        ),
        aggregate_type="enrollment",
        aggregate_ref=enrollment.public_id,
        payload={
            "enrollment_id": enrollment.public_id,
            "course_id": course.public_id,
            "student_id": enrollment.student.public_id,
            "status": next_status,
        },
    )
    COURSE_ENROLLMENT_DECISIONS_TOTAL.labels(
        mode=course.enrollment_mode,
        result=next_status,
    ).inc()
    return changed  # type: ignore[return-value]


def enrollment_exit_check(*, enrollment: Enrollment) -> list[Blocker]:
    if enrollment.status != Enrollment.Status.ACTIVE:
        return [
            Blocker(
                type="ENROLLMENT_NOT_ACTIVE",
                count=1,
                refs=(enrollment.public_id,),
                message="选课周期不是有效状态",
            )
        ]
    return enrollment_blockers(enrollment)


def _record_enrollment_end(
    before: Enrollment,
    changed: Enrollment,
    actor: User,
    action: str,
    context: ActorContext,
) -> None:
    _audit(
        context,
        action=action,
        target_type="enrollment",
        target_ref=before.public_id,
        course_ref=before.course.public_id,
        before={"status": before.status},
        after={"status": changed.status, "reason": changed.end_reason},
    )
    _event(
        context,
        event_type=events.ENROLLMENT_ENDED,
        aggregate_type="enrollment",
        aggregate_ref=before.public_id,
        payload={
            "enrollment_id": before.public_id,
            "course_id": before.course.public_id,
            "student_id": before.student.public_id,
            "status": changed.status,
        },
    )


@transaction.atomic
def drop_enrollment(
    *,
    enrollment_id: str,
    student: User,
    expected_version: int,
    reason: str,
    context: ActorContext,
) -> Enrollment:
    try:
        enrollment = (
            Enrollment.objects.select_for_update()
            .select_related("course", "student")
            .get(public_id=enrollment_id, student=student)
        )
    except Enrollment.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    blockers = enrollment_exit_check(enrollment=enrollment)
    if blockers:
        raise EnrollmentBlocked(detail={"blockers": [item.as_dict() for item in blockers]})
    changed = compare_and_swap(
        Enrollment,
        pk=enrollment.pk,
        expected_version=expected_version,
        changes={
            "status": Enrollment.Status.DROPPED,
            "ended_at": timezone.now(),
            "end_reason": reason.strip(),
        },
    )
    _enrollment_event(
        enrollment=changed,
        from_status=enrollment.status,
        reason_code="STUDENT_DROPPED",
        actor=student,
        blockers=blockers,
        context=context,
    )
    _record_enrollment_end(enrollment, changed, student, "enrollment.drop", context)
    return changed  # type: ignore[return-value]


@transaction.atomic
def remove_enrollment(
    *,
    course_id: str,
    enrollment_id: str,
    actor: User,
    expected_version: int,
    reason: str,
    context: ActorContext,
) -> Enrollment:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        enrollment = (
            Enrollment.objects.select_for_update()
            .select_related("course", "student")
            .get(public_id=enrollment_id, course=course)
        )
    except (Course.DoesNotExist, Enrollment.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course,
        actor=actor,
        capability=CourseStaffGrant.Capability.MANAGE_ENROLLMENT,
    )
    blockers = enrollment_exit_check(enrollment=enrollment)
    if blockers:
        raise EnrollmentBlocked(detail={"blockers": [item.as_dict() for item in blockers]})
    changed = compare_and_swap(
        Enrollment,
        pk=enrollment.pk,
        expected_version=expected_version,
        changes={
            "status": Enrollment.Status.REMOVED,
            "ended_at": timezone.now(),
            "end_reason": reason.strip(),
        },
    )
    _enrollment_event(
        enrollment=changed,
        from_status=enrollment.status,
        reason_code="TEACHER_REMOVED",
        actor=actor,
        blockers=blockers,
        context=context,
    )
    _record_enrollment_end(enrollment, changed, actor, "enrollment.remove", context)
    return changed  # type: ignore[return-value]

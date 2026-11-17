from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.core.pagination import PageSpec

from .errors import CourseGrantRequired
from .models import AcademicTerm, Course, CourseStaff, CourseStaffGrant, Enrollment


def term_for_ref(term_ref: str) -> AcademicTerm:
    queryset = (
        AcademicTerm.objects.filter(is_current=True)
        if term_ref == "current"
        else AcademicTerm.objects.filter(public_id=term_ref)
    )
    try:
        return queryset.get()
    except AcademicTerm.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def teacher_courses_for_term(actor: User, term_ref: str) -> QuerySet[Course]:
    term = term_for_ref(term_ref)
    return (
        Course.objects.select_related("term", "owner")
        .filter(term=term, staff__user=actor, staff__status=CourseStaff.Status.ACTIVE)
        .exclude(status__in=(Course.Status.CLOSED, Course.Status.ARCHIVED))
        .distinct()
        .order_by("code", "id")
    )


def student_courses_for_term(actor: User, term_ref: str) -> QuerySet[Course]:
    term = term_for_ref(term_ref)
    return (
        Course.objects.select_related("term", "owner")
        .filter(
            term=term,
            enrollments__student=actor,
            enrollments__status=Enrollment.Status.ACTIVE,
        )
        .exclude(status__in=(Course.Status.CLOSED, Course.Status.ARCHIVED))
        .distinct()
        .order_by("code", "id")
    )


def owned_active_course_refs(user: User) -> list[str]:
    return list(
        Course.objects.filter(
            owner=user,
            staff__user=user,
            staff__role=CourseStaff.Role.OWNER,
            staff__status=CourseStaff.Status.ACTIVE,
        )
        .exclude(status=Course.Status.ARCHIVED)
        .values_list("public_id", flat=True)
    )


def course_scope_summaries(*, actor: User, portal: str) -> list[dict[str, object]]:
    if portal == "USER":
        return [
            {
                "course_id": item.course.public_id,
                "course_code": item.course.code,
                "relation": "ENROLLMENT",
                "status": item.status,
                "capabilities": [],
            }
            for item in Enrollment.objects.select_related("course").filter(
                student=actor,
                status__in=(Enrollment.Status.PENDING, Enrollment.Status.ACTIVE),
            )
        ]
    if portal == "TEACHING":
        now = timezone.now()
        result = []
        staff_rows = (
            CourseStaff.objects.select_related("course")
            .prefetch_related("grants")
            .filter(user=actor, status=CourseStaff.Status.ACTIVE)
        )
        for staff in staff_rows:
            capabilities = (
                list(CourseStaffGrant.Capability.values)
                if staff.role == CourseStaff.Role.OWNER
                else [
                    grant.capability
                    for grant in staff.grants.all()
                    if grant.status == CourseStaffGrant.Status.ACTIVE
                    and (grant.expires_at is None or grant.expires_at > now)
                ]
            )
            result.append({
                "course_id": staff.course.public_id,
                "course_code": staff.course.code,
                "relation": staff.role,
                "status": staff.status,
                "capabilities": capabilities,
            })
        return result
    return []


def active_staff(*, course: Course, actor: User) -> CourseStaff | None:
    return (
        CourseStaff.objects.filter(
            course=course,
            user=actor,
            status=CourseStaff.Status.ACTIVE,
        )
        .select_related("course", "user")
        .first()
    )


def _staff_has_capability(staff: CourseStaff, capability: str) -> bool:
    if staff.role == CourseStaff.Role.OWNER:
        return True
    now = timezone.now()
    return (
        CourseStaffGrant.objects.filter(
            course_staff=staff,
            capability=capability,
            status=CourseStaffGrant.Status.ACTIVE,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .exists()
    )


def has_course_capability(*, course: Course, actor: User, capability: str) -> bool:
    staff = active_staff(course=course, actor=actor)
    if staff is None:
        return False
    return _staff_has_capability(staff, capability)


def require_course_capability(*, course: Course, actor: User, capability: str) -> CourseStaff:
    staff = active_staff(course=course, actor=actor)
    if staff is None or not _staff_has_capability(staff, capability):
        raise CourseGrantRequired(detail={"course_id": course.public_id, "capability": capability})
    return staff


def require_owner(*, course: Course, actor: User) -> CourseStaff:
    staff = active_staff(course=course, actor=actor)
    if staff is None or staff.role != CourseStaff.Role.OWNER:
        raise CourseGrantRequired(detail={"course_id": course.public_id, "capability": "OWNER"})
    return staff


def active_enrollment(*, course: Course, student: User) -> Enrollment | None:
    return (
        Enrollment.objects.filter(
            course=course,
            student=student,
            status=Enrollment.Status.ACTIVE,
        )
        .select_related("course", "student")
        .first()
    )


def visible_courses(*, actor: User, portal: str) -> QuerySet[Course]:
    queryset = Course.objects.select_related("owner")
    if portal == "USER":
        return queryset.filter(
            Q(status=Course.Status.PUBLISHED, visibility=Course.Visibility.PUBLIC)
            | Q(
                enrollments__student=actor,
                enrollments__status__in=(Enrollment.Status.PENDING, Enrollment.Status.ACTIVE),
            )
        ).distinct()
    if portal == "TEACHING":
        return queryset.filter(
            staff__user=actor,
            staff__status=CourseStaff.Status.ACTIVE,
        ).distinct()
    if portal == "PLATFORM":
        return queryset
    return queryset.none()


def visible_course(*, actor: User, portal: str, course_id: str) -> Course:
    try:
        return visible_courses(actor=actor, portal=portal).get(public_id=course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def paged_courses(
    *,
    actor: User,
    portal: str,
    spec: PageSpec,
    query: str = "",
    status: str = "",
    enrollment_open: bool | None = None,
) -> tuple[QuerySet[Course], int]:
    courses = visible_courses(actor=actor, portal=portal).order_by("code", "id")
    if query:
        courses = courses.filter(
            Q(code__icontains=query) | Q(title__icontains=query) | Q(summary__icontains=query)
        )
    if status:
        courses = courses.filter(status=status)
    if enrollment_open is not None:
        now = timezone.now()
        open_filter = (
            Q(status=Course.Status.PUBLISHED)
            & (Q(enrollment_start__isnull=True) | Q(enrollment_start__lte=now))
            & (Q(enrollment_end__isnull=True) | Q(enrollment_end__gte=now))
        )
        courses = courses.filter(open_filter if enrollment_open else ~open_filter)
    total = courses.count()
    return courses[spec.offset : spec.offset + spec.page_size], total


def visible_enrollments(
    *, actor: User, portal: str, course: Course | None = None
) -> QuerySet[Enrollment]:
    queryset = Enrollment.objects.select_related("course", "student", "reviewed_by")
    if portal == "USER":
        return queryset.filter(student=actor)
    if portal == "TEACHING" and course is not None:
        require_course_capability(
            course=course,
            actor=actor,
            capability=CourseStaffGrant.Capability.MANAGE_ENROLLMENT,
        )
        return queryset.filter(course=course)
    if portal == "PLATFORM":
        return queryset.filter(course=course) if course is not None else queryset
    return queryset.none()


def visible_enrollment(
    *, actor: User, portal: str, enrollment_id: str, course: Course | None = None
) -> Enrollment:
    try:
        return visible_enrollments(actor=actor, portal=portal, course=course).get(
            public_id=enrollment_id
        )
    except Enrollment.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def paged_enrollments(
    *,
    actor: User,
    portal: str,
    spec: PageSpec,
    course: Course | None = None,
    status: str = "",
) -> tuple[QuerySet[Enrollment], int]:
    enrollments = visible_enrollments(actor=actor, portal=portal, course=course).order_by(
        "-applied_at", "-id"
    )
    if status:
        enrollments = enrollments.filter(status=status)
    total = enrollments.count()
    return enrollments[spec.offset : spec.offset + spec.page_size], total

from django.db.models import Q, QuerySet

from apps.core.pagination import PageSpec

from .models import IdentityVerification, PlatformAdminAssignment, TeacherQualification, User


def user_by_public_id(public_id: str) -> User:
    return User.objects.get(public_id=public_id)


def user_by_login(identifier: str) -> User | None:
    normalized = identifier.strip().casefold()
    return User.objects.filter(Q(email=normalized) | Q(username=normalized)).first()


def eligible_portals(user: User) -> list[str]:
    if user.account_status != User.AccountStatus.ACTIVE:
        return []
    portals = ["USER"]
    if TeacherQualification.objects.filter(
        user=user, status=TeacherQualification.Status.ACTIVE
    ).exists():
        portals.append("TEACHING")
    if PlatformAdminAssignment.objects.filter(
        user=user, status=PlatformAdminAssignment.Status.ACTIVE
    ).exists():
        portals.append("PLATFORM")
    return portals


def portal_permissions(portal: str) -> list[str]:
    return {
        "USER": ["course.catalog.view", "enrollment.apply", "profile.update"],
        "TEACHING": ["course.create", "profile.update"],
        "PLATFORM": ["platform.accounts.manage", "profile.update"],
    }.get(portal, [])


def paged_users(*, spec: PageSpec, query: str = "") -> tuple[QuerySet[User], int]:
    users = User.objects.all().order_by("id")
    if query:
        users = users.filter(
            Q(email__icontains=query)
            | Q(username__icontains=query)
            | Q(display_name__icontains=query)
        )
    return users[spec.offset : spec.offset + spec.page_size], users.count()


def paged_teacher_qualifications(
    *, spec: PageSpec, status: str = ""
) -> tuple[QuerySet[TeacherQualification], int]:
    queryset = TeacherQualification.objects.select_related("user").order_by("id")
    if status:
        queryset = queryset.filter(status=status)
    return queryset[spec.offset : spec.offset + spec.page_size], queryset.count()


def paged_admin_assignments(
    *, spec: PageSpec, status: str = ""
) -> tuple[QuerySet[PlatformAdminAssignment], int]:
    queryset = PlatformAdminAssignment.objects.select_related("user").order_by("id")
    if status:
        queryset = queryset.filter(status=status)
    return queryset[spec.offset : spec.offset + spec.page_size], queryset.count()


def paged_verifications(
    *, spec: PageSpec, status: str = ""
) -> tuple[QuerySet[IdentityVerification], int]:
    queryset = IdentityVerification.objects.select_related("user", "material_asset").order_by("id")
    if status:
        queryset = queryset.filter(status=status)
    return queryset[spec.offset : spec.offset + spec.page_size], queryset.count()

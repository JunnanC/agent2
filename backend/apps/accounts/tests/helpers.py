from django.contrib.auth.hashers import make_password
from django.utils import timezone

from apps.accounts.models import (
    IdentityVerification,
    PlatformAdminAssignment,
    TeacherQualification,
    User,
)


def create_user(
    *,
    email: str = "user@example.edu",
    username: str = "user",
    display_name: str = "Test User",
    password: str = "ValidPassword!234",
) -> User:
    user = User.objects.create(
        email=email,
        username=username,
        display_name=display_name,
        password=make_password(password),
    )
    IdentityVerification.objects.create(user=user)
    return user


def grant_teacher(user: User, actor: User | None = None) -> TeacherQualification:
    return TeacherQualification.objects.create(
        user=user,
        status=TeacherQualification.Status.ACTIVE,
        granted_by=actor or user,
        granted_at=timezone.now(),
        reason="test",
    )


def grant_admin(user: User, actor: User | None = None) -> PlatformAdminAssignment:
    return PlatformAdminAssignment.objects.create(
        user=user,
        status=PlatformAdminAssignment.Status.ACTIVE,
        granted_by=actor or user,
        granted_at=timezone.now(),
        reason="test",
    )

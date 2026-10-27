"""Demo identities: platform admin, teachers, students, verifications, preferences."""

from __future__ import annotations

import contextlib
from collections import Counter
from typing import Final

from django.utils import timezone

from apps.accounts.models import (
    IdentityVerification,
    PlatformAdminAssignment,
    TeacherQualification,
    User,
)
from apps.accounts.services import (
    ActorContext,
    create_user,
    grant_teacher_qualification,
    review_identity_verification,
    update_identity_verification,
)
from apps.notifications.models import Preference

from .banks import GIVEN_NAME_POOL, SURNAME_POOL
from .config import (
    BuildContext,
    admin_email,
    admin_username,
    student_display_name,
    student_email,
    student_username,
    teacher_display_name,
    teacher_email,
    teacher_username,
)

DEMO_ORGANIZATION: Final[str] = "演示理工大学"


def ensure_platform_admin(ctx: BuildContext, counts: Counter[str]) -> User:
    username, email = admin_username(), admin_email()
    user = User.objects.filter(username=username).first()
    if user is None:
        user = create_user(
            email=email,
            username=username,
            display_name="演示平台管理员",
            password=ctx.password,
            context=ActorContext("system", "SYSTEM", ctx.trace_id),
        )
        counts["accounts.User"] += 1
    assignment = PlatformAdminAssignment.objects.filter(
        user=user, status=PlatformAdminAssignment.Status.ACTIVE
    ).first()
    if assignment is None:
        PlatformAdminAssignment.objects.create(
            user=user,
            status=PlatformAdminAssignment.Status.ACTIVE,
            granted_by=user,
            granted_at=timezone.now(),
            reason="演示数据集管理账号",
        )
        counts["accounts.PlatformAdminAssignment"] += 1
    return user


def _reuse_or_create_user(
    ctx: BuildContext,
    counts: Counter[str],
    *,
    username: str,
    email: str,
    display_name: str,
) -> User:
    existing = User.objects.filter(username=username).first()
    if existing is not None:
        return existing
    user = create_user(
        email=email,
        username=username,
        display_name=display_name,
        password=ctx.password,
        context=ActorContext("system", "SYSTEM", ctx.trace_id),
    )
    counts["accounts.User"] += 1
    return user


def ensure_teachers(ctx: BuildContext, admin: User, counts: Counter[str]) -> list[User]:
    teachers: list[User] = []
    for index in range(1, ctx.config.teachers + 1):
        user = _reuse_or_create_user(
            ctx,
            counts,
            username=teacher_username(index),
            email=teacher_email(index),
            display_name=teacher_display_name(index, SURNAME_POOL, GIVEN_NAME_POOL),
        )
        qualified = TeacherQualification.objects.filter(
            user=user, status=TeacherQualification.Status.ACTIVE
        ).first()
        if qualified is None:
            grant_teacher_qualification(
                user_public_id=user.public_id,
                reason="演示数据集教师资质",
                expected_user_version=user.row_version,
                actor=admin,
                context=ActorContext(admin.public_id, "PLATFORM", ctx.trace_id),
            )
            counts["accounts.TeacherQualification"] += 1
        _ensure_preference(user, "TEACHING", counts)
        teachers.append(user)
    return teachers


def ensure_students(ctx: BuildContext, counts: Counter[str]) -> list[User]:
    students: list[User] = []
    for index in range(1, ctx.config.students + 1):
        user = _reuse_or_create_user(
            ctx,
            counts,
            username=student_username(index),
            email=student_email(index),
            display_name=student_display_name(index, SURNAME_POOL, GIVEN_NAME_POOL),
        )
        _ensure_preference(user, "USER", counts)
        students.append(user)
    return students


def seed_identity_verifications(
    ctx: BuildContext,
    admin: User,
    students: list[User],
    counts: Counter[str],
) -> None:
    for offset, student in enumerate(students):
        already = IdentityVerification.objects.filter(user=student).exists()
        if already:
            continue
        if offset % 3 != 0:
            continue
        verification = update_identity_verification(
            user=student,
            identity_type=IdentityVerification.IdentityType.SCHOOL,
            organization_name=DEMO_ORGANIZATION,
            identity_number=f"1131{1234 + offset * 7:08d}00{offset:02d}",
            material_asset_id="",
            submit=True,
            expected_version=1,
            context=ActorContext(student.public_id, "USER", ctx.trace_id),
        )
        counts["accounts.IdentityVerification"] += 1
        decision = "APPROVE" if offset % 9 != 0 else "REJECT"
        with contextlib.suppress(Exception):
            review_identity_verification(
                verification_public_id=verification.public_id,
                decision=decision,
                reason="演示数据集身份核验",
                expected_version=verification.row_version,
                actor=admin,
                context=ActorContext(admin.public_id, "PLATFORM", ctx.trace_id),
            )


def _ensure_preference(actor: User, portal: str, counts: Counter[str]) -> None:
    exists = Preference.objects.filter(account=actor, portal=portal).first()
    if exists is not None:
        return
    Preference.objects.create(
        account=actor,
        portal=portal,
        channels={"in_app": True},
        muted_kinds=[],
        digest_enabled=False,
    )
    counts["notifications.Preference"] += 1

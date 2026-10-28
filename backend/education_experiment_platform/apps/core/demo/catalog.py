"""Demo terms, courses, content, roster, and demo-scoped governance resources."""

from __future__ import annotations

import contextlib
from collections import Counter
from datetime import timedelta
from typing import Final

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import User
from apps.courses import content_services
from apps.courses.models import AcademicTerm, Course, Enrollment
from apps.courses.services import (
    ActorContext,
    apply_for_course,
    appoint_course_assistant,
    close_course,
    create_course,
    grant_course_capability,
    publish_course,
    review_enrollment,
)
from apps.governance.models import (
    ImageAsset,
    NetworkAllowlist,
    Quota,
    ResourceProfile,
    RuntimeAdapter,
    SecurityPolicy,
)

from .banks import (
    ANNOUNCEMENTS,
    CALENDAR_EVENTS,
    CHAPTER_TITLES,
    COURSE_DEFS,
    LINK_MATERIALS,
    MATERIAL_BODY,
    MATERIAL_TITLES,
    QUESTION_SAMPLES,
)
from .config import BuildContext, course_code, term_code

ENROLLMENT_FRACTIONS: Final[tuple[float, ...]] = (0.55, 0.5, 0.45)

DEMO_ADAPTER_CODE: Final[str] = "DEMO-FAKE-01"
DEMO_PROFILE_CODE: Final[str] = "DEMO-STD-2C-4G"
DEMO_IMAGE_REPOSITORY_PREFIX: Final[str] = "demo/python-lab-"


def ensure_academic_terms(ctx: BuildContext, counts: Counter[str]) -> AcademicTerm:
    current = AcademicTerm.objects.filter(is_current=True).first()
    if current is not None:
        return current
    now = timezone.now()
    current = AcademicTerm.objects.create(
        code=term_code(1),
        name="演示学期：进行中",
        starts_at=now - timedelta(days=45),
        ends_at=now + timedelta(days=90),
        status=AcademicTerm.Status.CURRENT,
        is_current=True,
    )
    counts["courses.AcademicTerm"] += 1
    AcademicTerm.objects.create(
        code=term_code(2),
        name="演示学期：已结束",
        starts_at=now - timedelta(days=200),
        ends_at=now - timedelta(days=120),
        status=AcademicTerm.Status.CLOSED,
        is_current=False,
    )
    AcademicTerm.objects.create(
        code=term_code(3),
        name="演示学期：即将开始",
        starts_at=now + timedelta(days=120),
        ends_at=now + timedelta(days=260),
        status=AcademicTerm.Status.UPCOMING,
        is_current=False,
    )
    counts["courses.AcademicTerm"] += 2
    return current


def _demo_adapter_spec() -> dict[str, str]:
    """REAL 模式下演示数据集使用真实本地 Docker 运行时，STUB 下保持 Fake。"""
    if str(getattr(settings, "LOCAL_RUNTIME_MODE", "REAL")).upper() != "STUB":
        return {
            "driver": RuntimeAdapter.Driver.DOCKER_LOCAL,
            "name": "本地 Docker 运行时",
            "config_ref": "runtime/local-docker",
            "change_reason": "演示数据集切换到真实本地 Docker 运行时",
        }
    return {
        "driver": RuntimeAdapter.Driver.FAKE,
        "name": "演示本地 Fake 运行时",
        "config_ref": "local-demo-fake-runtime",
        "change_reason": "演示数据集运行时",
    }


def ensure_runtime_catalog(ctx: BuildContext, admin: User, counts: Counter[str]) -> RuntimeAdapter:
    spec = _demo_adapter_spec()
    adapter = RuntimeAdapter.objects.filter(code=DEMO_ADAPTER_CODE).first()
    if adapter is None:
        adapter = RuntimeAdapter.objects.create(
            code=DEMO_ADAPTER_CODE,
            name=spec["name"],
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            driver=spec["driver"],
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
            node_count=1,
            capacity_cpu_millicores=400000,
            available_cpu_millicores=400000,
            capacity_memory_mb=800000,
            available_memory_mb=800000,
            config_ref=spec["config_ref"],
            last_health_at=timezone.now(),
            change_reason=spec["change_reason"],
        )
        counts["governance.RuntimeAdapter"] += 1
    elif adapter.driver != spec["driver"] or adapter.config_ref != spec["config_ref"]:
        from apps.core.concurrency import compare_and_swap

        adapter = compare_and_swap(
            RuntimeAdapter,
            pk=adapter.pk,
            expected_version=adapter.row_version,
            changes={
                "driver": spec["driver"],
                "name": spec["name"],
                "config_ref": spec["config_ref"],
                "change_reason": spec["change_reason"],
            },
        )
        counts["governance.RuntimeAdapter"] += 1
    profile = ResourceProfile.objects.filter(code=DEMO_PROFILE_CODE).first()
    if profile is None:
        ResourceProfile.objects.create(
            code=DEMO_PROFILE_CODE,
            name="演示标准容器规格",
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            status=ResourceProfile.Status.ACTIVE,
            cpu_millicores=2000,
            memory_mb=4096,
            cpu_request_millicores=500,
            cpu_limit_millicores=2000,
            memory_request_mb=1024,
            memory_limit_mb=4096,
            disk_gb=20,
            network_mode=ResourceProfile.NetworkMode.DENY_ALL,
            cost_minor_per_hour=0,
            currency_code="CNY",
            activated_at=timezone.now(),
            change_reason="演示数据集资源规格",
        )
        counts["governance.ResourceProfile"] += 1
    _ensure_shared_quotas(ctx, admin, counts)
    return adapter


def _ensure_shared_quotas(ctx: BuildContext, admin: User, counts: Counter[str]) -> None:
    values = {
        "max_concurrent_instances": 500,
        "max_concurrent_starts": 300,
        "max_cpu_millicores": 800000,
        "max_memory_mb": 900000,
        "max_disk_gb": 5000,
        "max_object_storage_bytes": 1_000_000_000_000,
        "max_agent_tokens_per_day": 10_000_000,
        "max_agent_requests_per_minute": 2000,
    }
    quota = Quota.objects.filter(scope_key="PLATFORM").first()
    if quota is None:
        Quota.objects.create(
            scope_type=Quota.ScopeType.PLATFORM,
            scope_key="PLATFORM",
            **values,
            updated_by=admin,
            change_reason="演示数据集平台配额",
        )
        counts["governance.Quota"] += 1
        return
    changes = {
        field: amount
        for field, amount in values.items()
        if (getattr(quota, field) or 0) < amount
    }
    if not changes:
        return
    from apps.core.concurrency import compare_and_swap

    compare_and_swap(Quota, pk=quota.pk, expected_version=quota.row_version, changes=changes)


def ensure_demo_image(
    ctx: BuildContext,
    admin: User,
    index: int,
    counts: Counter[str],
) -> ImageAsset:
    digest = f"sha256:{f'{8 + index:02x}' * 32}"
    asset = ImageAsset.objects.filter(digest=digest).first()
    if asset is not None:
        return asset
    now = timezone.now()
    asset = ImageAsset.objects.create(
        registry="registry.local",
        repository=f"{DEMO_IMAGE_REPOSITORY_PREFIX}{index:02d}",
        display_tag="demo",
        digest=digest,
        scan_status=ImageAsset.ScanStatus.CLEAN,
        approval_status=ImageAsset.ApprovalStatus.APPROVED,
        risk_level=ImageAsset.RiskLevel.LOW,
        scan_report_ref="scan/demo-dataset",
        scanned_at=now,
        approved_by=admin,
        approved_at=now,
        change_reason="演示数据集镜像",
    )
    counts["governance.ImageAsset"] += 1
    return asset


def demo_course_status(index: int, total: int, ctx: BuildContext) -> str:
    if ctx.config.closed_course and index == total - 2 and total >= 3:
        return Course.Status.CLOSED
    if ctx.config.draft_course and index == total - 1:
        return Course.Status.DRAFT
    return Course.Status.PUBLISHED


def build_demo_courses(
    ctx: BuildContext,
    teachers: list[User],
    counts: Counter[str],
) -> list[Course]:
    courses: list[Course] = []
    total = ctx.config.courses
    students_hint = ctx.config.students
    for index in range(total):
        definition = COURSE_DEFS[index % len(COURSE_DEFS)]
        expected = max(
            4,
            int(students_hint * ENROLLMENT_FRACTIONS[index % len(ENROLLMENT_FRACTIONS)]),
        )
        owner = teachers[index % len(teachers)]
        status = demo_course_status(index, total, ctx)
        context = ActorContext(owner.public_id, "TEACHING", ctx.trace_id)
        course = Course.objects.filter(code=course_code(index)).first()
        if course is None:
            course = create_course(
                actor=owner,
                code=course_code(index),
                title=definition["title"],
                summary=definition["summary"],
                description=definition["description"],
                visibility=Course.Visibility.PUBLIC,
                enrollment_mode=(
                    Course.EnrollmentMode.APPROVAL if index == 0 else Course.EnrollmentMode.OPEN
                ),
                capacity=expected + 5,
                enrollment_start=None,
                enrollment_end=None,
                teaching_start=None,
                teaching_end=None,
                context=context,
            )
            counts["courses.Course"] += 1
        if status == Course.Status.PUBLISHED and course.status == Course.Status.DRAFT:
            publish_course(
                course_id=course.public_id,
                actor=owner,
                expected_version=course.row_version,
                context=context,
            )
            counts["courses.Course"] += 1
        if status == Course.Status.CLOSED and course.status in {
            Course.Status.DRAFT,
            Course.Status.PUBLISHED,
        }:
            with contextlib.suppress(Exception):
                if course.status == Course.Status.DRAFT:
                    course = publish_course(
                        course_id=course.public_id,
                        actor=owner,
                        expected_version=course.row_version,
                        context=context,
                    )
                close_course(
                    course_id=course.public_id,
                    actor=owner,
                    expected_version=course.row_version,
                    context=context,
                )
        courses.append(course)
    return courses


def build_course_content(
    ctx: BuildContext,
    courses: list[Course],
    students: list[User],
    counts: Counter[str],
) -> None:
    for course_index, course in enumerate(courses):
        owner = course.owner
        teaching = ActorContext(owner.public_id, "TEACHING", ctx.trace_id)
        course.refresh_from_db()
        if course.status == Course.Status.ARCHIVED:
            continue
        existing_chapters = list(course.chapters.order_by("position"))
        for position in range(len(existing_chapters), ctx.config.chapters_per_course):
            chapter = content_services.create_chapter(
                course_id=course.public_id,
                actor=owner,
                title=CHAPTER_TITLES[position % len(CHAPTER_TITLES)],
                summary=f"演示课程第 {position + 1} 章内容。",
                position=position + 1,
                context=teaching,
            )
            counts["courses.Chapter"] += 1
            content_services.change_chapter_status(
                chapter_id=chapter.public_id,
                actor=owner,
                expected_version=chapter.row_version,
                status="PUBLISHED",
                context=teaching,
            )
            material = content_services.create_material(
                course_id=course.public_id,
                actor=owner,
                chapter_id=chapter.public_id,
                title=MATERIAL_TITLES[position % len(MATERIAL_TITLES)],
                kind="TEXT",
                text_content=MATERIAL_BODY,
                link_url="",
                asset_id=None,
                context=teaching,
            )
            content_services.change_material_version_status(
                version_id=material.current_version.public_id,
                actor=owner,
                expected_version=material.current_version.row_version,
                status="PUBLISHED",
                context=teaching,
            )
            counts["courses.Material"] += 1
        if not existing_chapters and course_index == 0:
            title, link_url = LINK_MATERIALS[0]
            chapter = course.chapters.order_by("position").first()
            if chapter is not None:
                content_services.create_material(
                    course_id=course.public_id,
                    actor=owner,
                    chapter_id=chapter.public_id,
                    title=title,
                    kind="LINK",
                    text_content="",
                    link_url=link_url,
                    asset_id=None,
                    context=teaching,
                )
                counts["courses.Material"] += 1
        _seed_announcements(ctx, course, owner, teaching, counts)
        _seed_calendar(ctx, course, owner, teaching, counts)
        _seed_invitation(ctx, course, owner, teaching, counts)
        if course_index == 2:
            _seed_q_and_a(ctx, course, students, owner, teaching, counts)


def _seed_invitation(
    ctx: BuildContext,
    course: Course,
    owner: User,
    teaching: ActorContext,
    counts: Counter[str],
) -> None:
    if course.invitations.exists():
        return
    content_services.create_invitation(
        course_id=course.public_id,
        actor=owner,
        max_uses=10,
        expires_at=timezone.now() + timedelta(days=30),
        context=teaching,
    )
    counts["courses.Invitation"] += 1


def _seed_announcements(
    ctx: BuildContext,
    course: Course,
    owner: User,
    teaching: ActorContext,
    counts: Counter[str],
) -> None:
    if course.announcements.exists():
        return
    first = content_services.create_announcement(
        course_id=course.public_id,
        actor=owner,
        title=str(ANNOUNCEMENTS[0]["title"]),
        body=str(ANNOUNCEMENTS[0]["body"]),
        pinned=bool(ANNOUNCEMENTS[0]["pinned"]),
        context=teaching,
    )
    content_services.publish_announcement(
        announcement_id=first.public_id,
        actor=owner,
        expected_version=first.row_version,
        context=teaching,
    )
    content_services.create_announcement(
        course_id=course.public_id,
        actor=owner,
        title=str(ANNOUNCEMENTS[1]["title"]),
        body=str(ANNOUNCEMENTS[1]["body"]),
        pinned=False,
        context=teaching,
    )
    counts["courses.Announcement"] += 2


def _seed_calendar(
    ctx: BuildContext,
    course: Course,
    owner: User,
    teaching: ActorContext,
    counts: Counter[str],
) -> None:
    if not course.calendar_events.exists():
        base = timezone.now() + timedelta(days=3)
        for offset, (title, description) in enumerate(CALENDAR_EVENTS):
            content_services.create_calendar_event(
                course_id=course.public_id,
                actor=owner,
                title=title,
                description=description,
                starts_at=base + timedelta(days=offset * 3, hours=19),
                ends_at=base + timedelta(days=offset * 3, hours=20),
                context=teaching,
            )
        counts["courses.CalendarEvent"] += len(CALENDAR_EVENTS)


def _seed_q_and_a(
    ctx: BuildContext,
    course: Course,
    students: list[User],
    owner: User,
    teaching: ActorContext,
    counts: Counter[str],
) -> None:
    asker = next(
        (
            enrollment.student
            for enrollment in course.enrollments.filter(status=Enrollment.Status.ACTIVE)
        ),
        None,
    )
    if asker is None:
        return
    student_view = ActorContext(asker.public_id, "USER", ctx.trace_id)
    question = content_services.create_question(
        course_id=course.public_id,
        actor=asker,
        title=QUESTION_SAMPLES[0][0],
        body=QUESTION_SAMPLES[0][1],
        context=student_view,
    )
    counts["courses.Question"] += 1
    content_services.answer_question(
        question_id=question.public_id,
        actor=owner,
        body="演示回复：自动检查完成后由教师完成人工评阅。",
        context=teaching,
    )
    content_services.create_question(
        course_id=course.public_id,
        actor=asker,
        title=QUESTION_SAMPLES[1][0],
        body=QUESTION_SAMPLES[1][1],
        context=student_view,
    )
    counts["courses.Question"] += 1


def build_roster(
    ctx: BuildContext,
    courses: list[Course],
    teachers: list[User],
    students: list[User],
    counts: Counter[str],
) -> None:
    if not students:
        return
    for course_index, course in enumerate(courses):
        course.refresh_from_db()
        if course.status == Course.Status.DRAFT:
            continue
        owner = course.owner
        teaching = ActorContext(owner.public_id, "TEACHING", ctx.trace_id)
        _appoint_assistant(
            course, owner, teachers[(teachers.index(owner) + 1) % len(teachers)], teaching, counts
        )
        if course.status != Course.Status.PUBLISHED:
            continue  # applications are only accepted while the course is open.
        expected = max(
            4,
            int(
                ctx.config.students
                * ENROLLMENT_FRACTIONS[course_index % len(ENROLLMENT_FRACTIONS)]
            ),
        )
        rotated = [
            students[(partner_offset + course_index * 7) % len(students)]
            for partner_offset in range(ctx.config.students)
        ]
        pending: list[Enrollment] = []
        made = 0
        for student in rotated:
            if made >= expected:
                break
            if course.enrollments.filter(student=student).exists():
                made += 1
                continue
            enrollment = apply_for_course(
                course_id=course.public_id,
                student=student,
                application_message="演示数据集选课申请",
                context=ActorContext(student.public_id, "USER", ctx.trace_id),
            )
            counts["courses.Enrollment"] += 1
            made += 1
            if course.enrollment_mode == Course.EnrollmentMode.APPROVAL:
                pending.append(enrollment)
        if pending:
            _review_applications(ctx, course, owner, pending, teaching, counts)


def _appoint_assistant(
    course: Course,
    owner: User,
    assistant: User,
    teaching: ActorContext,
    counts: Counter[str],
) -> None:
    already = course.staff.filter(user=assistant, status="ACTIVE").first()
    if already is not None:
        return
    staff = appoint_course_assistant(
        course_id=course.public_id,
        user_id=assistant.public_id,
        actor=owner,
        reason="演示数据集助教",
        context=teaching,
    )
    counts["courses.CourseStaff"] += 1
    for capability in ("MANAGE_ENROLLMENT", "REVIEW_SUBMISSION"):
        grant_course_capability(
            course_id=course.public_id,
            staff_id=staff.public_id,
            capability=capability,
            expires_at=None,
            actor=owner,
            reason="演示数据集助教授权",
            context=teaching,
        )
        counts["courses.CourseStaffGrant"] += 1


def _review_applications(
    ctx: BuildContext,
    course: Course,
    owner: User,
    enrollments: list[Enrollment],
    teaching: ActorContext,
    counts: Counter[str],
) -> None:
    rejected = max(1, len(enrollments) // 3)
    for offset, enrollment in enumerate(enrollments):
        enrollment.refresh_from_db()
        if enrollment.status != Enrollment.Status.PENDING:
            continue
        if offset >= len(enrollments) - 2:
            continue  # keep two applications PENDING for realism.
        decision = "REJECT" if offset == rejected else "APPROVE"
        with contextlib.suppress(Exception):
            review_enrollment(
                course_id=course.public_id,
                enrollment_id=enrollment.public_id,
                decision=decision,
                note="演示数据集选课审核",
                actor=owner,
                expected_version=enrollment.row_version,
                context=teaching,
            )
            counts["courses.EnrollmentDecision"] += 1


def seed_course_scoped_governance(
    ctx: BuildContext,
    admin: User,
    courses: list[Course],
    counts: Counter[str],
) -> None:
    for course in courses:
        if course.status == Course.Status.DRAFT:
            continue
        now = timezone.now()
        Quota.objects.get_or_create(
            scope_key=f"COURSE:{course.public_id}",
            defaults={
                "scope_type": Quota.ScopeType.COURSE,
                "course": course,
                "max_concurrent_instances": 120,
                "max_concurrent_starts": 120,
                "max_cpu_millicores": 120000,
                "max_memory_mb": 120000,
                "max_disk_gb": 400,
                "max_object_storage_bytes": 200_000_000_000,
                "max_agent_tokens_per_day": 2_000_000,
                "max_agent_requests_per_minute": 500,
                "updated_by": admin,
                "change_reason": "演示数据集课程配额",
            },
        )
        counts["governance.Quota"] += 1
        SecurityPolicy.objects.get_or_create(
            policy_kind="RESOURCE_SCALING",
            scope_key=f"COURSE:{course.public_id}",
            defaults={
                "scope_type": SecurityPolicy.ScopeType.COURSE,
                "course": course,
                "risk_level": SecurityPolicy.RiskLevel.MEDIUM,
                "rules": {
                    "prewarm_enabled": False,
                    "prewarm_lead_minutes": 0,
                    "min_replicas": 0,
                    "max_replicas": 5,
                    "cooldown_seconds": 300,
                    "idle_reclaim_seconds": 1200,
                    "budget_minor": 20000,
                    "currency_code": "CNY",
                    "max_course_concurrency": 30,
                },
                "updated_by": admin,
                "change_reason": "演示数据集课程弹性策略",
            },
        )
        counts["governance.SecurityPolicy"] += 1
        for host, port in (("pypi.org", 443), ("registry.local", 5000)):
            NetworkAllowlist.objects.get_or_create(
                scope_key=f"COURSE:{course.public_id}",
                target_type="HOST",
                target_value=host,
                protocol="TCP",
                port_start=port,
                port_end=port,
                defaults={
                    "scope_type": NetworkAllowlist.ScopeType.COURSE,
                    "course": course,
                    "risk_level": "LOW",
                    "status": "ACTIVE",
                    "approved_by": admin,
                    "approved_at": now,
                    "change_reason": "演示数据集课程放行名单",
                },
            )
        counts["governance.NetworkAllowlist"] += 2

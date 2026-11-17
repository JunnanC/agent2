"""Seed a realistic Data Structures & Algorithms demo course.

Run inside the backend image (the runtime worker has the Docker socket needed
for precheck and image digest resolution):

    python manage.py seed_algorithm_demo --stage runtime
    python manage.py seed_algorithm_demo --stage course
    python manage.py seed_algorithm_demo --stage experiments
    python manage.py seed_algorithm_demo --stage activity

Every stage is idempotent and keyed by stable codes/names, so it can be re-run.
"""

from __future__ import annotations

import os
import re
import secrets
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.courses.content_services import (
    answer_question,
    change_chapter_status,
    change_material_version_status,
    create_announcement,
    create_calendar_event,
    create_material,
    create_question,
    publish_announcement,
)
from apps.courses.content_services import (
    create_chapter as create_course_chapter,
)
from apps.courses.models import (
    AcademicTerm,
    Chapter,
    Course,
    CourseSchedule,
    Enrollment,
    Material,
)
from apps.courses.services import (
    ActorContext,
    apply_for_course,
    create_course,
    current_academic_term,
    publish_course,
    review_enrollment,
)
from apps.experiments import demo_content as content
from apps.experiments.assessment import submit_choices
from apps.experiments.models import AnswerDraft, ExperimentTask, TaskPublication
from apps.experiments.services import (
    close_publication,
    create_publication,
    publish_publication,
)
from apps.governance.models import ImageAsset, Quota, ResourceProfile, RuntimeAdapter
from apps.governance.services import (
    create_image,
    create_quota,
    create_resource_profile,
    create_runtime_adapter,
    decide_image,
    rebuild_quota_cache,
    resolve_image_digest,
    transition_resource_profile,
    update_image_scan,
    update_runtime_adapter,
)
from apps.labtemplates.assessment_assets import store_question_tests
from apps.labtemplates.models import Template, TemplateChapter, TemplateVersion
from apps.labtemplates.services import (
    create_chapter as create_template_chapter,
)
from apps.labtemplates.services import (
    create_task,
    create_template,
    create_version,
    execute_precheck,
    publish_version,
    request_precheck,
)
from apps.reviews.services import (
    create_rubric,
    create_rubric_version,
    publish_rubric_version,
)

COURSE_CODE = content.COURSE["code"]
ADAPTER_CODE = "DEMO-LOCAL-DOCKER"
PROFILE_CODE = "DEMO-STDIO-512M"
IMAGE_REPOSITORY = "experimental-platform-stdio"
PUBLICATION_SUFFIX = "（2026 秋）"


class Command(BaseCommand):
    help = "Seed the algorithm demo course, chapters, experiments and activity."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--stage",
            choices=("runtime", "course", "experiments", "activity", "all"),
            default="all",
        )
        parser.add_argument("--reset", action="store_true", help="Delete the demo course first")

    def handle(self, *args: Any, **options: Any) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"}:
            raise CommandError("Refusing to seed a non-local environment")
        self.admin = User.objects.filter(username="demo-admin").first()
        if self.admin is None:
            raise CommandError("demo-admin account is required")
        self.ctx = ActorContext(
            actor_ref=self.admin.public_id,
            portal="PLATFORM",
            trace_id=secrets.token_hex(16),
        )
        stage = options["stage"]
        if options["reset"]:
            self._reset()
        if stage in {"runtime", "all"}:
            self._runtime()
        if stage in {"course", "all"}:
            self._course()
        if stage in {"experiments", "all"}:
            self._experiments()
        if stage in {"activity", "all"}:
            self._activity()

    # ------------------------------------------------------------------ runtime
    def _runtime(self) -> None:
        adapter = RuntimeAdapter.objects.filter(code=ADAPTER_CODE).first()
        if adapter is None:
            adapter = create_runtime_adapter(
                actor=self.admin,
                code=ADAPTER_CODE,
                name="演示本地 Docker 运行时",
                runtime_type="CONTAINER",
                driver="DOCKER_LOCAL",
                config_ref="runtime/local-docker",
                reason="算法演示课程运行环境",
                context=self.ctx,
            )
        if adapter.status != "ENABLED":
            adapter = update_runtime_adapter(
                adapter_id=adapter.public_id,
                actor=self.admin,
                expected_version=adapter.row_version,
                changes={"status": "ENABLED"},
                reason="演示环境启用",
                context=self.ctx,
            )

        profile = ResourceProfile.objects.filter(code=PROFILE_CODE).first()
        if profile is None:
            profile = create_resource_profile(
                actor=self.admin,
                code=PROFILE_CODE,
                name="演示容器规格 0.5C/512M",
                runtime_type="CONTAINER",
                cpu_millicores=500,
                memory_mb=512,
                cpu_request_millicores=250,
                cpu_limit_millicores=1000,
                memory_request_mb=256,
                memory_limit_mb=1024,
                disk_gb=2,
                network_mode="DENY_ALL",
                cost_minor_per_hour=0,
                currency_code="CNY",
                reason="算法演示课程运行规格",
                context=self.ctx,
            )
        if profile.status != "ACTIVE":
            profile = transition_resource_profile(
                profile_id=profile.public_id,
                actor=self.admin,
                expected_version=profile.row_version,
                target_status="ACTIVE",
                reason="演示环境启用规格",
                context=self.ctx,
            )

        if not Quota.objects.filter(scope_type="PLATFORM").exists():
            create_quota(
                actor=self.admin,
                scope_type="PLATFORM",
                course_id=None,
                user_id=None,
                values={
                    "max_concurrent_instances": 12,
                    "max_concurrent_starts": 12,
                    "max_cpu_millicores": 8000,
                    "max_memory_mb": 8192,
                    "max_disk_gb": 32,
                    "max_object_storage_bytes": 2 * 1024**3,
                    "max_agent_tokens_per_day": 200000,
                    "max_agent_requests_per_minute": 60,
                },
                reason="演示平台默认配额",
                context=self.ctx,
            )
        try:
            rebuild_quota_cache()
        except Exception as exc:  # pragma: no cover - cache is optional for seeding
            self.stderr.write(f"quota cache rebuild skipped: {exc}")

        image = ImageAsset.objects.filter(repository=IMAGE_REPOSITORY).first()
        if image is None:
            image = create_image(
                actor=self.admin,
                registry="localhost:5000",
                repository=IMAGE_REPOSITORY,
                display_tag="local",
                risk_level="LOW",
                reason="算法演示课程执行镜像",
                context=self.ctx,
            )
        if not image.digest:
            image = resolve_image_digest(
                image_id=image.public_id,
                context=self.ctx,
                reason="解析本地 stdio 镜像摘要",
            )
        image.refresh_from_db()
        if image.scan_status != "CLEAN":
            image = update_image_scan(
                image_id=image.public_id,
                expected_version=image.row_version,
                scan_status="CLEAN",
                scan_report_ref="local-clamav-20261116",
                risk_level="LOW",
                reason="沿用 2026-11-16 本地 ClamAV 全盘扫描结果（同一 digest）",
                actor=self.admin,
                context=self.ctx,
            )
        image.refresh_from_db()
        if image.approval_status != "APPROVED":
            image = decide_image(
                image_id=image.public_id,
                actor=self.admin,
                expected_version=image.row_version,
                decision="APPROVED",
                reason="演示环境批准本地已验证镜像",
                context=self.ctx,
            )
        self.stdout.write(
            self.style.SUCCESS(
                "runtime ready: "
                f"adapter={adapter.public_id} profile={profile.public_id} image={image.public_id}"
            )
        )

    # ------------------------------------------------------------------- course
    def _course(self) -> None:
        teacher = User.objects.filter(username="demo-teacher-01").first()
        if teacher is None:
            raise CommandError("demo-teacher-01 account is required")
        self.teacher = teacher
        self.teacher_ctx = ActorContext(
            actor_ref=teacher.public_id,
            portal="TEACHING",
            trace_id=secrets.token_hex(16),
        )
        try:
            term = current_academic_term()
        except AcademicTerm.DoesNotExist:
            code, name = content.COURSE["term"]
            now = timezone.now()
            term = AcademicTerm.objects.create(
                code=code,
                name=name,
                starts_at=now - timezone.timedelta(days=30),
                ends_at=now + timezone.timedelta(days=150),
                status=AcademicTerm.Status.CURRENT,
                is_current=True,
            )

        course = Course.objects.filter(code=COURSE_CODE).first()
        now = timezone.now()
        if course is None:
            course = create_course(
                actor=teacher,
                code=COURSE_CODE,
                title=content.COURSE["title"],
                summary=content.COURSE["summary"],
                description=content.COURSE["description"],
                visibility="PUBLIC",
                enrollment_mode="APPROVAL",
                capacity=60,
                enrollment_start=now - timezone.timedelta(days=45),
                enrollment_end=now + timezone.timedelta(days=45),
                teaching_start=now - timezone.timedelta(days=21),
                teaching_end=now + timezone.timedelta(days=120),
                context=self.teacher_ctx,
                term=term,
            )

        for position, chapter_data in enumerate(content.CHAPTERS, start=1):
            chapter = Chapter.objects.filter(course=course, title=chapter_data["title"]).first()
            if chapter is None:
                chapter = create_course_chapter(
                    course_id=course.public_id,
                    actor=teacher,
                    title=chapter_data["title"],
                    summary=chapter_data["summary"],
                    position=position,
                    content=chapter_data["content"].strip(),
                    context=self.teacher_ctx,
                )
            if chapter.status != "PUBLISHED":
                chapter = change_chapter_status(
                    chapter_id=chapter.public_id,
                    actor=teacher,
                    expected_version=chapter.row_version,
                    status="PUBLISHED",
                    context=self.teacher_ctx,
                )
            self._materials(course, chapter, chapter_data)

        for item in content.ANNOUNCEMENTS:
            if not course.announcements.filter(title=item["title"]).exists():
                announcement = create_announcement(
                    course_id=course.public_id,
                    actor=teacher,
                    title=item["title"],
                    body=item["body"],
                    pinned=item["pinned"],
                    context=self.teacher_ctx,
                )
                publish_announcement(
                    announcement_id=announcement.public_id,
                    actor=teacher,
                    expected_version=announcement.row_version,
                    context=self.teacher_ctx,
                )

        for title, description, offset_days, hours in content.CALENDAR_EVENTS:
            if not course.calendar_events.filter(title=title).exists():
                start = (now + timezone.timedelta(days=offset_days)).replace(
                    hour=14, minute=0, second=0, microsecond=0
                )
                create_calendar_event(
                    course_id=course.public_id,
                    actor=teacher,
                    title=title,
                    description=description,
                    starts_at=start,
                    ends_at=start + timezone.timedelta(hours=hours),
                    context=self.teacher_ctx,
                )

        course.refresh_from_db()
        if course.status == "DRAFT":
            course = publish_course(
                course_id=course.public_id,
                actor=teacher,
                expected_version=course.row_version,
                context=self.teacher_ctx,
            )

        for weekday, start_period, end_period, classroom in content.COURSE_SCHEDULES:
            if not CourseSchedule.objects.filter(
                course=course, weekday=weekday, start_period=start_period
            ).exists():
                CourseSchedule.objects.create(
                    course=course,
                    weekday=weekday,
                    start_period=start_period,
                    end_period=end_period,
                    week_start=1,
                    week_end=16,
                    classroom=classroom,
                    instructor_name=teacher.display_name,
                )

        self._students(course)
        self._questions(course)
        self.stdout.write(
            self.style.SUCCESS(
                f"course ready: {course.code} / {course.title} ({course.status}), "
                f"chapters={course.chapters.count()}, enrolled="
                f"{course.enrollments.filter(status='ACTIVE').count()}"
            )
        )

    def _materials(self, course: Course, chapter: Chapter, chapter_data: dict[str, Any]) -> None:
        short_name = re.sub(r"^第\s*\d+\s*章\s*", "", chapter_data["title"])
        text_title = f"导读：{short_name}"
        if not Material.objects.filter(course=course, title=text_title).exists():
            material = create_material(
                course_id=course.public_id,
                actor=self.teacher,
                chapter_id=chapter.public_id,
                title=text_title,
                kind="TEXT",
                text_content=chapter_data["material"],
                link_url="",
                asset_id=None,
                context=self.teacher_ctx,
            )
            version = material.current_version
            change_material_version_status(
                version_id=version.public_id,
                actor=self.teacher,
                expected_version=version.row_version,
                status="PUBLISHED",
                context=self.teacher_ctx,
            )

        link_title = f"延伸阅读：{short_name}"
        if not Material.objects.filter(course=course, title=link_title).exists():
            material = create_material(
                course_id=course.public_id,
                actor=self.teacher,
                chapter_id=chapter.public_id,
                title=link_title,
                kind="LINK",
                text_content="",
                link_url=f"https://www.hello-algo.com/zh-hans/{chapter_data['hello_chapter']}/",
                asset_id=None,
                context=self.teacher_ctx,
            )
            version = material.current_version
            change_material_version_status(
                version_id=version.public_id,
                actor=self.teacher,
                expected_version=version.row_version,
                status="PUBLISHED",
                context=self.teacher_ctx,
            )

    def _students(self, course: Course) -> None:
        password = os.getenv("DEMO_SEED_PASSWORD", "Demo-Seed-Only-2026!")
        # The shared demo student is always enrolled so the ready-made login can
        # immediately walk the course; the remaining accounts provide classmates.
        accounts = [("demo-student-001", "王远浩")] + [
            item for item in content.STUDENTS if item[0] != "demo-student-001"
        ]
        pending_names = {username for username, _ in content.STUDENTS[-2:]}
        for username, display_name in accounts:
            student = User.objects.filter(username=username).first()
            if student is None:
                student = create_user(
                    email=f"{username}@demo.edu",
                    username=username,
                    display_name=display_name,
                    password=password,
                    context=self.teacher_ctx,
                )
            active = Enrollment.objects.filter(
                course=course, student=student, status="ACTIVE"
            ).exists()
            pending = Enrollment.objects.filter(
                course=course, student=student, status="PENDING"
            ).exists()
            if active or pending:
                continue
            student_ctx = ActorContext(
                actor_ref=student.public_id,
                portal="USER",
                trace_id=secrets.token_hex(16),
            )
            enrollment = apply_for_course(
                course_id=course.public_id,
                student=student,
                application_message="选修数据结构与算法（Python），希望补齐算法基础。",
                context=student_ctx,
            )
            if username not in pending_names:
                review_enrollment(
                    course_id=course.public_id,
                    enrollment_id=enrollment.public_id,
                    decision="APPROVE",
                    note="演示数据：审核通过",
                    actor=self.teacher,
                    expected_version=enrollment.row_version,
                    context=self.teacher_ctx,
                )

    def _questions(self, course: Course) -> None:
        enrolled = list(
            Enrollment.objects.filter(course=course, status="ACTIVE")
            .select_related("student")
            .order_by("student__username")
        )
        if not enrolled:
            return
        for index, (title, answer) in enumerate(content.QA):
            if course.questions.filter(title=title).exists():
                continue
            student = enrolled[index % len(enrolled)].student
            student_ctx = ActorContext(
                actor_ref=student.public_id,
                portal="USER",
                trace_id=secrets.token_hex(16),
            )
            question = create_question(
                course_id=course.public_id,
                actor=student,
                title=title,
                body=title,
                context=student_ctx,
            )
            answer_question(
                question_id=question.public_id,
                actor=self.teacher,
                body=answer,
                context=self.teacher_ctx,
            )

    # -------------------------------------------------------------- experiments
    def _experiments(self) -> None:
        course = Course.objects.filter(code=COURSE_CODE).first()
        if course is None or course.status != "PUBLISHED":
            raise CommandError("run the course stage first")
        teacher = self.teacher = User.objects.get(username="demo-teacher-01")
        self.teacher_ctx = ActorContext(
            actor_ref=teacher.public_id, portal="TEACHING", trace_id=secrets.token_hex(16)
        )
        adapter = RuntimeAdapter.objects.get(code=ADAPTER_CODE, status="ENABLED")
        image = ImageAsset.objects.get(repository=IMAGE_REPOSITORY, approval_status="APPROVED")
        profile = ResourceProfile.objects.get(code=PROFILE_CODE, status="ACTIVE")
        runtime_data = {
            "runtime_type": "CONTAINER",
            "runtime_adapter_id": adapter.public_id,
            "image_id": image.public_id,
            "resource_profile_id": profile.public_id,
        }
        now = timezone.now()
        for spec in content.EXPERIMENTS:
            title = f"{spec['name']}{PUBLICATION_SUFFIX}"
            publication = TaskPublication.objects.filter(course=course, title=title).first()
            if publication is not None:
                if publication.status == "DRAFT":
                    publish_publication(
                        course_id=course.public_id,
                        publication_id=publication.public_id,
                        actor=teacher,
                        expected_version=publication.row_version,
                        selected_ids=[],
                        context=self.teacher_ctx,
                    )
                continue
            template = Template.objects.filter(course=course, name=spec["name"]).first()
            if template is None:
                template = create_template(
                    course_id=course.public_id,
                    actor=teacher,
                    name=spec["name"],
                    category=spec["category"],
                    description=spec["description"],
                    context=self.teacher_ctx,
                )
            version = template.versions.order_by("-version_no").first()
            if version is None:
                version = create_version(
                    course_id=course.public_id,
                    template_id=template.public_id,
                    actor=teacher,
                    data=runtime_data,
                    context=self.teacher_ctx,
                )
            if version.status in {"DRAFT", "PRECHECK_FAILED"}:
                self._build_version(course, version, spec)
                version.refresh_from_db()
                run = request_precheck(
                    course_id=course.public_id,
                    version_id=version.public_id,
                    actor=teacher,
                    expected_version=version.row_version,
                    context=self.teacher_ctx,
                )
                run = execute_precheck(run_id=run.public_id)
                version.refresh_from_db()
                if run.status != "PASSED":
                    raise CommandError(
                        f"precheck failed for {spec['code']}: "
                        f"{run.error_code} {run.error_detail_masked}"
                    )
            if version.status == "PRECHECK_PASSED":
                version = publish_version(
                    course_id=course.public_id,
                    version_id=version.public_id,
                    actor=teacher,
                    expected_version=version.row_version,
                    context=self.teacher_ctx,
                )
            if version.status != "PUBLISHED":
                raise CommandError(f"version not published for {spec['code']}: {version.status}")

            rubric = None
            if spec["report_required"]:
                rubric = self._rubric(course, spec)
            start_days, end_days = spec["window_days"]
            publication = create_publication(
                course_id=course.public_id,
                actor=teacher,
                context=self.teacher_ctx,
                data={
                    "template_version_id": version.public_id,
                    "rubric_version_id": rubric.public_id if rubric else None,
                    "course_chapter_id": course.chapters.order_by("position")[
                        spec["course_chapters"][0]
                    ].public_id,
                    "title": title,
                    "description": spec["description"],
                    "audience_mode": "ALL_ACTIVE",
                    "late_enrollment_policy": "ASSIGN_UNTIL_DEADLINE",
                    "window_start": now + timezone.timedelta(days=start_days),
                    "window_end": now + timezone.timedelta(days=end_days),
                    "report_required": spec["report_required"],
                    "review_mode": "MANUAL_WITH_AUTO_CHECK",
                },
            )
            publish_publication(
                course_id=course.public_id,
                publication_id=publication.public_id,
                actor=teacher,
                expected_version=publication.row_version,
                selected_ids=[],
                context=self.teacher_ctx,
            )
            self.stdout.write(f"published: {title}")

    def _build_version(
        self, course: Course, version: TemplateVersion, spec: dict[str, Any]
    ) -> None:
        for chapter_spec in spec["chapters"]:
            version.refresh_from_db()
            chapter = TemplateChapter.objects.filter(
                template_version=version, title=chapter_spec["title"]
            ).first()
            if chapter is None:
                chapter = create_template_chapter(
                    course_id=course.public_id,
                    version_id=version.public_id,
                    actor=self.teacher,
                    expected_version=version.row_version,
                    data={
                        "title": chapter_spec["title"],
                        "description": chapter_spec["description"],
                        "learning_objectives": chapter_spec["objectives"],
                    },
                    context=self.teacher_ctx,
                )
            for task in chapter_spec["tasks"]:
                task_title = (
                    content.PROGRAMMING_TASKS[task["key"]]["title"]
                    if task["type"] == content.PROGRAMMING
                    else task["title"]
                )
                if chapter.tasks.filter(title=task_title, active=True).exists():
                    continue
                version.refresh_from_db()
                data = self._task_data(course, version, task)
                version.refresh_from_db()
                create_task(
                    course_id=course.public_id,
                    chapter_id=chapter.public_id,
                    actor=self.teacher,
                    expected_version=version.row_version,
                    data=data,
                    context=self.teacher_ctx,
                )

    def _task_data(
        self, course: Course, version: TemplateVersion, task: dict[str, Any]
    ) -> dict[str, Any]:
        if task["type"] == content.PROGRAMMING:
            problem = content.PROGRAMMING_TASKS[task["key"]]
            stored = store_question_tests(
                actor=self.teacher,
                course_id=course.public_id,
                version_id=version.public_id,
                expected_version=version.row_version,
                groups=[
                    {"id": group["id"], "cases": group["cases"]}
                    for group in problem["tests"]
                ],
                scores=[
                    {"id": group["id"], "score": group["score"]}
                    for group in problem["tests"]
                ],
                context=self.teacher_ctx,
            )
            return {
                "title": problem["title"],
                "description": problem["description"],
                "instructions": problem["instructions"],
                "task_type": "PROGRAMMING",
                "max_score": task["score"],
                "question_spec": {
                    "allowed_languages": ["python"],
                    "samples": problem["samples"],
                    "starter_files": {"python": {"main.py": problem["starter"]}},
                    "limits": {"python": {"timeout_seconds": 3, "memory_mb": 256}},
                },
                "marking_spec": {
                    "tests_asset_id": stored["asset_id"],
                    "groups": [
                        {"id": group["id"], "score": group["score"]}
                        for group in problem["tests"]
                    ],
                    "reference_solutions": {"python": {"main.py": problem["reference"]}},
                },
            }
        return {
            "title": task["title"],
            "description": task["description"],
            "task_type": task["type"],
            "max_score": task["score"],
            "question_spec": {
                "options": [
                    {"id": option_id, "text": text}
                    for option_id, text in task["options"]
                ]
            },
            "marking_spec": {
                "correct_option_ids": task["correct"],
                "explanation": task["explanation"],
            },
        }

    def _rubric(self, course: Course, spec: dict[str, Any]) -> Any:
        name = f"{spec['name']}报告评分表"
        rubric = course.rubrics.filter(name=name).first()
        if rubric is None:
            rubric = create_rubric(
                course_id=course.public_id,
                actor=self.teacher,
                name=name,
                description="实验报告评分标准",
                context=self.teacher_ctx,
            )
        version = rubric.versions.order_by("-version_no").first()
        if version is None:
            version = create_rubric_version(
                course_id=course.public_id,
                rubric_id=rubric.public_id,
                actor=self.teacher,
                title="实验报告",
                description="按过程、分析与结论评分",
                total_score=100,
                criteria=[
                    {
                        "position": 1,
                        "title": "实验过程与分析",
                        "description": "步骤完整、分析有依据",
                        "max_score": 60,
                        "weight_basis_points": 6000,
                    },
                    {
                        "position": 2,
                        "title": "结论与反思",
                        "description": "结论明确、能指出改进方向",
                        "max_score": 40,
                        "weight_basis_points": 4000,
                    },
                ],
                context=self.teacher_ctx,
            )
        if version.status != "PUBLISHED":
            version = publish_rubric_version(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=self.teacher,
                expected_version=version.row_version,
                context=self.teacher_ctx,
            )
        return version

    # ----------------------------------------------------------------- activity
    def _activity(self) -> None:
        from apps.experiments.models import PublicationTask

        course = Course.objects.filter(code=COURSE_CODE).first()
        if course is None:
            raise CommandError("run the course stage first")
        teacher = User.objects.get(username="demo-teacher-01")
        teacher_ctx = ActorContext(
            actor_ref=teacher.public_id, portal="TEACHING", trace_id=secrets.token_hex(16)
        )
        for spec in content.EXPERIMENTS:
            title = f"{spec['name']}{PUBLICATION_SUFFIX}"
            publication = TaskPublication.objects.filter(course=course, title=title).first()
            if publication is None or publication.status not in {"PUBLISHED", "CLOSED"}:
                continue
            if spec["code"] != "EXP1" and spec["code"] != "EXP2":
                continue
            tasks = list(
                ExperimentTask.objects.filter(publication=publication)
                .select_related("student")
                .order_by("student__username")
            )
            questions = list(
                PublicationTask.objects.filter(
                    publication_chapter__publication=publication,
                    task_type__in=("SINGLE_CHOICE", "MULTIPLE_CHOICE"),
                ).order_by("publication_chapter__sort_order", "sort_order", "id")
            )
            limit = len(tasks) if spec["code"] == "EXP1" else 3
            for index, task in enumerate(tasks[:limit]):
                if task.status in {"APPROVED", "UNDER_REVIEW", "COMPLETED"}:
                    continue
                versions = {}
                for question_index, question in enumerate(questions):
                    draft, _ = AnswerDraft.objects.get_or_create(task=task, question=question)
                    correct = list(question.marking_spec["correct_option_ids"])
                    pass_question = (index + question_index) % 10 < 7
                    selected = correct if pass_question else self._wrong_answer(question, correct)
                    AnswerDraft.objects.filter(pk=draft.pk).update(
                        selected_option_ids=sorted(selected)
                    )
                    draft.refresh_from_db()
                    versions[question.public_id] = draft.row_version
                submit_choices(
                    actor=task.student,
                    task_id=task.public_id,
                    versions=versions,
                    trace_id=secrets.token_hex(16),
                )
            if spec["code"] == "EXP1" and spec["close_after_seed"]:
                publication.refresh_from_db()
                if publication.status == "PUBLISHED":
                    close_publication(
                        course_id=course.public_id,
                        publication_id=publication.public_id,
                        actor=teacher,
                        expected_version=publication.row_version,
                        context=teacher_ctx,
                    )
        self.stdout.write(self.style.SUCCESS("activity ready"))

    @staticmethod
    def _wrong_answer(question: Any, correct: list[str]) -> list[str]:
        options = [option["id"] for option in question.question_spec["options"]]
        if len(correct) >= 2:
            return correct[:-1]
        for option in options:
            if option not in correct:
                return [option]
        return []

    def _reset(self) -> None:
        raise CommandError(
            "--reset is intentionally not implemented: remove the demo course manually "
            "after exporting any data you need"
        )

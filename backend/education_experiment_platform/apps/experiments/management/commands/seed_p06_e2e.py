import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.courses.models import Course
from apps.courses.services import ActorContext
from apps.labtemplates.models import Template, TemplatePrecheckRun, TemplateVersion
from apps.labtemplates.services import execute_precheck, publish_version, request_precheck
from apps.reviews.models import Rubric, RubricVersion
from apps.reviews.services import publish_rubric_version

from ...models import ExperimentTask, TaskExtensionRequest, TaskPublication
from ...services import create_publication, publish_publication, request_extension


class Command(BaseCommand):
    help = "Create disposable P06 publication, task, and extension data for local verification."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("P06 E2E seed is restricted to disposable environments")
        teacher = User.objects.filter(email="teacher.integration@example.edu").first()
        course = Course.objects.filter(code="P03-DEMO-001").first()
        if teacher is None or course is None:
            raise CommandError("Run seed_p02_e2e and seed_p03_e2e first")
        trace = secrets.token_hex(16)
        teaching = ActorContext(teacher.public_id, "TEACHING", trace)
        template_version = self._published_template_version(course, teacher, teaching)
        rubric_version = self._published_rubric_version(course, teacher, teaching)
        publication = TaskPublication.objects.filter(
            course=course,
            title="P06 个人实验任务",
        ).first()
        now = timezone.now()
        if publication is None:
            publication = create_publication(
                course_id=course.public_id,
                actor=teacher,
                data={
                    "template_version_id": template_version.public_id,
                    "rubric_version_id": rubric_version.public_id,
                    "title": "P06 个人实验任务",
                    "description": "用于本地发布、个人任务和延期流程验证。",
                    "audience_mode": TaskPublication.AudienceMode.ALL_ACTIVE,
                    "late_enrollment_policy": (
                        TaskPublication.LateEnrollmentPolicy.ASSIGN_UNTIL_DEADLINE
                    ),
                    "window_start": now - timezone.timedelta(hours=1),
                    "window_end": now + timezone.timedelta(days=7),
                    "assignment_deadline": now + timezone.timedelta(days=5),
                    "report_required": True,
                    "review_mode": TaskPublication.ReviewMode.MANUAL_WITH_AUTO_CHECK,
                    "prerequisites": [],
                },
                context=teaching,
            )
        if publication.status == TaskPublication.Status.DRAFT:
            publication, _ = publish_publication(
                course_id=course.public_id,
                publication_id=publication.public_id,
                actor=teacher,
                expected_version=publication.row_version,
                selected_ids=[],
                context=teaching,
            )
        student = User.objects.filter(email="student.integration@example.edu").first()
        task = (
            ExperimentTask.objects.filter(publication=publication, student=student).first()
            if student is not None
            else None
        )
        if task is not None and not TaskExtensionRequest.objects.filter(
            task=task,
            status=TaskExtensionRequest.Status.PENDING,
        ).exists():
            request_extension(
                task_id=task.public_id,
                actor=task.student,
                data={
                    "requested_deadline": publication.window_end + timezone.timedelta(days=2),
                    "reason": "P06 本地延期决定验证",
                },
                context=ActorContext(task.student.public_id, "USER", trace),
            )
        self.stdout.write(
            self.style.SUCCESS(
                "P06 E2E data ready: "
                f"course={course.public_id} publication={publication.public_id} "
                f"tasks={publication.tasks.count()}"
            )
        )

    @staticmethod
    def _published_template_version(
        course: Course, teacher: User, context: ActorContext
    ) -> TemplateVersion:
        template = Template.objects.filter(course=course, name="P05 容器实验模板").first()
        if template is None:
            raise CommandError("Run seed_p05_e2e first")
        version = template.versions.order_by("version_no").first()
        if version is None:
            raise CommandError("P05 template version is missing")
        if version.status in {TemplateVersion.Status.DRAFT, TemplateVersion.Status.PRECHECK_FAILED}:
            run = request_precheck(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=teacher,
                expected_version=version.row_version,
                context=context,
            )
            execute_precheck(run_id=run.public_id)
            version.refresh_from_db()
        elif version.status == TemplateVersion.Status.PRECHECKING:
            run = TemplatePrecheckRun.objects.filter(
                template_version=version,
                status__in=(
                    TemplatePrecheckRun.Status.QUEUED,
                    TemplatePrecheckRun.Status.RUNNING,
                    TemplatePrecheckRun.Status.RETRY,
                ),
            ).order_by("-created_at").first()
            if run is None:
                raise CommandError("P05 template precheck state is inconsistent")
            execute_precheck(run_id=run.public_id)
            version.refresh_from_db()
        if version.status == TemplateVersion.Status.PRECHECK_PASSED:
            version = publish_version(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=teacher,
                expected_version=version.row_version,
                context=context,
            )
        if version.status != TemplateVersion.Status.PUBLISHED:
            raise CommandError(f"Template version cannot be published: {version.status}")
        return version

    @staticmethod
    def _published_rubric_version(
        course: Course, teacher: User, context: ActorContext
    ) -> RubricVersion:
        rubric = Rubric.objects.filter(course=course, name="P05 实验评分量规").first()
        if rubric is None:
            raise CommandError("Run seed_p05_e2e first")
        version = rubric.versions.order_by("version_no").first()
        if version is None:
            raise CommandError("P05 rubric version is missing")
        if version.status == RubricVersion.Status.DRAFT:
            version = publish_rubric_version(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=teacher,
                expected_version=version.row_version,
                context=context,
            )
        if version.status != RubricVersion.Status.PUBLISHED:
            raise CommandError(f"Rubric version cannot be published: {version.status}")
        return version

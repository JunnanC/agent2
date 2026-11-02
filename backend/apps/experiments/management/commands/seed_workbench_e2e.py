import os
import re
import secrets
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.core.seed_names import rename_seed_labels
from apps.courses.models import Enrollment
from apps.courses.services import ActorContext

from ...models import ExperimentTask, TaskPublication
from ...services import create_publication, publish_publication


class Command(BaseCommand):
    help = "Create one disposable non-report task for the experiment workbench journey."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--run-id", required=True)

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("workbench E2E seed is restricted to disposable environments")
        rename_seed_labels()

        run_id = str(options["run_id"])
        if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", run_id) is None:
            raise CommandError(
                "--run-id must contain only letters, numbers, underscores, or dashes"
            )

        title = f"工作台集成验收实验 {run_id}"
        existing = (
            ExperimentTask.objects.select_related("student", "publication")
            .filter(publication__title=title, student__email="student.integration@example.edu")
            .first()
        )
        if existing is not None:
            if existing.status != ExperimentTask.Status.ASSIGNED:
                raise CommandError(
                    "Workbench E2E task already consumed: "
                    f"task={existing.public_id} status={existing.status}"
                )
            self._write_result(existing)
            return

        teacher = User.objects.filter(email="teacher.integration@example.edu").first()
        student = User.objects.filter(email="student.integration@example.edu").first()
        base = (
            TaskPublication.objects.select_related(
                "course", "template_version", "rubric_version"
            )
            .filter(title="个人实验任务", status=TaskPublication.Status.PUBLISHED)
            .first()
        )
        if teacher is None or student is None or base is None:
            raise CommandError("Create disposable accounts, courses and publications first")
        enrollment = Enrollment.objects.filter(
            course=base.course,
            student=student,
            status=Enrollment.Status.ACTIVE,
        ).first()
        if enrollment is None:
            raise CommandError(
                "The workbench student needs an active enrollment in the integration course"
            )

        now = timezone.now()
        context = ActorContext(teacher.public_id, "TEACHING", secrets.token_hex(16))
        publication = create_publication(
            course_id=base.course.public_id,
            actor=teacher,
            data={
                "template_version_id": base.template_version.public_id,
                "rubric_version_id": base.rubric_version.public_id,
                "title": title,
                "description": "验证环境装载、工作台、保存、测试、Agent 与非报告提交的完整旅程。",
                "audience_mode": TaskPublication.AudienceMode.SELECTED,
                "late_enrollment_policy": TaskPublication.LateEnrollmentPolicy.DO_NOT_ASSIGN,
                "window_start": now - timezone.timedelta(minutes=5),
                "window_end": now + timezone.timedelta(days=1),
                "assignment_deadline": now + timezone.timedelta(hours=12),
                "report_required": False,
                "review_mode": TaskPublication.ReviewMode.MANUAL_WITH_AUTO_CHECK,
                "prerequisites": [],
            },
            context=context,
        )
        publish_publication(
            course_id=base.course.public_id,
            publication_id=publication.public_id,
            actor=teacher,
            expected_version=publication.row_version,
            selected_ids=[enrollment.public_id],
            context=context,
        )
        task = ExperimentTask.objects.get(publication=publication, student=student)
        self._write_result(task)

    def _write_result(self, task: ExperimentTask) -> None:
        self.stdout.write(
            self.style.SUCCESS(
                f"Workbench E2E facts ready: task={task.public_id} title={task.publication.title} "
                f"status={task.status} report_required={task.publication.report_required}"
            )
        )

import os
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.courses.models import Course
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.reviews.models import AutoCheckRun, Review, ReviewDecision, RubricCriterion
from apps.reviews.services import decide_review, execute_auto_check, score_review_criteria

from ...models import ArchiveJob


class Command(BaseCommand):
    help = "Approve one disposable P10 review through services and trigger its P11 archive."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("P11 E2E seed is restricted to disposable environments")
        course = Course.objects.filter(code="P03-DEMO-001").first()
        teacher = User.objects.filter(email="teacher.integration@example.edu").first()
        student = User.objects.filter(email="student.integration@example.edu").first()
        if course is None or teacher is None or student is None:
            raise CommandError("Run seed_p02_e2e through seed_p10_e2e first")
        task = (
            ExperimentTask.objects.filter(course=course, student=student)
            .order_by("-created_at")
            .first()
        )
        if task is None:
            raise CommandError("P11 task is missing")
        existing = ArchiveJob.objects.filter(task=task).first()
        if existing is not None:
            self._success(existing)
            return
        review = Review.objects.filter(task=task).order_by("-round_no").first()
        if review is None:
            raise CommandError("Run seed_p10_e2e before seed_p11_e2e")
        trace_id = secrets.token_hex(16)
        context = ActorContext(teacher.public_id, "TEACHING", trace_id)
        for run in review.auto_check_runs.filter(status=AutoCheckRun.Status.QUEUED):
            execute_auto_check(run_id=run.public_id)
        review.refresh_from_db()
        criteria = list(
            RubricCriterion.objects.filter(
                rubric_version=review.rubric_version,
                is_active=True,
            ).order_by("position")
        )
        if not criteria:
            raise CommandError("P11 review has no active rubric criteria")
        review = score_review_criteria(
            course_id=course.public_id,
            review_id=review.public_id,
            actor=teacher,
            expected_version=review.row_version,
            scores=[
                {
                    "criterion_id": item.public_id,
                    "score": str(item.max_score),
                    "note": "P11 verified archive seed",
                }
                for item in criteria
            ],
            context=context,
        )
        total = sum((item.max_score for item in criteria), Decimal("0"))
        decide_review(
            course_id=course.public_id,
            review_id=review.public_id,
            actor=teacher,
            expected_version=review.row_version,
            decision=ReviewDecision.Decision.APPROVE,
            requested_score=total,
            feedback="P11 归档验收通过。",
            context=context,
        )
        job = ArchiveJob.objects.get(task=task)
        self._success(job)

    def _success(self, job: ArchiveJob) -> None:
        self.stdout.write(
            self.style.SUCCESS(
                f"P11 E2E archive queued: course={job.course.public_id} "
                f"task={job.task.public_id} archive={job.public_id} status={job.status}"
            )
        )

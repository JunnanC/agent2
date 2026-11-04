import os
import secrets

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from apps.accounts.models import User
from apps.core.seed_names import rename_seed_labels
from apps.courses.models import Course, Enrollment
from apps.courses.services import ActorContext, apply_for_course, review_enrollment
from apps.experiments.models import ExperimentTask, TaskPublication
from apps.experiments.services import assign_late_enrollment_task
from apps.provisioning.models import ProvisioningJob
from apps.provisioning.services import execute_provisioning_job, start_provisioning
from apps.reports.models import ReportDraft
from apps.reports.services import submit_report, update_report_draft
from apps.workspaces.models import WorkspaceAutosaveLog
from apps.workspaces.services import enter_task, save_snapshot

from ...models import Review


class Command(BaseCommand):
    help = "Create disposable review, auto-check, and similarity facts."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("review E2E seed is restricted to disposable environments")
        rename_seed_labels()
        course = Course.objects.filter(code="P03-DEMO-001").first()
        student = User.objects.filter(email="student.integration@example.edu").first()
        publication = TaskPublication.objects.filter(
            course=course, title="个人实验任务", status=TaskPublication.Status.PUBLISHED
        ).first()
        if course is None or student is None or publication is None:
            raise CommandError("Run seed_accounts_e2e through seed_workspaces_e2e first")
        trace_id = secrets.token_hex(16)
        primary_task = ExperimentTask.objects.filter(
            publication=publication, student=student
        ).first()
        if primary_task is None:
            raise CommandError("Primary publication task is missing")
        primary_review = self._prepare_submission(
            primary_task,
            "# 教师审核\n\n相同实验步骤、数据处理和结果分析用于相似度验证。",
            trace_id,
        )

        peer = self._peer_user()
        enrollment = Enrollment.objects.filter(
            course=course, student=peer, status=Enrollment.Status.ACTIVE
        ).first()
        if enrollment is None:
            enrollment = Enrollment.objects.filter(
                course=course, student=peer, status="PENDING"
            ).first()
            enrollment = enrollment or apply_for_course(
                course_id=course.public_id,
                student=peer,
                application_message="report similarity candidate",
                context=ActorContext(peer.public_id, "USER", trace_id),
            )
            enrollment = review_enrollment(
                course_id=course.public_id, enrollment_id=enrollment.public_id,
                decision="APPROVE", note="Review E2E seed", actor=course.owner,
                expected_version=enrollment.row_version,
                context=ActorContext(course.owner.public_id, "TEACHING", trace_id),
            )
        # Reuse an existing task before asking the assignment service to create one.
        # This keeps the disposable seed idempotent even when a previous run already
        # assigned the late-enrollment candidate.
        peer_task = ExperimentTask.objects.filter(publication=publication, student=peer).first()
        if peer_task is None:
            peer_task = assign_late_enrollment_task(
                enrollment_id=enrollment.public_id,
                publication_id=publication.public_id,
                context=ActorContext(peer.public_id, "USER", trace_id),
            )
        if peer_task is None:
            raise CommandError("Could not assign the review similarity candidate task")
        peer_review = self._prepare_submission(
            peer_task,
            "# 教师审核\n\n相同实验步骤、数据处理和结果分析用于相似度验证，并补充结论。",
            trace_id,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Review E2E facts ready: course={course.public_id} "
                f"primary_review={primary_review.public_id} peer_review={peer_review.public_id}"
            )
        )

    @staticmethod
    def _peer_user() -> User:
        user = User.objects.filter(email="p10-peer.integration@example.edu").first()
        if user is not None:
            return user
        return User.objects.create(
            email="p10-peer.integration@example.edu",
            username="p10-integration-peer",
            display_name="报告相似度验证学生",
            password=make_password(secrets.token_urlsafe(32)),
        )

    @staticmethod
    def _prepare_submission(task: ExperimentTask, body: str, trace_id: str) -> Review:
        existing = Review.objects.filter(task=task).order_by("-round_no").first()
        if existing is not None:
            return existing
        context = ActorContext(task.student.public_id, "USER", trace_id)
        if task.status == ExperimentTask.Status.ASSIGNED:
            task, job = start_provisioning(
                task_id=task.public_id,
                actor=task.student,
                expected_version=task.row_version,
                context=context,
            )
            execute_provisioning_job(job_id=job.public_id, trace_id=trace_id)
            task.refresh_from_db()
        elif task.status == ExperimentTask.Status.PROVISIONING:
            job = ProvisioningJob.objects.filter(task=task).order_by("-attempt_no").first()
            if job is None:
                raise CommandError("Provisioning task has no job")
            execute_provisioning_job(job_id=job.public_id, trace_id=trace_id)
            task.refresh_from_db()
        if task.status not in {
            ExperimentTask.Status.READY,
            ExperimentTask.Status.IN_PROGRESS,
            ExperimentTask.Status.REPORT_DRAFT,
        }:
            raise CommandError(f"Task cannot enter the review report flow: {task.status}")
        task, session, token = enter_task(
            task_id=task.public_id,
            actor=task.student,
            expected_version=task.row_version,
            context=context,
        )
        client_seq = (
            WorkspaceAutosaveLog.objects.filter(task=task).aggregate(value=Max("client_seq"))[
                "value"
            ]
            or 0
        ) + 1
        session, _snapshot, _result = save_snapshot(
            task_id=task.public_id,
            actor=task.student,
            token=token,
            client_seq=client_seq,
            base_version=session.current_version,
            upload=SimpleUploadedFile(
                "review-workspace.txt",
                b"Reproducible review workspace output",
                content_type="text/plain",
            ),
            context=context,
        )
        draft = ReportDraft.objects.get(task=task)
        update_report_draft(
            task_id=task.public_id,
            actor=task.student,
            body_markdown=body,
            expected_version=draft.row_version,
            context=context,
        )
        task.refresh_from_db()
        submit_report(
            task_id=task.public_id,
            actor=task.student,
            expected_task_version=task.row_version,
            context=context,
        )
        return Review.objects.get(task=task, round_no=1)

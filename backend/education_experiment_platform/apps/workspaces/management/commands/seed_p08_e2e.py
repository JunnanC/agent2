import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.provisioning.models import ProvisioningInstance
from apps.provisioning.services import execute_provisioning_job, start_provisioning


class Command(BaseCommand):
    help = "Validate disposable P07 facts for the P08 workspace journey."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("P08 E2E seed is restricted to disposable environments")
        student = User.objects.filter(email="student.integration@example.edu").first()
        if student is None:
            raise CommandError("Run seed_p02_e2e through seed_p07_e2e first")
        instance = (
            ProvisioningInstance.objects.filter(
                task__student=student,
                task__publication__title="P07 FakeRuntime 任务",
                task__runtime_adapter_driver="FAKE",
                status=ProvisioningInstance.Status.READY,
            )
            .select_related("task", "task__course", "task__enrollment")
            .order_by("-ready_at", "-created_at")
            .first()
        )
        if instance is None:
            task = (
                ExperimentTask.objects.filter(student=student)
                .filter(publication__title="P07 FakeRuntime 任务")
                .filter(runtime_adapter_driver="FAKE")
                .select_related("course", "enrollment")
                .order_by("-created_at")
                .first()
            )
            if task is None:
                raise CommandError("No experiment task found; run seed_p06_e2e first")
            if task.status == ExperimentTask.Status.ASSIGNED:
                context = ActorContext(student.public_id, "USER", secrets.token_hex(16))
                _, job = start_provisioning(
                    task_id=task.public_id,
                    actor=student,
                    expected_version=task.row_version,
                    context=context,
                )
                execute_provisioning_job(job_id=job.public_id)
            elif task.status == ExperimentTask.Status.PROVISIONING:
                job = task.provisioning_jobs.order_by("-attempt_no").first()
                if job is not None:
                    execute_provisioning_job(job_id=job.public_id)
            task.refresh_from_db()
            instance = ProvisioningInstance.objects.filter(task=task).first()
        if instance is None or instance.status != ProvisioningInstance.Status.READY:
            raise CommandError("The selected task has no READY FakeRuntime instance")
        task = instance.task
        self.stdout.write(
            self.style.SUCCESS(
                f"P08 E2E facts ready: task={task.public_id} session_scope=USER "
                f"instance={instance.public_id} status={instance.status}"
            )
        )

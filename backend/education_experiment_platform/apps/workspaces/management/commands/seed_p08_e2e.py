import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.experiments.models import ExperimentTask
from apps.provisioning.models import ProvisioningInstance


class Command(BaseCommand):
    help = "Validate disposable P07 facts for the P08 workspace journey."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("P08 E2E seed is restricted to disposable environments")
        student = User.objects.filter(email="student.integration@example.edu").first()
        if student is None:
            raise CommandError("Run seed_p02_e2e through seed_p07_e2e first")
        task = (
            ExperimentTask.objects.filter(student=student)
            .select_related("course", "enrollment")
            .order_by("-created_at")
            .first()
        )
        if task is None:
            raise CommandError("No experiment task found; run seed_p06_e2e first")
        instance = ProvisioningInstance.objects.filter(task=task).first()
        if instance is None or instance.status != ProvisioningInstance.Status.READY:
            raise CommandError("The selected task has no READY FakeRuntime instance")
        self.stdout.write(
            self.style.SUCCESS(
                f"P08 E2E facts ready: task={task.public_id} session_scope=USER "
                f"instance={instance.public_id} status={instance.status}"
            )
        )

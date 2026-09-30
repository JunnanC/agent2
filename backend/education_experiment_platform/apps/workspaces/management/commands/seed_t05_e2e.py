import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.courses.services import ActorContext
from apps.provisioning.models import ProvisioningInstance

from ...services import enter_task, record_operation


class Command(BaseCommand):
    help = "Create one disposable T05 workspace execution run from the P08 seed facts."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("T05 E2E seed is restricted to disposable environments")
        student = User.objects.filter(email="student.integration@example.edu").first()
        if student is None:
            raise CommandError("Run seed_p02_e2e through seed_p08_e2e first")
        instance = (
            ProvisioningInstance.objects.filter(
                task__student=student, status=ProvisioningInstance.Status.READY
            )
            .select_related("task")
            .order_by("-ready_at", "-created_at")
            .first()
        )
        if instance is None:
            raise CommandError("No READY workspace instance found; run seed_p08_e2e first")
        task = instance.task
        context = ActorContext(student.public_id, "USER", secrets.token_hex(16))
        _, session, token = enter_task(
            task_id=task.public_id,
            actor=student,
            expected_version=task.row_version,
            context=context,
        )
        event = record_operation(
            session=session,
            token=token,
            actor=student,
            operation="RUN_CHECK",
            arguments={"source": "seed_t05_e2e"},
            request_key=f"seed-t05:{task.public_id}",
            context=context,
        )
        execution_id = str(event.payload_masked.get("execution_run_id", ""))
        self.stdout.write(
            self.style.SUCCESS(
                f"T05 execution facts ready: task={task.public_id} session={session.public_id} "
                f"execution_run={execution_id} "
                f"status={event.payload_masked.get('execution_status', '')}"
            )
        )

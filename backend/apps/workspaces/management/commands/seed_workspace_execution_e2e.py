import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.courses.services import ActorContext
from apps.provisioning.models import ProvisioningInstance

from ...services import enter_task, record_operation


class Command(BaseCommand):
    help = "Create a disposable execution run from the workspace seed facts."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("Workspace execution seed requires a disposable environment")
        student = User.objects.filter(email="student.integration@example.edu").first()
        if student is None:
            raise CommandError("Run seed_accounts_e2e through seed_workspaces_e2e first")
        instance = (
            ProvisioningInstance.objects.filter(
                task__student=student, status=ProvisioningInstance.Status.READY
            )
            .select_related("task")
            .order_by("-ready_at", "-created_at")
            .first()
        )
        if instance is None:
            raise CommandError("No READY workspace instance found; run seed_workspaces_e2e first")
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
            arguments={"source": "seed_workspace_execution_e2e"},
            request_key=f"seed-t05:{task.public_id}",
            context=context,
        )
        execution_id = str(event.payload_masked.get("execution_run_id", ""))
        self.stdout.write(
            self.style.SUCCESS(
                f"Workspace execution facts ready: task={task.public_id} "
                f"session={session.public_id} "
                f"execution_run={execution_id} "
                f"status={event.payload_masked.get('execution_status', '')}"
            )
        )

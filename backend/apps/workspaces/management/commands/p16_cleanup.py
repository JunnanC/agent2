"""Finalize and destroy the disposable P16 runtime after evidence capture."""

from __future__ import annotations

import secrets
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.provisioning.adapters import runtime_for_driver
from apps.provisioning.models import ProvisioningInstance
from apps.provisioning.services import destroy_task_instance

from ...services import revoke_task_sessions


class Command(BaseCommand):
    help = "Finalize workspace storage and destroy a disposable P16 runtime."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--title", required=True)

    def handle(self, *args: object, **options: object) -> None:
        task = ExperimentTask.objects.filter(
            publication__title=str(options["title"]),
            student__email="student.integration@example.edu",
        ).first()
        if task is None:
            raise CommandError("P16 task not found")
        existing_instance = (
            ProvisioningInstance.objects.select_related("runtime_adapter")
            .filter(task=task)
            .first()
        )
        context = ActorContext("p16-storage-cleanup", "WORKER", secrets.token_hex(16))
        instance = None
        if existing_instance is not None:
            instance = destroy_task_instance(
                task_id=task.public_id,
                idempotency_key=f"p16-cleanup:{task.public_id}",
                context=context,
            )
        revoke_task_sessions(
            task_id=task.public_id,
            reason="P16 disposable journey cleanup",
            context=context,
        )
        if instance is not None:
            adapter = runtime_for_driver(
                instance.runtime_adapter.driver,
                config_ref=instance.runtime_adapter.config_ref,
            )
            for resource in adapter.inventory_resources():
                if (
                    resource.metadata.get("kind") == "volume"
                    and resource.metadata.get("task_id") == task.public_id
                ):
                    adapter.destroy_resource(
                        resource.external_id,
                        f"p16-volume-cleanup:{task.public_id}",
                    )
        self.stdout.write(
            self.style.SUCCESS(
                f"P16 cleanup complete: task={task.public_id} "
                f"instance_status={instance.status if instance else 'MISSING'}"
            )
        )

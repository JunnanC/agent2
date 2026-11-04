"""Probe the real workspace runtime's instance-level upstream-token boundary."""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx
from django.core.management.base import BaseCommand, CommandError

from apps.core.workspace_tokens import workspace_upstream_token
from apps.experiments.models import ExperimentTask
from apps.provisioning.models import ProvisioningInstance


class Command(BaseCommand):
    help = "Verify correct, invalid, and cross-task-derived real workspace upstream tokens."

    def add_arguments(self, parser: Any) -> None:
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--title")
        scope.add_argument("--task-id")

    def handle(self, *args: object, **options: object) -> None:
        if options.get("task_id"):
            task = ExperimentTask.objects.filter(public_id=options["task_id"]).first()
        else:
            task = ExperimentTask.objects.filter(
                publication__title=options["title"],
                student__email="student.integration@example.edu",
            ).first()
        if task is None:
            raise CommandError("real workspace task not found")
        instance = ProvisioningInstance.objects.filter(task=task).first()
        if instance is None or not instance.endpoint or not instance.external_id:
            raise CommandError("real workspace runtime instance is not ready")
        spec_digest = str((instance.external_metadata or {}).get("spec_digest", ""))
        if len(spec_digest) != 64:
            raise CommandError("real workspace runtime spec digest is unavailable")
        correct = workspace_upstream_token(
            instance_id=instance.public_id,
            task_id=task.public_id,
            spec_digest=spec_digest,
        )
        cross_task = workspace_upstream_token(
            instance_id=instance.public_id,
            task_id=f"{task.public_id}-other",
            spec_digest=spec_digest,
        )
        url = f"{instance.endpoint.rstrip('/')}/webide/"
        statuses: dict[str, int] = {}
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            for name, token in (
                ("correct", correct),
                ("invalid", "invalid-upstream-token-value"),
                ("cross_task", cross_task),
            ):
                statuses[name] = client.get(
                    url,
                    headers={"X-Workspace-Upstream-Token": token},
                ).status_code
        if statuses["correct"] not in {200, 302, 307, 308}:
            raise CommandError(f"Correct upstream token was rejected: {statuses['correct']}")
        if statuses["invalid"] != 403 or statuses["cross_task"] != 403:
            raise CommandError("Invalid or cross-task upstream token was not rejected")
        json.dump(
            {
                "task_id": task.public_id,
                "instance_id": instance.public_id,
                "correct_status": statuses["correct"],
                "invalid_status": statuses["invalid"],
                "cross_task_status": statuses["cross_task"],
            },
            sys.stdout,
            ensure_ascii=True,
            sort_keys=True,
        )
        sys.stdout.write("\n")

"""Emit redacted, digest-only evidence for the P16 local journey."""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.experiments.models import ExperimentTask
from apps.provisioning.adapters import RuntimeAdapterFailure, runtime_for_driver
from apps.provisioning.models import ProvisioningInstance

from ...models import WorkspaceSession, WorkspaceSnapshot, WorkspaceStorageJob
from ...storage import _read_object


class Command(BaseCommand):
    help = "Emit P16 digest-only local Docker journey evidence."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--title", required=True)

    def handle(self, *args: object, **options: object) -> None:
        title = str(options["title"])
        task = (
            ExperimentTask.objects.select_related("runtime_adapter", "image")
            .filter(publication__title=title, student__email="student.integration@example.edu")
            .first()
        )
        if task is None:
            raise CommandError("P16 task not found")
        instance = (
            ProvisioningInstance.objects.select_related("runtime_adapter").filter(task=task).first()
        )
        session = WorkspaceSession.objects.filter(task=task).order_by("-created_at").first()
        latest = (
            WorkspaceSnapshot.objects.select_related("asset")
            .filter(task=task)
            .order_by("-version_no")
            .first()
        )
        jobs = list(
            WorkspaceStorageJob.objects.filter(task=task)
            .order_by("created_at")
            .values(
                "public_id", "kind", "status", "result_snapshot_id", "failure_record__error_code"
            )
        )
        result: dict[str, object] = {
            "phase": "P16-F",
            "task_id": task.public_id,
            "task_status": task.status,
            "instance_id": instance.public_id if instance else None,
            "instance_status": instance.status if instance else None,
            "external_id_present": bool(instance and instance.external_id),
            "session_id": session.public_id if session else None,
            "session_status": session.status if session else None,
            "latest_snapshot_id": latest.public_id if latest else None,
            "latest_snapshot_version": latest.version_no if latest else None,
            "latest_snapshot_digest": latest.digest_sha256 if latest else None,
            "latest_asset_digest": latest.asset.digest_sha256 if latest else None,
            "storage_jobs": jobs,
        }
        if latest is not None:
            value = _read_object(latest.asset)
            result["minio_object_digest"] = hashlib.sha256(value).hexdigest()
            result["minio_object_size"] = len(value)
        if instance is not None and instance.external_id:
            driver = instance.runtime_adapter.driver
            adapter = runtime_for_driver(driver, config_ref=instance.runtime_adapter.config_ref)
            try:
                artifact = adapter.capture_workspace(
                    external_id=instance.external_id,
                    relative_path="main.py",
                    max_bytes=int(getattr(settings, "WORKSPACE_MAX_FILE_BYTES", 1_048_576)),
                )
                result["runtime_file_digest"] = artifact.digest
                result["runtime_file_size"] = artifact.size
            except RuntimeAdapterFailure as exc:
                result["runtime_capture_error"] = exc.code
        json.dump(result, sys.stdout, ensure_ascii=True, sort_keys=True)
        sys.stdout.write("\n")

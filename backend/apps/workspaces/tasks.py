"""Durable workspaces for the assessment runtime queue."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from celery import shared_task
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from apps.core.concurrency import compare_and_swap
from apps.experiments.assessment_parts import INACTIVE_TASKS, part_open
from apps.experiments.assessment_workers import _executor
from apps.experiments.models import CodeDraft

from .models import StudentWorkspace
from .runtime import WorkspaceRuntime

logger = logging.getLogger(__name__)


@contextmanager
def workspace_runtime(workspace: StudentWorkspace) -> Iterator[WorkspaceRuntime]:
    client, executor = _executor(workspace.task, workspace.container_name)
    try:
        yield WorkspaceRuntime(executor, workspace)
    finally:
        client.close()


def sync_drafts(runtime: WorkspaceRuntime, container: Any, workspace: StudentWorkspace) -> None:
    timestamp = timezone.now()
    drafts = list(CodeDraft.objects.filter(task=workspace.task).select_related("question"))
    runtime.sync(container, drafts)
    compare_and_swap(
        StudentWorkspace,
        pk=workspace.pk,
        expected_version=workspace.row_version,
        changes={"synced_at": timestamp, "status": StudentWorkspace.Status.RUNNING},
    )


@shared_task(name="apps.workspaces.sync_student_workspace")
def sync_student_workspace(workspace_id: int) -> None:
    with transaction.atomic():
        workspace = StudentWorkspace.objects.select_for_update().filter(pk=workspace_id).first()
        if workspace is None:
            return
        if not part_open(workspace.task, workspace.expires_at):
            if workspace.status != StudentWorkspace.Status.EXPIRED:
                with workspace_runtime(workspace) as runtime:
                    runtime.remove()
                compare_and_swap(
                    StudentWorkspace,
                    pk=workspace.pk,
                    expected_version=workspace.row_version,
                    changes={"status": StudentWorkspace.Status.EXPIRED},
                )
            return
        try:
            with workspace_runtime(workspace) as runtime:
                sync_drafts(runtime, runtime.ensure(), workspace)
        except Exception:
            logger.exception("Student workspace could not be prepared", extra={"id": workspace_id})
            compare_and_swap(
                StudentWorkspace,
                pk=workspace.pk,
                expected_version=workspace.row_version,
                changes={"status": StudentWorkspace.Status.FAILED},
            )


@shared_task(name="apps.workspaces.dispatch_student_workspaces")
def dispatch_student_workspaces() -> None:
    now = timezone.now()
    dirty = CodeDraft.objects.filter(
        task_id=OuterRef("task_id"),
        updated_at__gt=OuterRef("synced_at"),
    )
    rows = (
        StudentWorkspace.objects.annotate(dirty=Exists(dirty))
        .filter(
            Q(status="PENDING")
            | Q(status="RUNNING", dirty=True)
            | Q(expires_at__lte=now)
            | Q(task__publication__status="WITHDRAWN")
            | Q(
                task__publication__status="CLOSED",
                expires_at__lte=F("task__publication__window_end"),
            )
            | Q(task__status__in=INACTIVE_TASKS)
            | ~Q(task__enrollment__status="ACTIVE")
        )
        .exclude(status="EXPIRED")
        .order_by("updated_at")
    )
    for workspace_id in rows.values_list("pk", flat=True)[:100]:
        sync_student_workspace.delay(workspace_id)

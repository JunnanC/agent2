"""Leased assessment jobs; persisted rows recover broker failures and stale deliveries."""

import hashlib
import time
import uuid
from datetime import timedelta
from typing import Any

import docker
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.audit import append_failure
from apps.core.concurrency import compare_and_swap
from apps.core.models import ObjectAsset
from apps.core.object_storage import object_storage
from apps.core.project_archive import unpack
from apps.courses.services import ActorContext
from apps.governance.models import QuotaReservation
from apps.governance.services import release_reservation, reserve_quota
from apps.provisioning.assessment_judge import grade_groups, read_private_tests, validated_groups
from apps.provisioning.services import release_runtime_capacity, reserve_runtime_capacity
from apps.provisioning.stdio import StdioExecutor

from .models import AssessmentRun, QuestionGrade


def _claim(model: Any, pk: int) -> Any:
    with transaction.atomic():
        row = model.objects.select_for_update().get(pk=pk)
        now = timezone.now()
        if row.status == "COMPLETED" or (
            row.status == "RUNNING" and row.lease_until and row.lease_until > now
        ):
            return None
        if row.attempt_count >= 5:
            return None
        if row.status == "RETRY" and row.updated_at > now - timedelta(seconds=30):
            return None
        return compare_and_swap(
            model, pk=row.pk, expected_version=row.row_version,
            changes={
                "status": "RUNNING", "lease_token": uuid.uuid4(),
                "lease_until": now + timedelta(minutes=30), "attempt_count": row.attempt_count + 1,
            },
        )


def _finish(row: Any, **changes: Any) -> None:
    with transaction.atomic():
        task = None
        if isinstance(row, QuestionGrade):
            from .models import ExperimentTask

            task = ExperimentTask.objects.select_for_update().get(
                pk=row.answer.submission.section.task_id,
            )
        current = type(row).objects.select_for_update().get(pk=row.pk)
        if current.lease_token != row.lease_token or current.status != "RUNNING":
            return
        compare_and_swap(
            type(row), pk=current.pk, expected_version=current.row_version,
            changes={**changes, "lease_token": None, "lease_until": None},
        )
        if isinstance(current, QuestionGrade) and changes.get("status") == "COMPLETED":
            from .assessment import sync_assessment_status
            from .models import ExperimentTask

            submission = current.answer.submission
            if submission.section.current_submission_id == submission.pk and task is not None:
                sync_assessment_status(task)


def _read_source(snapshot: Any) -> dict[str, str]:
    asset = snapshot.asset
    if asset.status != "ACTIVE" or asset.scan_status != "CLEAN":
        raise RuntimeError("Assessment source unavailable")
    stored = object_storage().open_object(
        bucket=asset.bucket, object_key=asset.object_key, version_id=asset.object_version,
    )
    try:
        source = stored.body.read(settings.WORKSPACE_SNAPSHOT_MAX_BYTES + 1)
    finally:
        stored.body.close()
    if (
        len(source) != snapshot.size_bytes
        or hashlib.sha256(source).hexdigest() != snapshot.digest_sha256
    ):
        raise RuntimeError("Assessment source digest mismatch")
    return {path: value.decode("utf-8") for path, value in unpack(
        source, max_bytes=settings.WORKSPACE_SNAPSHOT_MAX_BYTES, require_manifest=True,
    ).items()}


def _executor(task: Any, owner: str) -> tuple[Any, StdioExecutor]:
    if task.runtime_adapter_driver != "DOCKER_LOCAL" or settings.LOCAL_RUNTIME_MODE != "REAL":
        raise RuntimeError("Assessment requires a real Docker Local executor")
    configs = settings.RUNTIME_ADAPTER_CONFIGS
    config = configs.get(task.runtime_adapter_config_ref, {})
    host = config.get("base_url", config.get("docker_host", settings.LOCAL_DOCKER_HOST))
    client = docker.DockerClient(base_url=host, timeout=30)
    image_ref = f"{task.image_registry.rstrip('/')}/{task.image_repository}@{task.image_digest}"
    if image_ref.startswith("docker.io/library/"):
        image_ref = image_ref.removeprefix("docker.io/library/")
    try:
        client.images.get(image_ref)
    except Exception:
        client.close()
        raise
    return client, StdioExecutor(client, image_ref, owner=owner)


@transaction.atomic
def _admit(task: Any, owner: str, memory: int) -> QuotaReservation:
    context = ActorContext("assessment-worker", "WORKER", owner[:32])
    reservation = reserve_quota(
        reservation_key=owner, reservation_type="STANDARD", subject_type="ASSESSMENT",
        subject_ref=task.public_id, course_id=task.course.public_id, user_id=task.student.public_id,
        resource_profile_id=task.resource_profile.public_id,
        values={"instance_count": 1, "cpu_millicores": 1000, "memory_mb": memory, "disk_gb": 1},
        expires_at=timezone.now() + timedelta(minutes=60), context=context,
    )
    reserve_runtime_capacity(
        reservation_id=reservation, runtime_adapter_id=task.runtime_adapter.public_id,
        cpu_millicores=1000, memory_mb=memory,
    )
    return reservation


@transaction.atomic
def _release(reservation: QuotaReservation, owner: str) -> None:
    release_runtime_capacity(reservation_id=reservation)
    release_reservation(
        reservation_id=reservation.public_id, reason="assessment execution finished",
        context=ActorContext("assessment-worker", "WORKER", owner[:32]),
    )


def execute_assessment_job(*, pk: int, formal: bool) -> None:
    model = QuestionGrade if formal else AssessmentRun
    row = _claim(model, pk)
    if row is None:
        return
    if formal:
        answer = row.answer
        task = answer.submission.section.task
        question, snapshot = answer.question, answer.code_snapshot
    else:
        task, question, snapshot = row.task, row.question, row.snapshot
    owner = f"assessment-{row.lease_token}"
    executor = client = reservation = None
    try:
        limits = question.question_spec["limits"][snapshot.language]
        reservation = _admit(task, owner, max(1024, limits["memory_mb"]))
        client, executor = _executor(task, owner)
        files = _read_source(snapshot)
        if formal:
            asset, data = read_private_tests(
                asset_id=question.marking_spec["tests_asset_id"],
                template_version_id=task.template_version.public_id,
            )
            if asset.digest_sha256 != question.execution_snapshot.get("tests_digest"):
                raise RuntimeError("Published assessment tests digest mismatch")
            groups = validated_groups(data, question.marking_spec["groups"])
            result = grade_groups(
                executor=executor, language=snapshot.language, files=files,
                groups=groups, scores=question.marking_spec["groups"], limits=limits,
            )
            result["tests_digest"] = asset.digest_sha256
            changes = {"status": "COMPLETED", "score": result["score"], "private_result": result}
        else:
            compilation, results = executor.execute(
                language=snapshot.language, files=files, inputs=[row.stdin], **limits,
            )
            execution_result = compilation or results[0]
            changes = {
                "status": "COMPLETED", "stdout": execution_result.stdout,
                "stderr": execution_result.stderr,
                "result_status": "COMPILE_ERROR" if compilation else execution_result.status,
            }
        executor.close()
        executor = None
        _release(reservation, owner)
        reservation = None
        _finish(row, **changes)
    except Exception:
        _finish(row, status="RETRY")
        append_failure(
            failure_type="ASSESSMENT_EXECUTION", subject_type="QUESTION_GRADE" if formal else "RUN",
            subject_ref=str(row.pk), error_code="ASSESSMENT_PLATFORM_FAILURE",
            message="Assessment execution requires retry", detail={"formal": formal},
            retryable=True, trace_id=owner[:32],
        )
        raise
    finally:
        try:
            if executor:
                executor.close()
            if reservation:
                _release(reservation, owner)
        finally:
            if client:
                client.close()


@shared_task(name="apps.experiments.cleanup_assessment_resources")
def cleanup_assessment_resources() -> int:
    """Reclaim expired managed resources after crashes, then release their quota bindings."""
    hosts = {settings.LOCAL_DOCKER_HOST}
    for config in settings.RUNTIME_ADAPTER_CONFIGS.values():
        if isinstance(config, dict) and (config.get("base_url") or config.get("docker_host")):
            hosts.add(config.get("base_url") or config["docker_host"])
    cleaned = 0
    for host in hosts:
        client = docker.DockerClient(base_url=host, timeout=30)
        try:
            owners = set()
            filters = {"label": [
                "edu.platform.managed=true", "edu.platform.kind=assessment-stdio",
            ]}
            for container in client.containers.list(all=True, filters=filters):
                labels = container.labels
                if int(labels.get("edu.platform.expires_at", "0")) > time.time():
                    continue
                container.remove(force=True)
                owners.add(labels.get("edu.platform.assessment", ""))
                cleaned += 1
            for volume in client.volumes.list(filters=filters):
                labels = volume.attrs.get("Labels") or {}
                if int(labels.get("edu.platform.expires_at", "0")) > time.time():
                    continue
                volume.remove(force=True)
                owners.add(labels.get("edu.platform.assessment", ""))
                cleaned += 1
            for owner in owners:
                reservation = QuotaReservation.objects.filter(
                    reservation_key=owner, subject_type="ASSESSMENT", status="ACTIVE",
                ).first()
                if reservation:
                    _release(reservation, owner)
        finally:
            client.close()
    # A crashed worker can leave only the admission record, with no Docker resources.
    for reservation in QuotaReservation.objects.filter(
        Q(status="ACTIVE") | Q(runtime_capacity_binding__status="ACTIVE"),
        subject_type="ASSESSMENT", expires_at__lte=timezone.now(),
    ):
        _release(reservation, reservation.reservation_key)
    return cleaned


@shared_task(name="apps.experiments.cleanup_assessment_objects")
def cleanup_assessment_objects() -> int:
    """Recover uploads whose database transaction rolled back or process crashed."""
    storage = object_storage()
    cutoff = timezone.now() - timedelta(hours=1)
    removed = 0
    for prefix in ("assessment/", "assessment-tests/"):
        pages = storage.client.get_paginator("list_object_versions").paginate(
            Bucket=settings.MINIO_BUCKET, Prefix=prefix,
        )
        for page in pages:
            for version in page.get("Versions", []):
                if version["LastModified"] > cutoff:
                    continue
                if ObjectAsset.objects.filter(
                    bucket=settings.MINIO_BUCKET, object_key=version["Key"],
                    object_version=version["VersionId"],
                ).exists():
                    continue
                storage.delete_object(
                    bucket=settings.MINIO_BUCKET, object_key=version["Key"],
                    version_id=version["VersionId"],
                )
                removed += 1
    return removed


@shared_task(name="apps.experiments.dispatch_assessments")
def dispatch_assessments() -> int:
    now = timezone.now()
    count = 0
    for model, formal in ((QuestionGrade, True), (AssessmentRun, False)):
        rows = model.objects.filter(
            Q(status__in=("PENDING", "RETRY")) | Q(status="RUNNING", lease_until__lt=now),
            attempt_count__lt=5,
        ).order_by("created_at")[:100]
        for row in rows:
            run_assessment_job.apply_async(
                kwargs={"pk": row.pk, "formal": formal}, queue="q_provision",
            )
            count += 1
    return count


@shared_task(name="apps.experiments.archive_closed_assessments")
def archive_closed_assessments() -> int:
    from apps.archives.services import request_task_archive

    from .assessment import assessment_results
    from .models import ExperimentTask

    tasks = ExperimentTask.objects.filter(
        publication__status__in=("CLOSED", "WITHDRAWN"),
        publication__chapter_snapshots__task_snapshots__task_type__in=(
            "SINGLE_CHOICE", "MULTIPLE_CHOICE", "PROGRAMMING",
        ),
    ).exclude(status__in=("ARCHIVING", "DESTROYING", "COMPLETED", "CANCELLED", "EXPIRED"))
    count = 0
    for task in tasks.distinct()[:100]:
        results = assessment_results(task, student=False)
        if task.publication.status == "CLOSED" and any(r["score"] is None for r in results):
            continue
        with transaction.atomic():
            request_task_archive(
                task_id=task.public_id,
                terminal_target="COMPLETED" if task.publication.status == "CLOSED" else "CANCELLED",
                trigger="ASSESSMENT_CLOSED", context=ActorContext(
                    "assessment-archive", "WORKER", "assessment-archive",
                ),
            )
        count += 1
    return count


@shared_task(name="apps.experiments.run_assessment_job")
def run_assessment_job(*, pk: int, formal: bool) -> None:
    execute_assessment_job(pk=pk, formal=formal)

"""Read-only aggregation for the student experiment workbench."""

from collections.abc import Iterable
from typing import Any

from apps.accounts.models import User
from apps.core.models import ObjectAsset
from apps.experiments.models import ExperimentTask
from apps.experiments.services import allowed_actions, prerequisite_blockers_for_publication
from apps.labtemplates.errors import TemplateAssetNotReady
from apps.labtemplates.models import AutoCheckRule, TemplateVersion
from apps.labtemplates.toolchains import TOOLCHAINS_BY_LANGUAGE
from apps.provisioning.models import ProvisioningJob, ProvisioningStageEvent
from apps.reports.models import ReportDraft

from .models import WorkspaceExecutionRun, WorkspaceSession, WorkspaceSnapshot
from .presentation import asset_text, public_examples
from .selectors import active_storage_job_for_user, workbench_task_for_user
from .serializers import storage_job_data
from .services import task_has_active_test_rules

PUBLIC_STAGES = tuple(ProvisioningJob.Stage.values)
_ACTIVE_TASK_STATUSES = {
    ExperimentTask.Status.IN_PROGRESS,
    ExperimentTask.Status.REPORT_DRAFT,
}


def _asset_id(asset: ObjectAsset | None, *, version: TemplateVersion, purpose: str) -> str | None:
    if asset is None:
        return None
    if (
        asset.owner_type != "TEMPLATE_VERSION"
        or asset.owner_ref != version.public_id
        or asset.purpose != purpose
        or asset.status != ObjectAsset.Status.ACTIVE
        or asset.scan_status != ObjectAsset.ScanStatus.CLEAN
    ):
        raise TemplateAssetNotReady(detail={"asset_id": asset.public_id, "purpose": purpose})
    return asset.public_id


def _validate_tests_asset(version: TemplateVersion) -> None:
    tests_asset_id = str((version.execution_spec or {}).get("tests_asset", ""))
    if not tests_asset_id:
        return
    try:
        asset = ObjectAsset.objects.get(public_id=tests_asset_id)
    except ObjectAsset.DoesNotExist as exc:
        raise TemplateAssetNotReady(
            detail={"asset_id": tests_asset_id, "purpose": "TESTS"}
        ) from exc
    _asset_id(asset, version=version, purpose="TESTS")


def _public_display_policy(policy: Any) -> dict[str, Any]:
    if not isinstance(policy, dict):
        return {}
    allowed = {
        "title",
        "label",
        "description",
        "input_format",
        "pass_condition",
        "show_score",
        "show_output",
    }
    return {key: value for key, value in policy.items() if key in allowed}


def _rule_summary(rule: AutoCheckRule) -> dict[str, Any]:
    return {"position": rule.position, "summary": _public_display_policy(rule.display_policy)}


def _latest_job(task: ExperimentTask) -> ProvisioningJob | None:
    jobs = list(task.provisioning_jobs.all())
    return (
        sorted(jobs, key=lambda item: (item.attempt_no, item.created_at, item.pk), reverse=True)[0]
        if jobs
        else None
    )


def _stage_status(events: Iterable[ProvisioningStageEvent], stage: str) -> dict[str, Any]:
    rows = [item for item in events if item.stage == stage]
    if not rows:
        return {
            "stage": stage,
            "status": "PENDING",
            "attempt_no": None,
            "started_at": None,
            "completed_at": None,
        }
    item = max(rows, key=lambda value: (value.attempt_no, value.created_at, value.pk))
    return {
        "public_id": item.public_id,
        "stage": item.stage,
        "status": item.status,
        "attempt_no": item.attempt_no,
        "error_code": item.error_code,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
    }


def _provisioning_data(task: ExperimentTask) -> dict[str, Any]:
    job = _latest_job(task)
    if job is None:
        return {
            "status": "NOT_STARTED",
            "job_id": None,
            "current_stage": None,
            "progress": 100
            if task.status in _ACTIVE_TASK_STATUSES
            or task.status == ExperimentTask.Status.COMPLETED
            else 0,
            "retryable": False,
            "failure": None,
            "stages": [_stage_status([], stage) for stage in PUBLIC_STAGES],
            "events_channel": f"task:{task.public_id}",
        }

    events = list(job.stage_events.all())
    stage_rows = [_stage_status(events, stage) for stage in PUBLIC_STAGES]
    passed = sum(
        1
        for row in stage_rows
        if row["status"]
        in {ProvisioningStageEvent.Status.PASSED, ProvisioningStageEvent.Status.SKIPPED}
    )
    progress = 100 if job.status == ProvisioningJob.Status.PASSED else round(
        passed / len(PUBLIC_STAGES) * 100
    )
    if job.current_stage in PUBLIC_STAGES and job.status in {
        ProvisioningJob.Status.RUNNING,
        ProvisioningJob.Status.RETRY,
    }:
        progress = max(
            progress,
            round(PUBLIC_STAGES.index(job.current_stage) / len(PUBLIC_STAGES) * 100),
        )
    failure = None
    if job.failure_record is not None:
        failure = {
            "error_code": job.failure_record.error_code,
            "message": job.failure_record.message_masked,
            "detail": job.failure_record.detail_masked,
            "retryable": job.failure_record.retryable,
        }
    return {
        "status": job.status,
        "job_id": job.public_id,
        "current_stage": job.current_stage or None,
        "progress": progress,
        "attempt_no": job.attempt_no,
        "retryable": job.retryable,
        "failure": failure,
        "stages": stage_rows,
        "events_channel": f"task:{task.public_id}",
    }


def _content_data(task: ExperimentTask) -> dict[str, Any]:
    refs = [
        {
            "version_id": str(item.get("version_id", "")),
            "digest_sha256": str(item.get("digest_sha256", "")),
        }
        for item in (task.template_version.material_refs or [])
        if isinstance(item, dict) and item.get("version_id")
    ]
    manual = task.template_version.manual_asset
    manual_data = None
    if manual is not None:
        _asset_id(manual, version=task.template_version, purpose="MANUAL")
        manual_data = {
            "asset_id": manual.public_id,
            "format": "markdown" if manual.media_type == "text/markdown" else "text",
            "text": asset_text(manual) if manual.media_type.startswith("text/") else None,
        }
    return {
        "description": task.publication.description,
        "objectives": [],
        "steps": [],
        "constraints": [],
        "deliverables": [],
        "materials": refs,
        "manual": manual_data,
    }


def _template_data(version: TemplateVersion) -> dict[str, Any]:
    _validate_tests_asset(version)
    return {
        "public_id": version.template.public_id,
        "name": version.template.name,
        "version_id": version.public_id,
        "version_no": version.version_no,
        "dependencies": list(version.dependencies or []),
        "workspace_capabilities": {
            key: bool(value)
            for key, value in (version.workspace_capabilities or {}).items()
            if key in {"webide", "notebook", "terminal", "preview", "snapshot", "checkpoint"}
        },
        "manual_asset_id": _asset_id(version.manual_asset, version=version, purpose="MANUAL"),
        "starter_asset_id": _asset_id(version.starter_asset, version=version, purpose="STARTER"),
        "report_template_asset_id": _asset_id(
            version.report_template_asset, version=version, purpose="REPORT_TEMPLATE"
        ),
    }


def _tests_data(task: ExperimentTask) -> dict[str, Any]:
    rules = sorted(
        [rule for rule in task.template_version.auto_check_rules.all() if rule.is_active],
        key=lambda item: (item.position, item.pk),
    )
    recent = sorted(
        task.workspace_execution_runs.all(),
        key=lambda item: (item.created_at, item.pk),
        reverse=True,
    )
    run = recent[0] if recent else None
    recent_data = (
        {
            "public_id": run.public_id,
            "status": run.status,
            "result_summary": run.result_summary,
            "finished_at": run.finished_at,
            "duration_ms": run.duration_ms,
        }
        if run is not None
        else None
    )
    count, examples = 0, []
    tests_id = str((task.execution_spec or {}).get("tests_asset", ""))
    if tests_id:
        asset = ObjectAsset.objects.filter(public_id=tests_id).first()
        if asset is not None:
            _asset_id(asset, version=task.template_version, purpose="TESTS")
            count, examples = public_examples(asset_text(asset) or "")
    return {
        "public_count": len(examples) if tests_id else len(rules),
        "count": count if tests_id else len(rules),
        "runnable": task_has_active_test_rules(task),
        "summary": examples if tests_id else [_rule_summary(rule) for rule in rules],
        "recent_execution": recent_data,
    }


def _valid_submission_snapshot(task: ExperimentTask) -> WorkspaceSnapshot | None:
    snapshot = (
        WorkspaceSnapshot.objects.select_related("asset")
        .filter(task=task)
        .order_by("-version_no", "-created_at", "-id")
        .first()
    )
    if snapshot is None:
        return None
    asset = snapshot.asset
    if (
        asset.owner_type != "WORKSPACE_TASK"
        or asset.owner_ref != task.public_id
        or asset.digest_sha256 != snapshot.digest_sha256
        or asset.scan_status != ObjectAsset.ScanStatus.CLEAN
        or asset.status != ObjectAsset.Status.ACTIVE
    ):
        return None
    return snapshot


def _submission_data(
    task: ExperimentTask, *, blockers: list[dict[str, Any]]
) -> dict[str, Any]:
    required = bool(task.publication.report_required)
    draft = None
    if required:
        try:
            draft = task.report_draft
        except ReportDraft.DoesNotExist:
            draft = None
    blocked_reason: dict[str, Any] | None = None
    if task.status not in _ACTIVE_TASK_STATUSES:
        blocked_reason = {"code": "TASK_STATE", "status": task.status}
    elif blockers:
        blocked_reason = {"code": "TASK_BLOCKED"}

    snapshot = _valid_submission_snapshot(task)
    if blocked_reason is None and snapshot is None:
        blocked_reason = {"code": "WORKSPACE_SNAPSHOT_REQUIRED"}

    if required and blocked_reason is None and snapshot is not None:
        if (
            draft is None
            or draft.status != ReportDraft.Status.DRAFT
            or not draft.body_markdown.strip()
        ):
            blocked_reason = {"code": "REPORT_DRAFT_REQUIRED"}
        elif (
            draft.workspace_snapshot_id != snapshot.pk
            or draft.snapshot_digest != snapshot.digest_sha256
        ):
            blocked_reason = {"code": "REPORT_DRAFT_STALE"}
        else:
            attachments = list(draft.attachments.select_related("asset"))
            if any(
                item.asset.scan_status == ObjectAsset.ScanStatus.PENDING
                and item.asset.status == ObjectAsset.Status.ACTIVE
                for item in attachments
            ):
                blocked_reason = {"code": "REPORT_ATTACHMENTS_SCANNING"}
            elif any(
                item.asset.scan_status != ObjectAsset.ScanStatus.CLEAN
                or item.asset.status != ObjectAsset.Status.ACTIVE
                for item in attachments
            ):
                blocked_reason = {"code": "REPORT_ATTACHMENTS_NOT_READY"}

    if (
        blocked_reason is None and snapshot is not None
        and (task.execution_spec or {}).get("schema_version") == 2
    ):
        from apps.reports.errors import ReportExecutionConflict, ReportExecutionNotReady
        from apps.reports.services import _latest_execution_for_submission

        try:
            _latest_execution_for_submission(task=task, snapshot=snapshot)
        except ReportExecutionNotReady:
            blocked_reason = {"code": "TEST_NOT_PASSED"}
        except ReportExecutionConflict:
            blocked_reason = {"code": "TEST_SNAPSHOT_STALE"}

    if (
        required
        and blocked_reason is None
        and snapshot is not None
        and task_has_active_test_rules(task)
        and (task.execution_spec or {}).get("schema_version") != 2
    ):
        driver = task.runtime_adapter_driver or (
            task.runtime_adapter.driver if task.runtime_adapter_id else "FAKE"
        )
        if driver != "FAKE":
            run = (
                WorkspaceExecutionRun.objects.filter(task=task)
                .order_by("-created_at", "-id")
                .first()
            )
            if run is None or run.status in {
                WorkspaceExecutionRun.Status.QUEUED,
                WorkspaceExecutionRun.Status.RUNNING,
            }:
                blocked_reason = {"code": "TEST_NOT_FINISHED"}
            elif run.snapshot_id != snapshot.pk:
                blocked_reason = {"code": "TEST_SNAPSHOT_STALE"}

    return {
        "required": required,
        "kind": "REPORT" if required else "SYSTEM_ARTIFACT",
        "strategy": "REPORT" if required else "COMPLETE",
        "can_submit": blocked_reason is None,
        "blocked_reason": blocked_reason,
        "draft_status": draft.status if draft is not None else None,
    }


def workbench_data(*, actor: User, task_id: str) -> dict[str, Any]:
    task = workbench_task_for_user(actor=actor, task_id=task_id)
    blockers = prerequisite_blockers_for_publication(publication=task.publication, student=actor)
    actions = allowed_actions(task, actor=actor)
    operations: list[str] = []
    capabilities = task.template_version.workspace_capabilities or {}
    if task.status in _ACTIVE_TASK_STATUSES:
        operations = ["SAVE_SNAPSHOT", "RUN_TEST", "SELF_TEST"]
        if bool(capabilities.get("webide")):
            operations.append("RESET_WORKSPACE")
        operations.append("SUBMIT_REPORT" if task.publication.report_required else "COMPLETE")
    driver = task.runtime_adapter_driver or (
        task.runtime_adapter.driver if task.runtime_adapter_id else "FAKE"
    )
    real_runtime = driver != "FAKE" and bool(capabilities.get("webide"))
    active_job = active_storage_job_for_user(actor=actor, task_id=task_id)
    active_session = (
        WorkspaceSession.objects.select_related("latest_snapshot")
        .filter(
            task=task, student=actor, status=WorkspaceSession.Status.ACTIVE
        )
        .order_by("-created_at")
        .first()
    )
    current_version = active_session.current_version if active_session is not None else 0
    last_snapshot_id = (
        active_session.latest_snapshot.public_id
        if active_session is not None and active_session.latest_snapshot_id
        else None
    )
    workspace_mode = (
        "RUNTIME_IDE"
        if real_runtime and task.status in _ACTIVE_TASK_STATUSES
        else "READ_ONLY"
        if task.status not in _ACTIVE_TASK_STATUSES
        else "LEGACY_DRAFT"
    )
    capture_supported = workspace_mode == "RUNTIME_IDE" and bool(
        capabilities.get("snapshot")
    )
    policy = (task.execution_spec or {}).get("toolchain", {})
    language = active_session.language if active_session else policy.get("language") or "python"
    return {
        "task": {
            "public_id": task.public_id,
            "course_id": task.course.public_id,
            "publication_id": task.publication.public_id,
            "title": task.publication.title,
            "description": task.publication.description,
            "status": task.status,
            "deadline": task.effective_deadline or task.publication.window_end,
            "assignment_deadline": task.publication.assignment_deadline,
            "report_required": task.publication.report_required,
            "report_strategy": "REPORT" if task.publication.report_required else "COMPLETE",
            "allowed_actions": actions,
            "allowed_operations": operations,
            "blockers": blockers,
            "current_failure": task.current_failure,
            "row_version": task.row_version,
        },
        "content": _content_data(task),
        "template": _template_data(task.template_version),
        "tests": _tests_data(task),
        "provisioning": _provisioning_data(task),
        "workspace": {
            "mode": workspace_mode,
            "entrypoint": (task.execution_spec or {}).get("entrypoint")
            or TOOLCHAINS_BY_LANGUAGE.get(language, TOOLCHAINS_BY_LANGUAGE["python"])["entrypoint"],
            "language": language,
            "language_policy": policy,
            "toolchain_version": policy.get("default_versions", {}).get(language),
            "capture_supported": capture_supported,
            "last_synchronized_version": current_version,
            "last_synchronized_snapshot_id": last_snapshot_id,
            "active_storage_job": storage_job_data(active_job) if active_job else None,
        },
        "submission": _submission_data(task, blockers=blockers),
    }

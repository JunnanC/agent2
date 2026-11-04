"""Auto-check execution ports.

The review service owns the audit fact and retry state. This module only
translates a frozen review into an execution request. Commands and hidden test
assets always come from the task's frozen execution contract.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings

from apps.core.models import ObjectAsset
from apps.core.object_storage import object_storage
from apps.experiments.models import ExperimentTask
from apps.labtemplates.services import build_execution_command
from apps.provisioning.adapters import runtime_for_driver
from apps.provisioning.metrics import (
    RUNTIME_ENGINE_UNAVAILABLE_TOTAL,
    RUNTIME_JUDGE_EXECUTION_DURATION,
    RUNTIME_JUDGE_EXECUTIONS,
    is_engine_unavailable,
)
from apps.provisioning.ports import RuntimeExecutionResult, RuntimeSpec

from .models import AutoCheckRun, Review

logger = logging.getLogger("runtime.judge")

AUTO_CHECK_TERMINAL_STATUSES = frozenset(
    {
        AutoCheckRun.Status.PASSED,
        AutoCheckRun.Status.FAILED,
        AutoCheckRun.Status.TIMEOUT,
        AutoCheckRun.Status.RESOURCE_EXCEEDED,
        AutoCheckRun.Status.REJECTED,
    }
)


@dataclass(frozen=True)
class AutoCheckResult:
    passed: bool
    summary: dict[str, object]
    evidence: list[dict[str, object]]
    status: str = AutoCheckRun.Status.PASSED
    error_code: str = ""
    duration_ms: int | None = None


class AutoCheckExecutor(Protocol):
    def execute(self, run: AutoCheckRun) -> AutoCheckResult: ...


class AutoCheckRejected(RuntimeError):
    """A non-retryable contract or asset violation discovered by a judge."""

    retryable = False

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _record_judge_cleanup_failure(
    *, run: AutoCheckRun, driver: str, config_ref: str, error: Exception
) -> None:
    """Record a retryable cleanup fact without changing the judge result.

    The execution result is an immutable review fact.  A Docker Engine outage while
    removing the one-shot container must therefore be handled independently through
    the normal compensation queue instead of turning a passed check into a failed
    check or rewriting its status.
    """

    from apps.core.audit import append_failure
    from apps.core.compensation import create_compensation
    from apps.core.models import CompensationTask

    subject_ref = run.public_id
    if not CompensationTask.objects.filter(
        task_type="RETRY_JUDGE_DESTROY",
        subject_type="AUTO_CHECK_RUN",
        subject_ref=subject_ref,
        status__in=(
            CompensationTask.Status.PENDING,
            CompensationTask.Status.IN_FLIGHT,
            CompensationTask.Status.RETRY,
        ),
    ).exists():
        failure = append_failure(
            failure_type="JUDGE_CLEANUP",
            subject_type="AUTO_CHECK_RUN",
            subject_ref=subject_ref,
            error_code=str(getattr(error, "code", "JUDGE_DESTROY_FAILED"))[:64],
            message="judge cleanup failed",
            detail={"exception": type(error).__name__},
            retryable=True,
            trace_id=run.trace_id,
        )
        task = create_compensation(
            task_type="RETRY_JUDGE_DESTROY",
            subject_type="AUTO_CHECK_RUN",
            subject_ref=subject_ref,
            payload={
                "judge_id": run.public_id,
                "driver": driver,
                "config_ref": config_ref,
            },
            trace_id=run.trace_id,
        )
        # Keep a stable link in the failure detail without exposing the exception
        # text or Docker connection details.
        del failure, task


class FakeRuntimeAutoCheckExecutor:
    """Deterministic executor retained for local compatibility tests."""

    def execute(self, run: AutoCheckRun) -> AutoCheckResult:
        forced_failure = bool(run.rule.input_schema.get("x_fake_failure", False))
        return AutoCheckResult(
            passed=not forced_failure,
            summary={
                "checker_type": run.checker_type,
                "result": "FAILED" if forced_failure else "PASSED",
                "executor": "FAKE_RUNTIME",
                "execution_rule_digest": run.execution_rule_digest,
            },
            evidence=[
                {
                    "rule_digest": run.rule_digest,
                    "artifact_digest": run.artifact_digest,
                    "execution_rule_digest": run.execution_rule_digest,
                    "message": (
                        "Local FakeRuntime check was configured to fail."
                        if forced_failure
                        else "Local FakeRuntime check completed."
                    ),
                }
            ],
            status=AutoCheckRun.Status.FAILED if forced_failure else AutoCheckRun.Status.PASSED,
        )


def _read_asset(asset: ObjectAsset, *, limit: int | None = None) -> bytes:
    if (
        asset.status != ObjectAsset.Status.ACTIVE
        or asset.scan_status != ObjectAsset.ScanStatus.CLEAN
    ):
        raise AutoCheckRejected("AUTO_CHECK_ASSET_NOT_READY")
    if limit is not None and asset.size_bytes > limit:
        raise AutoCheckRejected("AUTO_CHECK_ASSET_TOO_LARGE")
    try:
        stored = object_storage().open_object(
            bucket=asset.bucket,
            object_key=asset.object_key,
            version_id=asset.object_version,
        )
        body = stored.body
        try:
            value = (
                body.read(limit + 1) if limit is not None else body.read()
            ) if hasattr(body, "read") else body
        finally:
            if hasattr(body, "close"):
                body.close()
        value = bytes(value or b"")
        if limit is not None and (
            len(value) > limit or hashlib.sha256(value).hexdigest() != asset.digest_sha256
        ):
            raise AutoCheckRejected("AUTO_CHECK_ASSET_INVALID")
        return value
    except AutoCheckRejected:
        raise
    except Exception as exc:  # noqa: BLE001 - the audit layer masks storage details
        raise AutoCheckRejected("AUTO_CHECK_ASSET_UNAVAILABLE") from exc


def submitted_execution_contract(
    task: ExperimentTask, review: Review,
) -> tuple[dict[str, Any], str]:
    """Resolve the shared execution contract using the submitted snapshot's language."""
    from apps.workspaces.services import _execution_rules

    submission = review.report_version if review.report_version_id else review.system_artifact
    snapshot = submission.workspace_snapshot
    if snapshot.task_id != task.pk:
        raise AutoCheckRejected("AUTO_CHECK_SUBMISSION_MISMATCH")
    try:
        summary, _command, digest = _execution_rules(task, language=snapshot.language)
    except (KeyError, ValueError) as exc:
        raise AutoCheckRejected("AUTO_CHECK_EXECUTION_SPEC_INVALID") from exc
    if summary["language"] != snapshot.language:
        raise AutoCheckRejected("AUTO_CHECK_SUBMISSION_MISMATCH")
    return summary, digest


def _execution_summary(task: ExperimentTask, run: AutoCheckRun) -> dict[str, Any]:
    if (task.execution_spec or {}).get("schema_version") == 2:
        summary, digest = submitted_execution_contract(task, run.review)
        submission = (
            run.review.report_version
            if run.review.report_version_id else run.review.system_artifact
        )
        snapshot = submission.workspace_snapshot
        submitted_digest = (
            submission.snapshot_digest if run.review.report_version_id else submission.digest_sha256
        )
        if (
            run.input_asset_id != snapshot.asset_id
            or run.artifact_digest != submitted_digest
            or snapshot.digest_sha256 != submitted_digest
            or snapshot.asset.digest_sha256 != submitted_digest
        ):
            raise AutoCheckRejected("AUTO_CHECK_SUBMISSION_MISMATCH")
        if run.execution_rule_summary != summary or run.execution_rule_digest != digest:
            raise AutoCheckRejected("AUTO_CHECK_EXECUTION_RULE_MISMATCH")
        return summary
    summary = dict(run.execution_rule_summary or {})
    if not summary:
        spec = dict(task.execution_spec or task.template_version.execution_spec or {})
        summary = {
            "language": spec.get("language", ""),
            "entrypoint": spec.get("entrypoint", ""),
            "timeout_seconds": spec.get("timeout_seconds", 0),
            "memory_mb": spec.get("memory_mb", 0),
            "cpu_millicores": spec.get("cpu_millicores", 0),
            "comparator": spec.get("comparator", "token"),
            "network_mode": spec.get("network_mode", "DENY_ALL"),
            "tests_asset": spec.get("tests_asset", ""),
            "command": [],
        }
    command = summary.get("command")
    if not command:
        try:
            command = build_execution_command(summary)
        except Exception as exc:  # noqa: BLE001 - contract violations are terminal
            raise AutoCheckRejected("AUTO_CHECK_EXECUTION_SPEC_INVALID") from exc
    # Only the server-generated first-version Python command is allowed.
    if not isinstance(command, list) or len(command) != 2 or command[0] != "python":
        raise AutoCheckRejected("AUTO_CHECK_COMMAND_NOT_ALLOWED")
    summary["command"] = [str(value) for value in command]
    if summary.get("network_mode", "DENY_ALL") != "DENY_ALL":
        raise AutoCheckRejected("AUTO_CHECK_NETWORK_NOT_ALLOWED")
    computed_digest = hashlib.sha256(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if run.execution_rule_digest and run.execution_rule_digest != computed_digest:
        raise AutoCheckRejected("AUTO_CHECK_EXECUTION_RULE_MISMATCH")
    if not run.execution_rule_digest:
        run.execution_rule_digest = computed_digest
    return summary


def _runtime_spec(task: ExperimentTask, *, trace_id: str) -> RuntimeSpec:
    profile = dict(task.resource_profile_snapshot or {})
    image = task.image
    return RuntimeSpec(
        task_id=task.public_id,
        course_id=task.course.public_id,
        student_id=task.student.public_id,
        runtime_type=task.runtime_type,
        image_registry=task.image_registry or (image.registry if image else ""),
        image_repository=task.image_repository or (image.repository if image else ""),
        image_digest=task.image_digest or (image.digest if image else "sha256:"),
        resource_profile_id=(
            task.resource_profile.public_id
            if task.resource_profile_id
            else str(profile.get("public_id", ""))
        ),
        cpu_millicores=int(profile.get("cpu_millicores", 0) or 0),
        memory_mb=int(profile.get("memory_mb", 0) or 0),
        disk_gb=int(profile.get("disk_gb", 0) or 0),
        network_policy={"mode": "DENY_ALL"},
        workspace_capabilities={},
        workspace_port=8080,
        healthcheck_path="/healthz",
        trace_id=trace_id,
    )


class DockerLocalAutoCheckExecutor:
    """Judge port backed by a runtime adapter.

    Adapters with ``execute_judge`` receive student source and hidden tests and
    manage the one-shot container lifecycle. Legacy protocol stubs fall back to
    ``execute`` without hidden tests.
    """

    def __init__(
        self,
        *,
        runtime_factory: Callable[..., Any] = runtime_for_driver,
    ) -> None:
        self._runtime_factory = runtime_factory

    def execute(self, run: AutoCheckRun) -> AutoCheckResult:
        task = (
            ExperimentTask.objects.select_related(
                "course",
                "student",
                "template_version",
                "runtime_adapter",
                "image",
                "resource_profile",
            )
            .get(pk=run.review.task_id)
        )
        driver = task.runtime_adapter_driver or (
            task.runtime_adapter.driver if task.runtime_adapter_id else ""
        )
        if driver != "DOCKER_LOCAL":
            raise AutoCheckRejected("AUTO_CHECK_RUNTIME_NOT_LOCAL")
        summary = _execution_summary(task, run)
        tests_id = str(summary.get("tests_asset", ""))
        try:
            tests_asset = ObjectAsset.objects.get(
                public_id=tests_id,
                owner_type="TEMPLATE_VERSION",
                owner_ref=task.template_version.public_id,
                purpose="TESTS",
            )
        except ObjectAsset.DoesNotExist as exc:
            raise AutoCheckRejected("AUTO_CHECK_HIDDEN_TESTS_UNAVAILABLE") from exc
        project = (task.execution_spec or {}).get("schema_version") == 2
        if project:
            limit = int(settings.WORKSPACE_SNAPSHOT_MAX_BYTES)
            source = _read_asset(run.input_asset, limit=limit)
            tests = _read_asset(tests_asset, limit=int(settings.TEMPLATE_ASSET_MAX_BYTES))
            test_config = json.loads(tests)
            test_config.update({key: summary[key] for key in (
                "comparator", "absolute_tolerance", "relative_tolerance"
            )})
            tests = json.dumps(test_config).encode()
        else:
            source = _read_asset(run.input_asset)
            tests = _read_asset(tests_asset)
        config_ref = task.runtime_adapter_config_ref or (
            task.runtime_adapter.config_ref if task.runtime_adapter_id else ""
        )
        adapter = self._runtime_factory(driver, config_ref=config_ref)
        timeout_seconds = int(summary.get("timeout_seconds", 0) or 0)
        if run.rule.timeout_seconds:
            timeout_seconds = min(timeout_seconds, int(run.rule.timeout_seconds))
        limits = dict(run.rule.resource_limit or {})
        memory_mb = int(limits.get("memory_mb") or summary.get("memory_mb", 0) or 0)
        cpu_millicores = int(limits.get("cpu_millicores") or summary.get("cpu_millicores", 0) or 0)
        spec = _runtime_spec(task, trace_id=run.trace_id)
        execute_judge = getattr(adapter, "execute_judge", None)
        try:
            if callable(execute_judge):
                result = execute_judge(
                    spec=spec,
                    command=list(summary["command"]),
                    source=source,
                    tests=tests,
                    timeout_seconds=timeout_seconds,
                    memory_mb=memory_mb,
                    cpu_millicores=cpu_millicores,
                    network_mode="DENY_ALL",
                    judge_id=run.public_id,
                    **({"execution_plan": summary["execution_plan"]} if project else {}),
                )
            else:
                if project:
                    raise AutoCheckRejected("AUTO_CHECK_EXECUTION_PLAN_UNSUPPORTED")
                # The legacy protocol stub has no hidden-test parameter. It
                # still exercises driver selection and the stable one-shot port.
                result = adapter.execute(
                    spec=spec,
                    command=list(summary["command"]),
                    source=source,
                    timeout_seconds=timeout_seconds,
                    memory_mb=memory_mb,
                    cpu_millicores=cpu_millicores,
                    network_mode="DENY_ALL",
                )
        except Exception as exc:
            error_code = str(getattr(exc, "code", ""))
            if is_engine_unavailable(error_code):
                RUNTIME_ENGINE_UNAVAILABLE_TOTAL.labels(driver=driver).inc()
            raise
        finally:
            destroy_judge = getattr(adapter, "destroy_judge", None)
            if callable(destroy_judge):
                try:
                    destroy_judge(
                        run.public_id,
                        f"judge-destroy:{run.public_id}",
                    )
                except Exception as exc:  # noqa: BLE001 - queue a safe retry
                    _record_judge_cleanup_failure(
                        run=run,
                        driver=driver,
                        config_ref=config_ref,
                        error=exc,
                    )
        if isinstance(result, RuntimeExecutionResult):
            status = result.status
            stdout = result.stdout
            stderr = result.stderr
            report = dict(result.test_report or {})
            error_code = result.error_code
            duration_ms = result.duration_ms
            result_summary = result.result_summary or status
        else:
            status = str(getattr(result, "status", "FAILED"))
            stdout = str(getattr(result, "stdout", ""))
            stderr = str(getattr(result, "stderr", ""))
            report = dict(getattr(result, "test_report", {}) or {})
            error_code = str(getattr(result, "error_code", ""))
            duration_ms = getattr(result, "duration_ms", None)
            result_summary = str(getattr(result, "result_summary", "") or status)
        if status not in AUTO_CHECK_TERMINAL_STATUSES:
            status = AutoCheckRun.Status.FAILED
        if duration_ms is not None:
            RUNTIME_JUDGE_EXECUTION_DURATION.labels(driver=driver).observe(duration_ms / 1000)
        RUNTIME_JUDGE_EXECUTIONS.labels(driver=driver, status=status).inc()
        logger.info(
            "runtime judge finished",
            extra={
                "trace_id": run.trace_id,
                "task_ref": task.public_id,
                "execution_run_ref": run.public_id,
                "resource_ref": run.public_id,
                "result": status,
                "error_code": error_code,
                "duration_ms": duration_ms or 0,
            },
        )
        return AutoCheckResult(
            passed=status == AutoCheckRun.Status.PASSED,
            status=status,
            error_code=error_code,
            duration_ms=duration_ms,
            summary={
                "checker_type": run.checker_type,
                "result": status,
                "executor": "DOCKER_LOCAL_JUDGE",
                "judge_container": True,
                "network_mode": "DENY_ALL",
                "execution_rule_digest": run.execution_rule_digest,
                "test_report": report,
                "summary": result_summary,
            },
            evidence=[
                {
                    "rule_digest": run.rule_digest,
                    "artifact_digest": run.artifact_digest,
                    "execution_rule_digest": run.execution_rule_digest,
                    "tests_asset_digest": tests_asset.digest_sha256,
                    "status": status,
                    "stdout_digest": hashlib.sha256(stdout.encode()).hexdigest(),
                    "stderr_digest": hashlib.sha256(stderr.encode()).hexdigest(),
                }
            ],
        )


class RoutingAutoCheckExecutor:
    """Keep FakeRuntime semantics while routing real tasks to the judge port."""

    def __init__(self) -> None:
        self.fake = FakeRuntimeAutoCheckExecutor()
        self.docker_local = DockerLocalAutoCheckExecutor()

    def execute(self, run: AutoCheckRun) -> AutoCheckResult:
        task = run.review.task
        driver = getattr(task, "runtime_adapter_driver", "") or (
            task.runtime_adapter.driver if getattr(task, "runtime_adapter_id", None) else "FAKE"
        )
        if driver == "DOCKER_LOCAL":
            return self.docker_local.execute(run)
        return self.fake.execute(run)


def auto_check_executor() -> AutoCheckExecutor:
    """Return the stable review executor port used by workers and tests."""

    return RoutingAutoCheckExecutor()


RealAutoCheckExecutor = DockerLocalAutoCheckExecutor

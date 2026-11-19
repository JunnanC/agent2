"""Workers compare expected output outside the student container."""

import logging
from typing import Any

from django.db import transaction

from apps.provisioning.assessment_judge import ordered_cases
from apps.provisioning.stdio import StdioResult, stdio_outputs_match
from apps.workspaces.models import StudentWorkspace
from apps.workspaces.tasks import sync_drafts, workspace_runtime

from .assessment_parts import part_open
from .assessment_workers import _finish, _read_source
from .models import AssessmentRun, ProgrammingSubmission
from .workspace_assessment import complete_attempt

logger = logging.getLogger(__name__)


def _cases(run: AssessmentRun) -> list[dict[str, str]]:
    return ordered_cases(run.question, run.task.template_version.public_id)


def case_results(
    cases: list[dict[str, str]],
    results: list[StdioResult],
) -> list[dict[str, Any]]:
    rows = []
    for index, case in enumerate(cases):
        result = results[index] if index < len(results) else StdioResult("NOT_RUN")
        passed = result.status == "PASSED" and stdio_outputs_match(result.stdout, case["output"])
        row: dict[str, Any] = {"number": index + 1, "passed": passed}
        if index < 2:
            row.update(
                input=case["input"],
                expected_output=case["output"],
                actual_output=result.stdout,
                stderr=result.stderr,
                status=result.status,
            )
        rows.append(row)
    return rows


def execute_workspace_attempt(run: AssessmentRun) -> None:
    try:
        final = run.mode == AssessmentRun.Mode.FINAL
        cases = _cases(run) if final else []
        inputs = [case["input"] for case in cases] if final else [run.stdin]
        files = _read_source(run.snapshot)
        with transaction.atomic():
            workspace = StudentWorkspace.objects.select_for_update().get(task_id=run.task_id)
            if not part_open(workspace.task, workspace.expires_at):
                _finish(run, status="COMPLETED", result_status="WINDOW_CLOSED")
                return
            if ProgrammingSubmission.objects.filter(
                task_id=run.task_id,
                question_id=run.question_id,
            ).exists():
                _finish(run, status="COMPLETED", result_status="ALREADY_SUBMITTED")
                return
            with workspace_runtime(workspace) as runtime:
                container = runtime.ensure()
                sync_drafts(runtime, container, workspace)
                compilation, results = runtime.execute(
                    container=container,
                    language=run.snapshot.language,
                    files=files,
                    inputs=inputs,
                    timeout_seconds=run.question.question_spec["limits"][run.snapshot.language][
                        "timeout_seconds"
                    ],
                    expires_at=workspace.expires_at.timestamp(),
                )
        if final:
            rows = case_results(cases, results)
            passed = bool(rows) and all(case["passed"] for case in rows)
            status = "PASSED" if passed else "COMPILE_ERROR" if compilation else "FAILED"
            complete_attempt(
                run,
                all_passed=passed,
                result={
                    "case_results": rows,
                    "result_status": status,
                    "stderr": compilation.stderr if compilation else "",
                },
            )
        else:
            result = compilation or results[0]
            _finish(
                run,
                status="COMPLETED",
                stdout=result.stdout,
                stderr=result.stderr,
                result_status="COMPILE_ERROR" if compilation else result.status,
            )
    except Exception:
        logger.exception("Workspace attempt failed", extra={"run_id": run.pk})
        if run.attempt_count >= 5:
            _finish(run, status="COMPLETED", result_status="PLATFORM_ERROR")
        else:
            _finish(run, status="RETRY")

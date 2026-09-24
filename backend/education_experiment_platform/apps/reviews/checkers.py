from dataclasses import dataclass
from typing import Protocol

from .models import AutoCheckRun


@dataclass(frozen=True)
class AutoCheckResult:
    passed: bool
    summary: dict[str, object]
    evidence: list[dict[str, object]]


class AutoCheckExecutor(Protocol):
    def execute(self, run: AutoCheckRun) -> AutoCheckResult: ...


class FakeRuntimeAutoCheckExecutor:
    """P07/P10 local executor. P14 replaces this through the same port."""

    def execute(self, run: AutoCheckRun) -> AutoCheckResult:
        forced_failure = bool(run.rule.input_schema.get("x_fake_failure", False))
        return AutoCheckResult(
            passed=not forced_failure,
            summary={
                "checker_type": run.checker_type,
                "result": "FAILED" if forced_failure else "PASSED",
                "executor": "FAKE_RUNTIME",
            },
            evidence=[
                {
                    "rule_digest": run.rule_digest,
                    "artifact_digest": run.artifact_digest,
                    "message": (
                        "Local FakeRuntime check was configured to fail."
                        if forced_failure
                        else "Local FakeRuntime check completed."
                    ),
                }
            ],
        )


def auto_check_executor() -> AutoCheckExecutor:
    return FakeRuntimeAutoCheckExecutor()

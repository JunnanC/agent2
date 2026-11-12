from types import SimpleNamespace
from typing import Any, cast

import pytest

from apps.labtemplates.errors import TemplateValidationError
from apps.provisioning.assessment_judge import grade_groups, validated_groups
from apps.provisioning.stdio import StdioExecutor, StdioResult


def test_group_is_all_or_nothing_but_other_groups_still_score() -> None:
    groups = [
        {"id": "basic", "cases": [{"input": "1", "output": "2"}, {"input": "3", "output": "4"}]},
        {"id": "edge", "cases": [{"input": "5", "output": "6"}]},
    ]
    executor = SimpleNamespace(execute=lambda **kwargs: (None, [
        StdioResult("PASSED", "2"), StdioResult("PASSED", "wrong"), StdioResult("PASSED", "6\n"),
    ]))
    result = grade_groups(
        executor=cast(StdioExecutor, executor), language="python",
        files={"main.py": ""}, groups=groups,
        scores=[{"id": "basic", "score": "7"}, {"id": "edge", "score": "3"}],
        limits={"timeout_seconds": 3, "memory_mb": 256},
    )
    assert result["score"] == "3"
    assert result["groups"][0]["score"] == "0"
    assert "wrong" not in str(result)
    assert "input" not in str(result)


def test_missing_group_or_case_output_is_a_configuration_error() -> None:
    with pytest.raises(TemplateValidationError):
        validated_groups({"groups": []}, [{"id": "g", "score": "1"}])
    with pytest.raises(TemplateValidationError):
        validated_groups(
            {"groups": [{"id": "g", "cases": [{"input": "secret"}]}]},
            [{"id": "g", "score": "1"}],
        )


def test_compiler_failure_is_zero_but_executor_failure_is_not_a_grade() -> None:
    kwargs: dict[str, Any] = {
        "language": "python", "files": {"main.py": "bad"},
        "groups": [{"id": "g", "cases": [{"input": "1", "output": "2"}]}],
        "scores": [{"id": "g", "score": "1"}],
        "limits": {"timeout_seconds": 3, "memory_mb": 256},
    }
    compiler = SimpleNamespace(execute=lambda **_: (StdioResult("RUNTIME_ERROR"), []))
    assert grade_groups(executor=cast(StdioExecutor, compiler), **kwargs)["score"] == "0"
    broken = SimpleNamespace(execute=lambda **_: (None, []))
    with pytest.raises(RuntimeError):
        grade_groups(executor=cast(StdioExecutor, broken), **kwargs)

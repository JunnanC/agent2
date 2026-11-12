from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.labtemplates.errors import TemplateValidationError
from apps.labtemplates.questions import (
    normalize_question,
    project_files,
    public_question,
    score_value,
)


def test_choice_validation_and_student_projection_exclude_secrets() -> None:
    public, private, score = normalize_question(
        task_type="MULTIPLE_CHOICE", max_score="2.50",
        public={"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]},
        marking={"correct_option_ids": ["b", "a"], "explanation": "private explanation"},
    )
    assert score == Decimal("2.50")
    question = SimpleNamespace(
        public_id="q1", title="Question", description="", instructions="", sort_order=1,
        task_type="MULTIPLE_CHOICE", question_spec=public, marking_spec=private, max_score=score,
    )
    student = public_question(question)
    assert student["options"] == public["options"]
    assert "correct_option_ids" not in str(student)
    assert "private explanation" not in str(student)


@pytest.mark.parametrize("answers", [["a", "a"], ["c"], [], ["a", "b"]])
def test_single_choice_rejects_invalid_answer_sets(answers: list[str]) -> None:
    with pytest.raises(TemplateValidationError):
        normalize_question(
            task_type="SINGLE_CHOICE", max_score=1,
            public={"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]},
            marking={"correct_option_ids": answers},
        )


@pytest.mark.parametrize("score", [True, "NaN", "Infinity", "0", "-1", "1.001", "100000"])
def test_invalid_scores(score: object) -> None:
    with pytest.raises(TemplateValidationError):
        score_value(score)


@pytest.mark.parametrize("files", [
    {"../main.py": ""}, {"/main.py": ""}, {"a\\b.py": ""}, {"-x.py": ""},
    {"main.py": "\x00"}, {"a": "", "a/b": ""}, {"Main.py": "", "main.py": ""},
])
def test_unsafe_project_files(files: dict[str, str]) -> None:
    with pytest.raises(TemplateValidationError):
        project_files(files)


def test_empty_file_and_empty_project_can_be_saved() -> None:
    assert project_files({"main.py": ""}) == {"main.py": ""}
    assert project_files({}) == {}


def test_programming_question_validates_groups_and_reference() -> None:
    public = {
        "allowed_languages": ["python"], "samples": [{"input": "1", "output": "1"}],
        "starter_files": {"python": {"main.py": ""}},
        "limits": {"python": {"timeout_seconds": 3, "memory_mb": 256}},
    }
    private = {
        "tests_asset_id": "A" * 26, "groups": [{"id": "basic", "score": "10"}],
        "reference_solutions": {"python": {"main.py": "print(input())"}},
    }
    assert normalize_question(
        task_type="PROGRAMMING", public=public, marking=private, max_score="10",
    )[2] == Decimal("10")
    with pytest.raises(TemplateValidationError, match="模板规格无效"):
        normalize_question(
            task_type="PROGRAMMING", public=public, marking=private, max_score="11",
        )

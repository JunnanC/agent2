"""Experiment-authored questions and published runtime settings."""

from decimal import Decimal
from typing import Any

from apps.core.errors import StateConflict
from apps.core.identifiers import new_ulid
from apps.labtemplates.questions import CHOICE_TYPES, ENTRYPOINTS, normalize_question, project_files

from .environments import config_for, validate_environment
from .models import TaskPublication, TeachingEnvironment


def normalized_design(
    data: dict[str, Any],
    environment: TeachingEnvironment | None,
) -> dict[str, Any]:
    questions = []
    points = {key: str(value) for key, value in data["part_maxima"].items()}
    language = environment.language if environment else None
    types = {question["task_type"] for question in data["questions"]}
    if bool(types & CHOICE_TYPES) != (Decimal(points["CHOICE"]) > 0):
        raise StateConflict(detail={"part_maxima": "choice_questions_and_points_required"})
    if ("PROGRAMMING" in types) != (Decimal(points["PROGRAMMING"]) > 0):
        raise StateConflict(detail={"part_maxima": "programming_questions_and_points_required"})
    if Decimal(points["REPORT"]) > 0 and not data["report_requirements"].strip():
        raise StateConflict(detail={"report_requirements": "required"})
    if not any(Decimal(value) > 0 for value in points.values()):
        raise StateConflict(detail={"part_maxima": "at_least_one_part_required"})

    for position, item in enumerate(data["questions"], 1):
        kind = item["task_type"]
        if kind in CHOICE_TYPES:
            public, marking, _points = normalize_question(
                task_type=kind,
                public={"options": item["options"]},
                marking={
                    "correct_option_ids": item["correct_option_ids"],
                    "explanation": item["explanation"],
                },
                max_score=1,
            )
        else:
            if not environment or not language:
                raise StateConflict(detail={"environment_id": "required_for_programming"})
            if not item["samples"] or not item["hidden_cases"]:
                raise StateConflict(detail={"cases": "public_and_private_cases_required"})
            filename = ENTRYPOINTS[language]
            public = {
                "allowed_languages": [language],
                "samples": item["samples"],
                "starter_files": {language: project_files({filename: item["starter_code"]})},
                "limits": {
                    language: {
                        "timeout_seconds": item["timeout_seconds"],
                        "memory_mb": environment.memory_mb,
                    }
                },
            }
            marking = {"hidden_cases": item["hidden_cases"], "explanation": item["explanation"]}
        questions.append({
            "source_task_id": new_ulid(),
            "sort_order": position,
            "task_type": kind,
            "title": item["title"],
            "description": item["description"],
            "instructions": "",
            "question_spec": public,
            "marking_spec": marking,
            "max_score": "1.00",
            "submission_policy": {},
            "grading_policy": {},
        })
    return {
        "guidance": data["guidance"],
        "report_requirements": data["report_requirements"],
        "part_maxima": points,
        "questions": questions,
    }


def direct_content(publication: TaskPublication) -> tuple[dict[str, Any], dict[str, Any]]:
    from .services import _json_digest

    spec = publication.experiment_spec
    environment = publication.environment
    programming = any(item["task_type"] == "PROGRAMMING" for item in spec["questions"])
    config: dict[str, Any] = {}
    runtime: dict[str, Any] = {}
    if programming:
        if environment is None:
            raise StateConflict(detail={"environment_id": "required_for_programming"})
        validate_environment(environment)
        config = config_for(environment)
        if any(
            item["question_spec"]["allowed_languages"] != [environment.language]
            for item in spec["questions"]
            if item["task_type"] == "PROGRAMMING"
        ):
            raise StateConflict(detail={"environment_id": "language_changed_resave_draft"})
        runtime = {
            "runtime_adapter": environment.runtime_adapter,
            "runtime_adapter_driver": config["runtime_adapter_driver"],
            "runtime_adapter_config_ref": config["runtime_adapter_config_ref"],
            "image": environment.image,
            "image_registry": config["image_registry"],
            "image_repository": config["image_repository"],
            "image_digest": config["image_digest"],
            "resource_profile_snapshot": config,
        }
    questions = []
    for item in spec["questions"]:
        public = item["question_spec"]
        is_program = item["task_type"] == "PROGRAMMING"
        execution: dict[str, Any] = {}
        if is_program:
            limits = {
                language: {**limit, "memory_mb": config["memory_mb"]}
                for language, limit in public["limits"].items()
            }
            public = {**public, "limits": limits}
            execution = {
                "case_count": len(public["samples"]) + len(item["marking_spec"]["hidden_cases"]),
            }
        questions.append({
            **item,
            "question_spec": public,
            "image_digest": config["image_digest"] if is_program else "",
            "resource_profile_snapshot": config if is_program else {},
            "execution_snapshot": execution,
        })
    digest = _json_digest({"spec": spec, "runtime": config})
    return {
        "template_digest": digest,
        "chapters": [
            {
                "source_chapter_id": publication.public_id,
                "title": publication.title[:160],
                "description": spec["guidance"],
                "learning_objectives": [],
                "sort_order": 1,
                "resource_profile_snapshot": config,
                "tasks": questions,
            }
        ],
    }, {"template_spec_digest": digest, **runtime}

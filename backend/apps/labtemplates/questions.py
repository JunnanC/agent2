"""Validated assessment content; private marking data never enters student projections."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn

from django.conf import settings

from .errors import TemplateValidationError
from .toolchains import TOOLCHAINS_BY_LANGUAGE

CHOICE_TYPES = frozenset({"SINGLE_CHOICE", "MULTIPLE_CHOICE"})
QUESTION_TYPES = CHOICE_TYPES | {"PROGRAMMING"}
ENTRYPOINTS = {
    "python": "main.py", "c": "main.c", "cpp": "main.cpp",
    "java": "Main.java", "go": "main.go",
}


def invalid(field: str, reason: str) -> NoReturn:
    raise TemplateValidationError(detail={field: reason})


def score_value(value: Any, *, allow_zero: bool = False) -> Decimal:
    try:
        if isinstance(value, bool):
            raise ValueError
        result = Decimal(str(value))
        if (
            not result.is_finite() or result < 0 or (result == 0 and not allow_zero)
            or result > Decimal("99999.99") or result != result.quantize(Decimal("0.01"))
        ):
            raise ValueError
    except (InvalidOperation, ValueError):
        invalid("score", "positive_decimal_with_at_most_two_places_required")
    return result


def project_files(value: Any, *, allow_empty: bool = True) -> dict[str, str]:
    if not isinstance(value, dict) or (not value and not allow_empty):
        invalid("files", "text_file_mapping_required")
    if len(value) > 200:
        invalid("files", "too_many_files")
    size = 0
    paths: set[str] = set()
    for path, content in value.items():
        if (
            not isinstance(path, str) or len(path) > 255
            or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", path)
            or any(part.startswith((".", "-")) for part in path.split("/"))
            or not isinstance(content, str) or "\x00" in content
        ):
            invalid("files", "invalid_path_or_text")
        key = path.casefold()
        if key in paths or any(key.startswith(p + "/") or p.startswith(key + "/") for p in paths):
            invalid("files", "conflicting_paths")
        paths.add(key)
        try:
            size += len(path.encode("utf-8")) + len(content.encode("utf-8"))
        except UnicodeEncodeError:
            invalid("files", "invalid_utf8")
    if size > settings.WORKSPACE_SNAPSHOT_MAX_BYTES:
        invalid("files", "project_too_large")
    return dict(value)


def normalize_question(
    *, task_type: str, public: Any, marking: Any, max_score: Any,
) -> tuple[dict[str, Any], dict[str, Any], Decimal]:
    if task_type not in QUESTION_TYPES:
        invalid("task_type", "unsupported")
    if not isinstance(public, dict) or not isinstance(marking, dict):
        invalid("question", "objects_required")
    points = score_value(max_score)
    if task_type in CHOICE_TYPES:
        if set(public) != {"options"} or set(marking) - {"correct_option_ids", "explanation"}:
            invalid("question", "unexpected_fields")
        options = public.get("options")
        if not isinstance(options, list) or not 2 <= len(options) <= 6:
            invalid("options", "two_to_six_required")
        ids: set[str] = set()
        for option in options:
            if (
                not isinstance(option, dict) or set(option) != {"id", "text"}
                or not isinstance(option["id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", option["id"])
                or option["id"] in ids or not isinstance(option["text"], str)
                or not option["text"].strip() or len(option["text"]) > 20000
            ):
                invalid("options", "unique_ids_and_nonempty_text_required")
            ids.add(option["id"])
        answers = marking.get("correct_option_ids")
        if (
            not isinstance(answers, list) or any(not isinstance(x, str) for x in answers)
            or len(set(answers)) != len(answers) or not set(answers) <= ids
            or (task_type == "SINGLE_CHOICE" and len(answers) != 1)
            or (task_type == "MULTIPLE_CHOICE" and len(answers) < 2)
        ):
            invalid("correct_option_ids", "invalid_answer_set")
        explanation = marking.get("explanation", "")
        if not isinstance(explanation, str) or len(explanation) > 20000:
            invalid("explanation", "text_required")
        return {"options": options}, {
            "correct_option_ids": sorted(answers), "explanation": explanation,
        }, points

    if set(public) != {"allowed_languages", "samples", "starter_files", "limits"}:
        invalid("question", "invalid_programming_fields")
    languages = public["allowed_languages"]
    if (
        not isinstance(languages, list) or not languages
        or any(not isinstance(x, str) or x not in TOOLCHAINS_BY_LANGUAGE for x in languages)
        or len(set(languages)) != len(languages)
    ):
        invalid("allowed_languages", "supported_unique_languages_required")
    samples = public["samples"]
    if not isinstance(samples, list) or not samples:
        invalid("samples", "at_least_one_required")
    for sample in samples:
        if (
            not isinstance(sample, dict) or set(sample) != {"input", "output"}
            or any(not isinstance(x, str) or len(x.encode("utf-8")) > 1048576
                   for x in sample.values())
        ):
            invalid("samples", "input_output_text_required")
    starters, limits = public["starter_files"], public["limits"]
    if not isinstance(starters, dict) or not isinstance(limits, dict):
        invalid("question", "language_configuration_required")
    if set(starters) != set(languages) or set(limits) != set(languages):
        invalid("question", "configuration_required_for_each_language")
    for language in languages:
        files = project_files(starters[language], allow_empty=False)
        if ENTRYPOINTS[language] not in files:
            invalid("starter_files", "default_entrypoint_required")
        limit = limits[language]
        if (
            not isinstance(limit, dict) or set(limit) != {"timeout_seconds", "memory_mb"}
            or any(isinstance(x, bool) or not isinstance(x, int) or x < 1
                   for x in limit.values())
            or limit["timeout_seconds"] > settings.TEMPLATE_CHECK_TIMEOUT_MAX_SECONDS
        ):
            invalid("limits", "positive_resource_limits_required")
    if set(marking) != {"tests_asset_id", "groups", "reference_solutions"}:
        invalid("marking_spec", "invalid_programming_fields")
    asset_id = marking["tests_asset_id"]
    if not isinstance(asset_id, str) or not re.fullmatch(r"[0-9A-Za-z]{26}", asset_id):
        invalid("tests_asset_id", "asset_id_required")
    groups = marking["groups"]
    if not isinstance(groups, list) or not groups:
        invalid("groups", "at_least_one_required")
    group_ids: set[str] = set()
    total = Decimal("0")
    for group in groups:
        if (
            not isinstance(group, dict) or set(group) != {"id", "score"}
            or not isinstance(group["id"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", group["id"])
            or group["id"] in group_ids
        ):
            invalid("groups", "unique_group_ids_required")
        group_ids.add(group["id"])
        total += score_value(group["score"])
    if total != points:
        invalid("groups", "score_sum_mismatch")
    references = marking["reference_solutions"]
    if not isinstance(references, dict) or not references or not set(references) <= set(languages):
        invalid("reference_solutions", "allowed_language_reference_required")
    for language, files in references.items():
        if ENTRYPOINTS[language] not in project_files(files, allow_empty=False):
            invalid("reference_solutions", "default_entrypoint_required")
    return dict(public), dict(marking), points


def public_question(question: Any) -> dict[str, Any]:
    """Construct a whitelist, never expose execution or marking JSON to students."""
    public = question.question_spec
    result: dict[str, Any] = {
        "id": question.public_id, "title": question.title,
        "description": question.description, "instructions": question.instructions,
        "task_type": question.task_type, "sort_order": question.sort_order,
        "max_score": str(question.max_score),
    }
    if question.task_type in CHOICE_TYPES:
        result["options"] = [
            {"id": option["id"], "text": option["text"]} for option in public["options"]
        ]
    else:
        result.update({key: public[key] for key in (
            "allowed_languages", "samples", "starter_files", "limits",
        )})
    return result


def assessment_snapshot(
    version: Any, *, run_reference: bool = False, include_case_metadata: bool = False,
) -> dict[str, Any] | None:
    """Freeze the validated public questions and private grading configuration."""
    from .models import TemplateTask

    questions = list(TemplateTask.objects.filter(
        chapter__template_version=version, active=True,
    ).select_related("chapter").order_by(
        "chapter__sort_order", "sort_order", "id",
    ))
    if not questions or not any(question.task_type in QUESTION_TYPES for question in questions):
        return None
    if any(question.task_type not in QUESTION_TYPES for question in questions):
        invalid("task_type", "mixed_legacy_and_assessment_questions")
    records = []
    programming = False
    for question in questions:
        public, private, points = normalize_question(
            task_type=question.task_type, public=question.question_spec,
            marking=question.marking_spec, max_score=question.max_score,
        )
        programming = programming or question.task_type == "PROGRAMMING"
        records.append({
            "id": question.public_id, "chapter_id": question.chapter.public_id,
            "title": question.title, "description": question.description,
            "instructions": question.instructions, "task_type": question.task_type,
            "sort_order": question.sort_order, "question_spec": public,
            "marking_spec": private, "max_score": str(points),
        })
    if programming:
        from apps.provisioning.adapters import ASSESSMENT_RUNTIME_DRIVERS

        if not all((version.runtime_adapter_id, version.image_id, version.resource_profile_id)):
            invalid("runtime", "programming_runtime_required")
        if version.runtime_adapter.driver not in ASSESSMENT_RUNTIME_DRIVERS:
            invalid("runtime", "stdio_requires_docker_local")
        if not version.image.is_ready or version.runtime_adapter.status != "ENABLED":
            invalid("runtime", "approved_image_and_enabled_runtime_required")
        from apps.provisioning.assessment_judge import read_private_tests, validated_groups

        for record in records:
            if record["task_type"] != "PROGRAMMING":
                continue
            private = record["marking_spec"]
            asset, tests = read_private_tests(
                asset_id=private["tests_asset_id"], template_version_id=version.public_id,
            )
            groups = validated_groups(tests, private["groups"])
            record["tests_digest"] = asset.digest_sha256
            if include_case_metadata:
                cases = record["question_spec"]["samples"] + [
                    case for group in groups for case in group["cases"]
                ]
                record["case_metadata"] = {
                    "case_count": len(cases),
                    "visible_cases": record["question_spec"]["samples"][:2],
                }
            profile = version.resource_profile
            for limit in record["question_spec"]["limits"].values():
                if limit["memory_mb"] > (profile.memory_limit_mb or profile.memory_mb):
                    invalid("limits", "exceeds_resource_profile")
            if run_reference:
                _precheck_references(version, record, groups)
    chapters = [{
        "id": chapter.public_id, "title": chapter.title,
        "description": chapter.description, "learning_objectives": chapter.learning_objectives,
        "sort_order": chapter.sort_order,
    } for chapter in version.chapters.order_by("sort_order", "id")]
    if any(not any(q["chapter_id"] == c["id"] for q in records) for c in chapters):
        invalid("chapters", "each_chapter_requires_questions")
    return {
        "assessment_schema_version": 1, "questions": records, "chapters": chapters,
        "report_policy": version.report_policy if programming else {},
        "review_policy": version.review_policy if programming else {},
        "runtime_type": version.runtime_type if programming else "",
        "runtime": {
            "driver": version.runtime_adapter.driver,
            "config_ref": version.runtime_adapter.config_ref,
            "registry": version.image.registry, "repository": version.image.repository,
            "digest": version.image.digest, "resource_profile": version.resource_profile.public_id,
            "resource_limits": {
                "cpu_millicores": version.resource_profile.cpu_limit_millicores
                or version.resource_profile.cpu_millicores,
                "memory_mb": version.resource_profile.memory_limit_mb
                or version.resource_profile.memory_mb,
                "disk_gb": version.resource_profile.disk_gb,
                "network_mode": version.resource_profile.network_mode,
            },
        } if programming else {},
        "retention_days": version.retention_days,
    }


def _precheck_references(
    version: Any, record: dict[str, Any], groups: list[dict[str, Any]],
) -> None:
    import uuid

    import docker

    from apps.provisioning.assessment_judge import grade_groups
    from apps.provisioning.stdio import TOOLCHAIN_SMOKE, StdioExecutor, stdio_outputs_match

    if settings.LOCAL_RUNTIME_MODE != "REAL":
        invalid("runtime", "real_reference_execution_required")
    config = settings.RUNTIME_ADAPTER_CONFIGS.get(version.runtime_adapter.config_ref, {})
    client = docker.DockerClient(
        base_url=config.get("base_url", config.get("docker_host", settings.LOCAL_DOCKER_HOST)),
        timeout=30,
    )
    image_ref = f"{version.image.registry}/{version.image.repository}@{version.image.digest}"
    try:
        for language in record["question_spec"]["allowed_languages"]:
            executor = StdioExecutor(client, image_ref, owner=f"toolchain-{uuid.uuid4().hex}")
            try:
                compilation, results = executor.execute(
                    language=language, files=TOOLCHAIN_SMOKE[language], inputs=["7\n"],
                    **record["question_spec"]["limits"][language],
                )
                if (
                    compilation or results[0].status != "PASSED"
                    or not stdio_outputs_match(results[0].stdout, "7")
                ):
                    invalid("allowed_languages", "toolchain_smoke_failed")
            finally:
                executor.close()
        for language, files in record["marking_spec"]["reference_solutions"].items():
            executor = StdioExecutor(client, image_ref, owner=f"precheck-{uuid.uuid4().hex}")
            try:
                limits = record["question_spec"]["limits"][language]
                result = grade_groups(
                    executor=executor, language=language, files=files, groups=groups,
                    scores=record["marking_spec"]["groups"], limits=limits,
                )
                if Decimal(result["score"]) != Decimal(record["max_score"]):
                    invalid("reference_solutions", "reference_does_not_pass_all_hidden_tests")
                compilation, results = executor.execute(
                    language=language, files=files,
                    inputs=[sample["input"] for sample in record["question_spec"]["samples"]],
                    **limits,
                )
                if compilation or any(
                    result.status != "PASSED"
                    or not stdio_outputs_match(result.stdout, sample["output"])
                    for result, sample in zip(
                        results, record["question_spec"]["samples"], strict=True,
                    )
                ):
                    invalid("reference_solutions", "reference_does_not_pass_samples")
            finally:
                executor.close()
    finally:
        client.close()

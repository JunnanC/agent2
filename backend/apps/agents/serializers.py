from typing import Any

from rest_framework import serializers

from apps.core.redaction import redact


class AgentResponseMetaSerializer(serializers.Serializer):
    trace_id = serializers.CharField()


class AgentEnvelopeSerializer(serializers.Serializer):
    data = serializers.JSONField()
    meta = AgentResponseMetaSerializer()


class ProfileWriteSerializer(serializers.Serializer):
    modes = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[
                "KNOWLEDGE_QA",
                "SOCRATIC_HINT",
                "DEBUG_ASSIST",
                "REPORT_COACH",
                "WORKSPACE_ASSIST",
            ]
        ),
        allow_empty=False,
    )
    model_route = serializers.CharField(required=False, allow_blank=True, max_length=128)
    budget = serializers.DictField(required=False)
    definition_id = serializers.CharField(required=False, allow_blank=True)
    knowledge_base_id = serializers.CharField(required=False, allow_blank=True)
    prompt_version_id = serializers.CharField(required=False, allow_blank=True)
    tool_policy_id = serializers.CharField(required=False, allow_blank=True)


class ProfilePatchSerializer(serializers.Serializer):
    modes = serializers.ListField(child=serializers.CharField(), required=False)
    model_route = serializers.CharField(required=False, allow_blank=True, max_length=128)
    budget = serializers.DictField(required=False)
    knowledge_base_id = serializers.CharField(required=False, allow_blank=True)
    prompt_version_id = serializers.CharField(required=False, allow_blank=True)
    tool_policy_id = serializers.CharField(required=False, allow_blank=True)


class KnowledgeBaseWriteSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=1, max_length=180)
    description = serializers.CharField(required=False, allow_blank=True, max_length=500)


class SourceWriteSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=["COURSE_MATERIAL", "LAB_MANUAL", "TEACHER_FAQ", "STATIC"]
    )
    title = serializers.CharField(min_length=1, max_length=180)
    material_version_id = serializers.CharField(required=False, allow_blank=True)


class SourceVersionWriteSerializer(serializers.Serializer):
    object_asset_id = serializers.CharField(required=False, allow_blank=True)


class SourceAssetUploadSerializer(serializers.Serializer):
    file_name = serializers.CharField(min_length=1, max_length=255)
    media_type = serializers.ChoiceField(choices=["text/markdown", "text/plain"])
    size_bytes = serializers.IntegerField(min_value=1)
    digest_sha256 = serializers.RegexField(r"^[0-9a-fA-F]{64}$")


class PromptWriteSerializer(serializers.Serializer):
    body = serializers.CharField(min_length=1)
    template_id = serializers.CharField(required=False, allow_blank=True)


class SessionWriteSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=[
            "KNOWLEDGE_QA",
            "SOCRATIC_HINT",
            "DEBUG_ASSIST",
            "REPORT_COACH",
            "WORKSPACE_ASSIST",
        ]
    )


class MessageWriteSerializer(serializers.Serializer):
    body = serializers.CharField(min_length=1)


class ToolWriteSerializer(serializers.Serializer):
    tool_name = serializers.CharField(max_length=128)
    arguments = serializers.DictField(required=False)


class ToolDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["APPROVED", "REJECTED"])
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class FeedbackWriteSerializer(serializers.Serializer):
    rating = serializers.ChoiceField(choices=["USEFUL", "NOT_USEFUL"])
    issue_type = serializers.CharField(required=False, allow_blank=True, max_length=64)
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class TriageSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["OPEN", "TRIAGED", "CLOSED"])
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class ModelRouteWriteSerializer(serializers.Serializer):
    key = serializers.SlugField(max_length=64)
    provider = serializers.CharField(max_length=64)
    model_name = serializers.CharField(max_length=128)
    fallback_routes = serializers.ListField(child=serializers.CharField(), required=False)
    regions = serializers.ListField(child=serializers.CharField(), required=False)
    sensitive_data_allowed = serializers.BooleanField(required=False, default=False)
    timeout_seconds = serializers.IntegerField(
        min_value=1, max_value=300, required=False, default=30
    )
    max_tokens = serializers.IntegerField(
        min_value=1, max_value=100000, required=False, default=4096
    )
    cost_per_1k_input_minor = serializers.IntegerField(min_value=0, required=False, default=0)
    cost_per_1k_output_minor = serializers.IntegerField(min_value=0, required=False, default=0)


class ModelRoutePatchSerializer(serializers.Serializer):
    fallback_routes = serializers.ListField(child=serializers.CharField(), required=False)
    regions = serializers.ListField(child=serializers.CharField(), required=False)
    sensitive_data_allowed = serializers.BooleanField(required=False)
    timeout_seconds = serializers.IntegerField(min_value=1, max_value=300, required=False)
    max_tokens = serializers.IntegerField(min_value=1, max_value=100000, required=False)
    cost_per_1k_input_minor = serializers.IntegerField(min_value=0, required=False)
    cost_per_1k_output_minor = serializers.IntegerField(min_value=0, required=False)
    status = serializers.ChoiceField(choices=["ACTIVE", "RETIRED"], required=False)


class ToolPolicyWriteSerializer(serializers.Serializer):
    key = serializers.SlugField(max_length=64)
    tool_name = serializers.CharField(max_length=128)
    risk = serializers.ChoiceField(choices=["LOW", "MEDIUM", "HIGH", "FORBIDDEN"])
    schema = serializers.DictField(required=False)
    allowlist = serializers.ListField(child=serializers.CharField(), required=False)
    redaction_rules = serializers.ListField(child=serializers.CharField(), required=False)
    timeout_seconds = serializers.IntegerField(
        min_value=1, max_value=300, required=False, default=30
    )
    output_limit = serializers.IntegerField(
        min_value=1, max_value=1048576, required=False, default=8192
    )


class ToolPolicyPatchSerializer(serializers.Serializer):
    risk = serializers.ChoiceField(
        choices=["LOW", "MEDIUM", "HIGH", "FORBIDDEN"], required=False
    )
    schema = serializers.DictField(required=False)
    allowlist = serializers.ListField(child=serializers.CharField(), required=False)
    redaction_rules = serializers.ListField(child=serializers.CharField(), required=False)
    timeout_seconds = serializers.IntegerField(min_value=1, max_value=300, required=False)
    output_limit = serializers.IntegerField(min_value=1, max_value=1048576, required=False)
    status = serializers.ChoiceField(choices=["ACTIVE", "RETIRED"], required=False)


class EvalSuiteWriteSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=1, max_length=180)
    threshold = serializers.DictField(required=False)


class EvalCaseWriteSerializer(serializers.Serializer):
    key = serializers.SlugField(max_length=128)
    category = serializers.CharField(min_length=1, max_length=64)
    prompt = serializers.CharField(min_length=1)
    expected = serializers.DictField(required=False)
    mandatory = serializers.BooleanField(required=False, default=False)


class PlatformEvalRunWriteSerializer(serializers.Serializer):
    suite_id = serializers.CharField()
    profile_id = serializers.CharField(required=False, allow_blank=True)


def profile_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "version_no": item.version_no,
        "status": item.status,
        "modes": item.modes,
        "model_route": item.model_route,
        "budget": item.budget,
        "knowledge_base_id": item.knowledge_base.public_id if item.knowledge_base else None,
        "prompt_version_id": item.prompt_version.public_id if item.prompt_version else None,
        "tool_policy_id": item.tool_policy.public_id if item.tool_policy else None,
        "last_eval_run_id": item.last_eval_run.public_id if item.last_eval_run else None,
        "row_version": item.row_version,
        "effective_from": item.effective_from,
        "effective_until": item.effective_until,
    }


def knowledge_base_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "row_version": item.row_version,
    }


def source_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "knowledge_base_id": item.knowledge_base.public_id,
        "source_type": item.source_type,
        "title": item.title,
        "status": item.status,
        "audience": item.audience,
        "row_version": item.row_version,
    }


def source_version_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "source_id": item.source.public_id,
        "version_no": item.version_no,
        "digest_sha256": item.digest_sha256,
        "status": item.status,
        "audience": item.audience,
        "indexed_at": item.indexed_at,
        "row_version": item.row_version,
    }


def ingestion_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "source_version_id": item.source_version.public_id,
        "status": item.status,
        "chunk_count": item.chunk_count,
        "indexed_count": item.indexed_count,
        "filtered_count": item.filtered_count,
        "error_code": item.error_code,
        "trace_id": item.trace_id,
        "row_version": item.row_version,
    }


def prompt_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id if item.course else None,
        "name": item.name,
        "template_type": item.template_type,
        "platform_managed": item.platform_managed,
        "status": item.status,
        "row_version": item.row_version,
    }


def prompt_version_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "template_id": item.template.public_id,
        "version_no": item.version_no,
        "digest_sha256": item.digest_sha256,
        "status": item.status,
        "row_version": item.row_version,
    }


def session_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "enrollment_id": item.enrollment.public_id,
        "task_id": item.task.public_id if item.task else None,
        "mode": item.mode,
        "status": item.status,
        "profile_id": item.profile.public_id,
        "profile_version": item.profile_version,
        "prompt_version_id": item.prompt_version.public_id if item.prompt_version else None,
        "knowledge_base_id": item.knowledge_base.public_id if item.knowledge_base else None,
        "knowledge_snapshot": item.knowledge_snapshot,
        "tool_policy_id": item.tool_policy.public_id if item.tool_policy else None,
        "model_route": item.model_route,
        "budget": item.budget_snapshot,
        "row_version": item.row_version,
        "trace_id": item.trace_id,
    }


def citation_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "source_version_id": item.source_version.public_id,
        "title": item.title,
        "snippet": item.snippet,
        "score": item.score,
        "accessible": item.accessible,
        "asset_id": item.download_asset.public_id if item.download_asset else None,
    }


def message_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "role": item.role,
        "body": item.body,
        "status": item.status,
        "citation_status": item.citation_status,
        "token_count": item.token_count,
        "cost_minor": item.cost_minor,
        "created_at": item.created_at,
        "trace_id": item.trace_id,
        "citations": [
            citation_data(c)
            for c in item.citations.select_related("source_version", "download_asset").order_by(
                "rank"
            )
        ],
        "tool_calls": [
            tool_call_data(call)
            for call in item.tool_calls.select_related("session", "state").order_by("created_at")
        ],
    }


def tool_call_data(item: Any) -> dict[str, Any]:
    state = getattr(item, "state", None)
    return {
        "public_id": item.public_id,
        "session_id": item.session.public_id,
        "tool_name": item.tool_name,
        "risk": item.risk,
        "arguments_digest": item.arguments_digest,
        "state": {
            "public_id": state.public_id,
            "status": state.status,
            "output": state.output_masked,
            "error_code": state.error_code,
            "row_version": state.row_version,
        }
        if state
        else None,
        "trace_id": item.trace_id,
    }


def eval_suite_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id if item.course else None,
        "name": item.name,
        "platform_managed": item.platform_managed,
        "threshold": item.threshold,
        "status": item.status,
        "row_version": item.row_version,
        "case_count": item.cases.count(),
    }


def eval_case_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "suite_id": item.suite.public_id,
        "key": item.key,
        "category": item.category,
        "prompt": item.prompt,
        "expected": item.expected,
        "mandatory": item.mandatory,
        "created_at": item.created_at,
    }


def model_route_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "key": item.key,
        "version_no": item.version_no,
        "provider": item.provider,
        "model_name": item.model_name,
        "fallback_routes": item.fallback_routes,
        "regions": item.regions,
        "sensitive_data_allowed": item.sensitive_data_allowed,
        "timeout_seconds": item.timeout_seconds,
        "max_tokens": item.max_tokens,
        "cost_per_1k_input_minor": item.cost_per_1k_input_minor,
        "cost_per_1k_output_minor": item.cost_per_1k_output_minor,
        "status": item.status,
        "row_version": item.row_version,
    }


def tool_policy_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "key": item.key,
        "version_no": item.version_no,
        "tool_name": item.tool_name,
        "risk": item.risk,
        "schema": item.schema,
        "allowlist": item.allowlist,
        "redaction_rules": item.redaction_rules,
        "timeout_seconds": item.timeout_seconds,
        "output_limit": item.output_limit,
        "status": item.status,
        "row_version": item.row_version,
    }


def eval_run_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "suite_id": item.suite.public_id,
        "profile_id": item.profile.public_id if item.profile else None,
        "status": item.status,
        "scores": item.scores,
        "passed": item.passed,
        "definition_version": item.definition_version,
        "profile_version": item.profile_version,
        "prompt_version": item.prompt_version,
        "knowledge_version": item.knowledge_version,
        "tool_policy_version": item.tool_policy_version,
        "model_route_row_version": item.model_route_row_version,
        "tool_policy_row_version": item.tool_policy_row_version,
        "model_route": item.model_route,
        "trace_id": item.trace_id,
        "row_version": item.row_version,
    }


def feedback_data(item: Any) -> dict[str, Any]:
    triage = getattr(item, "triage", None)
    return {
        "public_id": item.public_id,
        "session_id": item.session.public_id,
        "message_id": item.message.public_id,
        "rating": item.rating,
        "issue_type": item.issue_type,
        "note": redact(item.note),
        "triage_status": triage.status if triage else "OPEN",
        "triage_note": triage.note if triage else "",
        "row_version": triage.row_version if triage else None,
        "created_at": item.created_at,
    }

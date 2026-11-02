from typing import Any

from rest_framework import serializers


class P13AnalyticsResponseSerializer(serializers.Serializer):
    """Named placeholder for envelope responses represented by view helpers."""

    pass


class RiskResolveSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=("ACKNOWLEDGED", "IGNORED", "CLOSED"))
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


def daily_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "period_start": item.period_start,
        "metrics": item.metrics,
        "projection_version": item.projection_version,
        "source_cursor": item.source_cursor,
        "calculated_at": item.calculated_at,
    }


def risk_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "student_id": item.student.public_id,
        "task_id": item.task.public_id if item.task else None,
        "kind": item.kind,
        "severity": item.severity,
        "status": item.status,
        "explanation": item.explanation_masked,
        "evidence": item.evidence,
        "source_refs": item.source_refs,
        "rule_version": item.rule_version,
        "model_version": item.model_version,
        "valid_until": item.valid_until,
        "row_version": item.row_version,
    }


def quality_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "period_start": item.period_start,
        "quality_score": item.quality_score,
        "metrics": item.metrics,
        "projection_version": item.projection_version,
        "source_cursor": item.source_cursor,
        "calculated_at": item.calculated_at,
    }


def recommendation_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "task_id": item.task.public_id if item.task else None,
        "kind": item.kind,
        "title": item.title,
        "explanation": item.explanation_masked,
        "evidence": item.evidence,
        "source_refs": item.source_refs,
        "rule_version": item.rule_version,
        "model_version": item.model_version,
        "valid_until": item.valid_until,
    }


def cost_data(item: Any) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id if item.course else None,
        "period_start": item.period_start,
        "resource_type": item.resource_type,
        "amount_minor": item.amount_minor,
        "units": item.units,
        "metadata": item.metadata,
        "projection_version": item.projection_version,
        "source_cursor": item.source_cursor,
        "calculated_at": item.calculated_at,
    }

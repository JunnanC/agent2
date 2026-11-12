from decimal import Decimal
from typing import Any

from rest_framework import serializers

from .models import (
    Rubric,
    RubricCriterion,
    RubricVersion,
)


class RubricWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    description = serializers.CharField(required=False, allow_blank=True)


class RubricVersionCreateSerializer(serializers.Serializer):
    source_version_id = serializers.CharField(max_length=26, required=False)
    title = serializers.CharField(max_length=180, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    total_score = serializers.DecimalField(
        max_digits=9, decimal_places=2, min_value=Decimal("0.01"), required=False
    )
    criteria = serializers.ListField(child=serializers.DictField(), required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("source_version_id"):
            extra = set(attrs) - {"source_version_id"}
            if extra:
                raise serializers.ValidationError({
                    "source_version_id": "clone_request_cannot_override_fields"
                })
            return attrs
        required = {"title", "total_score", "criteria"}
        missing = sorted(required - set(attrs))
        if missing:
            raise serializers.ValidationError({field: "required" for field in missing})
        return attrs


class RubricVersionWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180)
    description = serializers.CharField(required=False, allow_blank=True)
    total_score = serializers.DecimalField(
        max_digits=9, decimal_places=2, min_value=Decimal("0.01")
    )
    criteria = serializers.ListField(child=serializers.DictField())


class RubricCriterionDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    position = serializers.IntegerField()
    title = serializers.CharField()
    description = serializers.CharField()
    guidance = serializers.CharField()
    max_score = serializers.DecimalField(max_digits=9, decimal_places=2)
    weight_basis_points = serializers.IntegerField()


class RubricVersionDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    rubric_id = serializers.CharField()
    version_no = serializers.IntegerField()
    title = serializers.CharField()
    description = serializers.CharField()
    total_score = serializers.DecimalField(max_digits=9, decimal_places=2)
    status = serializers.ChoiceField(choices=RubricVersion.Status.choices)
    published_at = serializers.DateTimeField(allow_null=True)
    row_version = serializers.IntegerField()
    criteria = RubricCriterionDataSerializer(many=True)


class RubricDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    course_id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    owner_id = serializers.CharField()
    status = serializers.ChoiceField(choices=Rubric.Status.choices)
    current_version_id = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()


class RubricResponseSerializer(serializers.Serializer):
    data = RubricDataSerializer()
    meta = serializers.DictField()


class RubricListResponseSerializer(serializers.Serializer):
    data = RubricDataSerializer(many=True)
    meta = serializers.DictField()


class RubricVersionResponseSerializer(serializers.Serializer):
    data = RubricVersionDataSerializer()
    meta = serializers.DictField()


class RubricVersionListResponseSerializer(serializers.Serializer):
    data = RubricVersionDataSerializer(many=True)
    meta = serializers.DictField()


def criterion_data(item: RubricCriterion) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "position": item.position,
        "title": item.title,
        "description": item.description,
        "guidance": item.guidance,
        "max_score": item.max_score,
        "weight_basis_points": item.weight_basis_points,
    }


def version_data(item: RubricVersion) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "rubric_id": item.rubric.public_id,
        "version_no": item.version_no,
        "title": item.title,
        "description": item.description,
        "total_score": item.total_score,
        "status": item.status,
        "published_at": item.published_at,
        "row_version": item.row_version,
        "criteria": [
            criterion_data(value)
            for value in item.criteria.filter(is_active=True).order_by("position")
        ],
    }


def rubric_data(item: Rubric) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "name": item.name,
        "description": item.description,
        "owner_id": item.owner.public_id,
        "status": item.status,
        "current_version_id": (item.current_version.public_id if item.current_version_id else None),
        "row_version": item.row_version,
    }

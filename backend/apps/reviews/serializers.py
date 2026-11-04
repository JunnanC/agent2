from decimal import Decimal
from typing import Any

from django.db.models import Count
from rest_framework import serializers

from apps.reports.serializers import (
    ReportVersionDataSerializer,
    SystemArtifactDataSerializer,
    report_version_data,
    system_artifact_data,
)

from .models import (
    AIScoreBatch,
    AIScoreSuggestion,
    AnnotationRevision,
    AutoCheckRun,
    Review,
    ReviewAnnotation,
    ReviewDecision,
    Rubric,
    RubricCriterion,
    RubricVersion,
    SimilarityMatch,
    SimilarityRun,
)


class RubricWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    description = serializers.CharField(required=False, allow_blank=True)


class AIScoreBatchWriteSerializer(serializers.Serializer):
    publication_id = serializers.CharField(max_length=26)


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


class CriterionScoreWriteItemSerializer(serializers.Serializer):
    criterion_id = serializers.CharField(max_length=26)
    score = serializers.DecimalField(max_digits=9, decimal_places=2, min_value=Decimal("0"))
    note = serializers.CharField(required=False, allow_blank=True, max_length=8000)


class CriterionScoresWriteSerializer(serializers.Serializer):
    scores = CriterionScoreWriteItemSerializer(many=True, allow_empty=False)


class AnnotationWriteSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(choices=ReviewAnnotation.TargetType.choices)
    target_ref = serializers.CharField(max_length=26)
    anchor = serializers.JSONField()
    body = serializers.CharField(max_length=8000)


class AnnotationRevisionWriteSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=8000)


class ReviewDecisionWriteSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=ReviewDecision.Decision.choices)
    score = serializers.DecimalField(
        max_digits=9, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True
    )
    feedback = serializers.CharField(required=False, allow_blank=True, max_length=12000)


class SimilarityStartSerializer(serializers.Serializer):
    review_id = serializers.CharField(max_length=26)


class ReviewListDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    publication_id = serializers.CharField()
    publication_title = serializers.CharField()
    student_id = serializers.CharField()
    student_name = serializers.CharField()
    round_no = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Review.Status.choices)
    target_kind = serializers.CharField()
    created_at = serializers.DateTimeField()
    row_version = serializers.IntegerField()


class ReviewListResponseSerializer(serializers.Serializer):
    data = ReviewListDataSerializer(many=True)
    meta = serializers.DictField()


class CriterionScoreDataSerializer(RubricCriterionDataSerializer):
    score = serializers.DecimalField(max_digits=9, decimal_places=2, allow_null=True)
    note = serializers.CharField()
    score_row_version = serializers.IntegerField(allow_null=True)
    revision_no = serializers.IntegerField()


class CriterionScoresDataSerializer(serializers.Serializer):
    review_id = serializers.CharField()
    rubric_version = RubricVersionDataSerializer()
    criteria = CriterionScoreDataSerializer(many=True)
    review_row_version = serializers.IntegerField()


class AnnotationRevisionDataSerializer(serializers.Serializer):
    revision_no = serializers.IntegerField()
    action = serializers.ChoiceField(choices=AnnotationRevision.Action.choices)
    body = serializers.CharField()
    actor_id = serializers.CharField()
    created_at = serializers.DateTimeField()
    trace_id = serializers.CharField()


class AnnotationDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    review_id = serializers.CharField()
    author_id = serializers.CharField()
    target_type = serializers.ChoiceField(choices=ReviewAnnotation.TargetType.choices)
    target_ref = serializers.CharField()
    object_digest = serializers.CharField()
    anchor = serializers.JSONField()
    status = serializers.ChoiceField(choices=ReviewAnnotation.Status.choices)
    body = serializers.CharField()
    current_revision_no = serializers.IntegerField()
    row_version = serializers.IntegerField()
    revisions = AnnotationRevisionDataSerializer(many=True, required=False)


class AutoCheckDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    checker_type = serializers.CharField()
    rule_digest = serializers.CharField()
    artifact_digest = serializers.CharField()
    execution_rule_summary = serializers.DictField()
    execution_rule_digest = serializers.CharField()
    status = serializers.ChoiceField(choices=AutoCheckRun.Status.choices)
    attempt_count = serializers.IntegerField()
    result_summary = serializers.DictField()
    evidence = serializers.ListField(child=serializers.DictField())
    error_code = serializers.CharField()
    trace_id = serializers.CharField()
    duration_ms = serializers.IntegerField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)


class DecisionDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    decision = serializers.ChoiceField(choices=ReviewDecision.Decision.choices)
    score = serializers.DecimalField(max_digits=9, decimal_places=2)
    feedback = serializers.CharField()
    decided_by = serializers.CharField()
    criterion_snapshot = serializers.ListField(child=serializers.DictField())
    trace_id = serializers.CharField()
    created_at = serializers.DateTimeField()
    review_row_version = serializers.IntegerField(required=False)
    task_status = serializers.CharField(required=False)
    task_row_version = serializers.IntegerField(required=False)


class SimilarityRunDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    review_id = serializers.CharField()
    algorithm_version = serializers.CharField()
    candidate_scope = serializers.CharField()
    input_digest = serializers.CharField()
    threshold = serializers.DecimalField(max_digits=5, decimal_places=4)
    candidate_count = serializers.IntegerField()
    status = serializers.ChoiceField(choices=SimilarityRun.Status.choices)
    error_code = serializers.CharField()
    trace_id = serializers.CharField()
    retention_until = serializers.DateTimeField()
    row_version = serializers.IntegerField()


class SubmissionDataSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("REPORT", "SYSTEM_ARTIFACT"))
    version = ReportVersionDataSerializer(required=False)
    artifact = SystemArtifactDataSerializer(required=False)


class ReviewDetailDataSerializer(ReviewListDataSerializer):
    project = serializers.DictField(required=False)
    rubric_version_id = serializers.CharField()
    scores = CriterionScoresDataSerializer()
    annotations = AnnotationDataSerializer(many=True)
    auto_checks = AutoCheckDataSerializer(many=True)
    similarity_runs = SimilarityRunDataSerializer(many=True)
    decision = DecisionDataSerializer(allow_null=True)
    submission = SubmissionDataSerializer()


class ReviewDetailResponseSerializer(serializers.Serializer):
    data = ReviewDetailDataSerializer()
    meta = serializers.DictField()


class CriterionScoresResponseSerializer(serializers.Serializer):
    data = CriterionScoresDataSerializer()
    meta = serializers.DictField()


class AnnotationResponseSerializer(serializers.Serializer):
    data = AnnotationDataSerializer()
    meta = serializers.DictField()


class AnnotationListResponseSerializer(serializers.Serializer):
    data = AnnotationDataSerializer(many=True)
    meta = serializers.DictField()


class ReviewDecisionResponseSerializer(serializers.Serializer):
    data = DecisionDataSerializer()
    meta = serializers.DictField()


class ReviewRoundDataSerializer(serializers.Serializer):
    review_id = serializers.CharField()
    round_no = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Review.Status.choices)
    scores = CriterionScoresDataSerializer(allow_null=True)
    annotations = AnnotationDataSerializer(many=True)
    decision = DecisionDataSerializer(allow_null=True)


class ReviewResultDataSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    task_status = serializers.CharField()
    rounds = ReviewRoundDataSerializer(many=True)
    allowed_actions = serializers.ListField(child=serializers.CharField())


class ReviewResultResponseSerializer(serializers.Serializer):
    data = ReviewResultDataSerializer()
    meta = serializers.DictField()


class SimilarityRunResponseSerializer(serializers.Serializer):
    data = SimilarityRunDataSerializer()
    meta = serializers.DictField()


class SimilarityMatchDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    candidate_report_version_id = serializers.CharField()
    candidate_task_id = serializers.CharField()
    candidate_student_id = serializers.CharField()
    candidate_student_name = serializers.CharField()
    score = serializers.DecimalField(max_digits=5, decimal_places=4)
    evidence = serializers.ListField(child=serializers.DictField())
    evidence_purged_at = serializers.DateTimeField(allow_null=True)
    retention_until = serializers.DateTimeField()


class SimilarityMatchListResponseSerializer(serializers.Serializer):
    data = SimilarityMatchDataSerializer(many=True)
    meta = serializers.DictField()


class ReviewMonitorDataSerializer(serializers.Serializer):
    review_counts = serializers.DictField(child=serializers.IntegerField())
    auto_check_failures = serializers.IntegerField()
    similarity_counts = serializers.DictField(child=serializers.IntegerField())
    latest_trace_id = serializers.CharField()


class ReviewMonitorResponseSerializer(serializers.Serializer):
    data = ReviewMonitorDataSerializer()
    meta = serializers.DictField()


class AIScoreSuggestionDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    review_id = serializers.CharField()
    student_id = serializers.CharField()
    student_name = serializers.CharField()
    status = serializers.ChoiceField(choices=AIScoreSuggestion.Status.choices)
    review_row_version = serializers.IntegerField()
    criteria = serializers.ListField(child=serializers.DictField())
    total_score = serializers.DecimalField(max_digits=9, decimal_places=2, allow_null=True)
    model_name = serializers.CharField()
    error_code = serializers.CharField()
    accepted_by = serializers.CharField(allow_null=True)
    accepted_at = serializers.DateTimeField(allow_null=True)
    row_version = serializers.IntegerField()


class AIScoreBatchDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    course_id = serializers.CharField()
    publication_id = serializers.CharField()
    publication_title = serializers.CharField()
    created_by = serializers.CharField()
    status = serializers.ChoiceField(choices=AIScoreBatch.Status.choices)
    entry_count = serializers.IntegerField()
    counts = serializers.DictField(child=serializers.IntegerField())
    row_version = serializers.IntegerField()


class AIScoreBatchResponseSerializer(serializers.Serializer):
    data = serializers.DictField()
    meta = serializers.DictField()


class AIScoreBatchDataResponseSerializer(serializers.Serializer):
    data = AIScoreBatchDataSerializer()
    meta = serializers.DictField()


class AIScoreBatchDetailDataSerializer(serializers.Serializer):
    batch = AIScoreBatchDataSerializer()
    suggestions = AIScoreSuggestionDataSerializer(many=True)
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()


class AIScoreBatchDetailResponseSerializer(serializers.Serializer):
    data = AIScoreBatchDetailDataSerializer()
    meta = serializers.DictField()


class AIScoreSuggestionResponseSerializer(serializers.Serializer):
    data = AIScoreSuggestionDataSerializer()
    meta = serializers.DictField()


def review_list_data(item: Review) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "task_id": item.task.public_id,
        "publication_id": item.task.publication.public_id,
        "publication_title": item.task.publication.title,
        "student_id": item.task.student.public_id,
        "student_name": item.task.student.display_name,
        "round_no": item.round_no,
        "status": item.status,
        "target_kind": "REPORT" if item.report_version_id else "SYSTEM_ARTIFACT",
        "created_at": item.created_at,
        "row_version": item.row_version,
    }


def ai_score_suggestion_data(item: AIScoreSuggestion) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "review_id": item.review.public_id,
        "student_id": item.review.task.student.public_id,
        "student_name": item.review.task.student.display_name,
        "status": item.status,
        "review_row_version": item.review_row_version,
        "criteria": item.criteria,
        "total_score": item.total_score,
        "model_name": item.model_name,
        "error_code": item.error_code,
        "accepted_by": item.accepted_by.public_id if item.accepted_by_id else None,
        "accepted_at": item.accepted_at,
        "row_version": item.row_version,
    }


def ai_score_batch_data(item: AIScoreBatch) -> dict[str, Any]:
    counts = {
        row["status"]: row["count"]
        for row in item.suggestions.values("status").annotate(count=Count("id"))
    }
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "publication_id": item.publication.public_id,
        "publication_title": item.publication.title,
        "created_by": item.created_by.public_id,
        "status": item.status,
        "entry_count": item.entry_count,
        "counts": counts,
        "row_version": item.row_version,
    }


def criterion_scores_data(item: Review) -> dict[str, Any]:
    projections = {value.criterion_id: value for value in item.criterion_scores.all()}
    criteria = []
    for criterion in item.rubric_version.criteria.filter(is_active=True).order_by("position"):
        score = projections.get(criterion.pk)
        criteria.append({
            **criterion_data(criterion),
            "score": score.score if score else None,
            "note": score.note if score else "",
            "score_row_version": score.row_version if score else None,
            "revision_no": score.revision_no if score else 0,
        })
    return {
        "review_id": item.public_id,
        "rubric_version": version_data(item.rubric_version),
        "criteria": criteria,
        "review_row_version": item.row_version,
    }


def annotation_data(item: ReviewAnnotation, *, include_history: bool = True) -> dict[str, Any]:
    revisions = list(item.revisions.order_by("revision_no"))
    current = revisions[-1] if revisions else None
    data = {
        "public_id": item.public_id,
        "review_id": item.review.public_id,
        "author_id": item.author.public_id,
        "target_type": item.target_type,
        "target_ref": (
            item.report_version.public_id if item.report_version_id else item.asset.public_id
        ),
        "object_digest": item.object_digest,
        "anchor": item.anchor,
        "status": item.status,
        "body": (
            current.body
            if current and current.action == AnnotationRevision.Action.UPSERT
            else ""
        ),
        "current_revision_no": item.current_revision_no,
        "row_version": item.row_version,
    }
    if include_history:
        data["revisions"] = [
            {
                "revision_no": revision.revision_no,
                "action": revision.action,
                "body": revision.body,
                "actor_id": revision.actor.public_id,
                "created_at": revision.created_at,
                "trace_id": revision.trace_id,
            }
            for revision in revisions
        ]
    return data


def auto_check_data(item: AutoCheckRun) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "checker_type": item.checker_type,
        "rule_digest": item.rule_digest,
        "artifact_digest": item.artifact_digest,
        "execution_rule_summary": item.execution_rule_summary,
        "execution_rule_digest": item.execution_rule_digest,
        "status": item.status,
        "attempt_count": item.attempt_count,
        "result_summary": item.result_summary,
        "evidence": item.evidence,
        "error_code": item.error_code,
        "trace_id": item.trace_id,
        "duration_ms": item.duration_ms,
        "completed_at": item.completed_at,
    }


def decision_data(item: ReviewDecision) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "decision": item.decision,
        "score": item.score,
        "feedback": item.feedback,
        "decided_by": item.decided_by.public_id,
        "criterion_snapshot": item.criterion_snapshot,
        "trace_id": item.trace_id,
        "created_at": item.created_at,
    }


def review_detail_data(item: Review, *, include_source: bool = False) -> dict[str, Any]:
    decision = getattr(item, "decision", None)
    project = {}
    if include_source:
        from apps.workspaces.workbench import _content_data

        from .services import submitted_project_files

        snapshot = (
            item.report_version.workspace_snapshot if item.report_version_id
            else item.system_artifact.workspace_snapshot
        )
        files = []
        remaining = 1024 * 1024
        error_code = ""
        try:
            for path, value in sorted(submitted_project_files(item).items()):
                text = value.decode("utf-8")
                files.append({"path": path, "content": text[:remaining],
                              "truncated": len(text) > remaining})
                remaining = max(0, remaining - len(text))
        except Exception:  # noqa: BLE001 - manual grading survives unavailable source storage
            error_code = "SUBMITTED_PROJECT_UNAVAILABLE"
        project = {"project": {
            "snapshot_id": snapshot.public_id, "digest_sha256": snapshot.digest_sha256,
            "language": snapshot.language, "files": files, "error_code": error_code,
            "guidance": _content_data(item.task),
        }}
    return {
        **review_list_data(item),
        **project,
        "rubric_version_id": item.rubric_version.public_id,
        "scores": criterion_scores_data(item),
        "annotations": [annotation_data(value) for value in item.annotations.all()],
        "auto_checks": [auto_check_data(value) for value in item.auto_check_runs.all()],
        "similarity_runs": [similarity_run_data(value) for value in item.similarity_runs.all()],
        "decision": decision_data(decision) if decision else None,
        "submission": (
            {"kind": "REPORT", "version": report_version_data(item.report_version)}
            if item.report_version_id
            else {"kind": "SYSTEM_ARTIFACT", "artifact": system_artifact_data(item.system_artifact)}
        ),
    }


def review_result_data(values: list[Review]) -> dict[str, Any]:
    latest = values[0]
    rounds = []
    for item in values:
        decision = getattr(item, "decision", None)
        is_decided = decision is not None
        rounds.append({
            "review_id": item.public_id,
            "round_no": item.round_no,
            "status": item.status,
            # Teacher work in progress stays private until the decision is committed.
            "scores": criterion_scores_data(item) if is_decided else None,
            "annotations": [
                annotation_data(value, include_history=False)
                for value in item.annotations.all()
                if is_decided and value.status == ReviewAnnotation.Status.ACTIVE
            ],
            "decision": decision_data(decision) if decision else None,
        })
    allowed_actions = []
    if latest.task.status in {"REPORT_DRAFT", "IN_PROGRESS"}:
        latest_decision = getattr(latest, "decision", None)
        if latest_decision and latest_decision.decision == ReviewDecision.Decision.REJECT:
            allowed_actions.append("REVISE_AND_RESUBMIT")
    return {
        "task_id": latest.task.public_id,
        "task_status": latest.task.status,
        "rounds": rounds,
        "allowed_actions": allowed_actions,
    }


def similarity_run_data(item: SimilarityRun) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "review_id": item.review.public_id,
        "algorithm_version": item.algorithm_version,
        "candidate_scope": item.candidate_scope,
        "input_digest": item.input_digest,
        "threshold": item.threshold,
        "candidate_count": item.candidate_count,
        "status": item.status,
        "error_code": item.error_code,
        "trace_id": item.trace_id,
        "retention_until": item.retention_until,
        "row_version": item.row_version,
    }


def similarity_match_data(item: SimilarityMatch) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "candidate_report_version_id": item.candidate_report_version.public_id,
        "candidate_task_id": item.candidate_report_version.task.public_id,
        "candidate_student_id": item.candidate_report_version.task.student.public_id,
        "candidate_student_name": item.candidate_report_version.task.student.display_name,
        "score": item.score,
        "evidence": [] if item.evidence_purged_at else item.evidence,
        "evidence_purged_at": item.evidence_purged_at,
        "retention_until": item.retention_until,
    }

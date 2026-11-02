from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import AppendOnlyModel, ObjectAsset, VersionedModel
from apps.courses.models import Course, CourseStaff


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class Rubric(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="rubrics")
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="owned_rubrics")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    current_version = models.ForeignKey(
        "RubricVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_for_rubrics",
    )

    class Meta:
        db_table = "reviews_rubric"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "name"), name="reviews_rubric_course_name_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "PUBLISHED")),
                name="reviews_rubric_status_ck",
            ),
        ]
        indexes = [models.Index(fields=("course", "status"), name="reviews_rubric_course_idx")]


class RubricVersion(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"

    public_id = public_id_field()
    rubric = models.ForeignKey(Rubric, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveIntegerField()
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default="")
    total_score = models.DecimalField(max_digits=9, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_rubric_versions"
    )
    published_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_rubric_versions",
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reviews_rubric_version"
        constraints = [
            models.UniqueConstraint(
                fields=("rubric", "version_no"), name="reviews_rubric_ver_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(total_score__gt=0), name="reviews_rubric_total_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "PUBLISHED")),
                name="reviews_rubric_ver_status_ck",
            ),
        ]
        indexes = [models.Index(fields=("rubric", "status"), name="reviews_rubric_ver_idx")]


class RubricCriterion(VersionedModel):
    public_id = public_id_field()
    rubric_version = models.ForeignKey(
        RubricVersion, on_delete=models.PROTECT, related_name="criteria"
    )
    position = models.PositiveIntegerField()
    position_key = models.CharField(max_length=64, default="")
    is_active = models.BooleanField(default=True)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default="")
    guidance = models.TextField(blank=True, default="")
    max_score = models.DecimalField(max_digits=9, decimal_places=2)
    weight_basis_points = models.PositiveIntegerField()

    class Meta:
        db_table = "reviews_rubric_criterion"
        constraints = [
            models.UniqueConstraint(
                fields=("rubric_version", "position_key"),
                name="reviews_criterion_position_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1), name="reviews_criterion_position_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(max_score__gt=0), name="reviews_criterion_score_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(weight_basis_points__gte=1)
                & models.Q(weight_basis_points__lte=10000),
                name="reviews_criterion_weight_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("rubric_version", "position"), name="reviews_criterion_order_idx")
        ]


class Review(VersionedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        IN_REVIEW = "IN_REVIEW"
        DECIDED = "DECIDED"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="reviews")
    task = models.ForeignKey(
        "experiments.ExperimentTask", on_delete=models.PROTECT, related_name="reviews"
    )
    round_no = models.PositiveIntegerField()
    rubric_version = models.ForeignKey(
        RubricVersion, on_delete=models.PROTECT, related_name="reviews"
    )
    report_version = models.ForeignKey(
        "reports.ReportVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviews",
    )
    system_artifact = models.ForeignKey(
        "reports.SystemArtifact",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviews",
    )
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_reviews",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    class Meta:
        db_table = "reviews_review"
        constraints = [
            models.UniqueConstraint(
                fields=("task", "round_no"), name="reviews_review_task_round_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(round_no__gte=1), name="reviews_review_round_ck"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(report_version__isnull=False, system_artifact__isnull=True)
                    | models.Q(report_version__isnull=True, system_artifact__isnull=False)
                ),
                name="reviews_review_target_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("PENDING", "IN_REVIEW", "DECIDED")),
                name="reviews_review_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("course", "status", "created_at"), name="reviews_queue_idx"),
            models.Index(fields=("task", "created_at"), name="reviews_review_task_idx"),
        ]


class CriterionScore(VersionedModel):
    public_id = public_id_field()
    review = models.ForeignKey(Review, on_delete=models.PROTECT, related_name="criterion_scores")
    criterion = models.ForeignKey(
        RubricCriterion, on_delete=models.PROTECT, related_name="review_scores"
    )
    score = models.DecimalField(max_digits=9, decimal_places=2)
    note = models.TextField(blank=True, default="")
    revision_no = models.PositiveIntegerField(default=1)
    updated_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="updated_review_scores"
    )

    class Meta:
        db_table = "reviews_criterion_score"
        constraints = [
            models.UniqueConstraint(
                fields=("review", "criterion"), name="reviews_score_review_crit_uniq"
            ),
            models.CheckConstraint(condition=models.Q(score__gte=0), name="reviews_score_min_ck"),
            models.CheckConstraint(
                condition=models.Q(revision_no__gte=1), name="reviews_score_revision_ck"
            ),
        ]
        indexes = [models.Index(fields=("review", "created_at"), name="reviews_score_idx")]


class CriterionScoreEvent(AppendOnlyModel):
    public_id = public_id_field()
    score_projection = models.ForeignKey(
        CriterionScore, on_delete=models.PROTECT, related_name="events"
    )
    review = models.ForeignKey(Review, on_delete=models.PROTECT, related_name="score_events")
    criterion = models.ForeignKey(
        RubricCriterion, on_delete=models.PROTECT, related_name="score_events"
    )
    revision_no = models.PositiveIntegerField()
    score = models.DecimalField(max_digits=9, decimal_places=2)
    note = models.TextField(blank=True, default="")
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="review_score_events")
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "reviews_criterion_score_event"
        constraints = [
            models.UniqueConstraint(
                fields=("score_projection", "revision_no"),
                name="reviews_score_event_revision_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=("review", "created_at"), name="reviews_score_event_idx")
        ]


class ReviewDecision(AppendOnlyModel):
    class Decision(models.TextChoices):
        APPROVE = "APPROVE"
        REJECT = "REJECT"

    public_id = public_id_field()
    review = models.OneToOneField(Review, on_delete=models.PROTECT, related_name="decision")
    decision = models.CharField(max_length=8, choices=Decision.choices)
    score = models.DecimalField(max_digits=9, decimal_places=2)
    feedback = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="review_decisions"
    )
    decided_by_staff = models.ForeignKey(
        CourseStaff, on_delete=models.PROTECT, related_name="review_decisions"
    )
    actor_portal = models.CharField(max_length=16, default="TEACHING")
    criterion_snapshot = models.JSONField(default=list)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "reviews_review_decision"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(decision__in=("APPROVE", "REJECT")),
                name="reviews_decision_value_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(actor_portal="TEACHING"),
                name="reviews_decision_portal_ck",
            ),
            models.CheckConstraint(condition=models.Q(score__gte=0), name="reviews_dec_score_ck"),
        ]
        indexes = [
            models.Index(fields=("decided_by", "created_at"), name="reviews_decision_actor_idx")
        ]


class ReviewAnnotation(VersionedModel):
    class TargetType(models.TextChoices):
        REPORT_TEXT = "REPORT_TEXT"
        ATTACHMENT = "ATTACHMENT"
        WORKSPACE_SNAPSHOT = "WORKSPACE_SNAPSHOT"
        SYSTEM_ARTIFACT = "SYSTEM_ARTIFACT"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        REVOKED = "REVOKED"

    public_id = public_id_field()
    review = models.ForeignKey(Review, on_delete=models.PROTECT, related_name="annotations")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="review_annotations")
    target_type = models.CharField(max_length=32, choices=TargetType.choices)
    report_version = models.ForeignKey(
        "reports.ReportVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="review_annotations",
    )
    asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="review_annotations",
    )
    object_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    anchor = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    current_revision_no = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "reviews_review_annotation"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        target_type="REPORT_TEXT",
                        report_version__isnull=False,
                        asset__isnull=True,
                    )
                    | models.Q(
                        target_type__in=(
                            "ATTACHMENT",
                            "WORKSPACE_SNAPSHOT",
                            "SYSTEM_ARTIFACT",
                        ),
                        report_version__isnull=True,
                        asset__isnull=False,
                    )
                ),
                name="reviews_annotation_target_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "REVOKED")),
                name="reviews_annotation_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("review", "status", "created_at"), name="reviews_annotation_idx")
        ]


class AnnotationRevision(AppendOnlyModel):
    class Action(models.TextChoices):
        UPSERT = "UPSERT"
        REVOKE = "REVOKE"

    public_id = public_id_field()
    annotation = models.ForeignKey(
        ReviewAnnotation, on_delete=models.PROTECT, related_name="revisions"
    )
    revision_no = models.PositiveIntegerField()
    action = models.CharField(max_length=16, choices=Action.choices)
    body = models.TextField(blank=True, default="")
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="annotation_revisions")
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "reviews_annotation_revision"
        constraints = [
            models.UniqueConstraint(
                fields=("annotation", "revision_no"), name="reviews_annotation_revision_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=("UPSERT", "REVOKE")),
                name="reviews_annotation_action_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("annotation", "created_at"), name="reviews_annotation_rev_idx")
        ]


class AutoCheckRun(VersionedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        PASSED = "PASSED"
        FAILED = "FAILED"
        TIMEOUT = "TIMEOUT"
        RESOURCE_EXCEEDED = "RESOURCE_EXCEEDED"
        REJECTED = "REJECTED"

    public_id = public_id_field()
    review = models.ForeignKey(Review, on_delete=models.PROTECT, related_name="auto_check_runs")
    rule = models.ForeignKey(
        "labtemplates.AutoCheckRule", on_delete=models.PROTECT, related_name="review_runs"
    )
    input_asset = models.ForeignKey(
        ObjectAsset, on_delete=models.PROTECT, related_name="auto_check_runs"
    )
    checker_type = models.CharField(max_length=64)
    rule_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    artifact_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    # The task execution contract is copied when the review is created.  A
    # later template edit therefore cannot change what a judge is allowed to
    # run for this review.
    execution_rule_summary = models.JSONField(default=dict)
    execution_rule_digest = models.CharField(
        max_length=64, blank=True, default="", db_collation="ascii_bin"
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED)
    attempt_count = models.PositiveIntegerField(default=0)
    result_summary = models.JSONField(default=dict)
    evidence = models.JSONField(default=list)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_detail_masked = models.JSONField(default=dict)
    trace_id = models.CharField(max_length=32)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "reviews_auto_check_run"
        constraints = [
            models.UniqueConstraint(
                fields=("review", "rule", "artifact_digest"),
                name="reviews_auto_run_input_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "QUEUED",
                        "RUNNING",
                        "PASSED",
                        "FAILED",
                        "TIMEOUT",
                        "RESOURCE_EXCEEDED",
                        "REJECTED",
                    )
                ),
                name="reviews_auto_run_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_ms__isnull=True) | models.Q(duration_ms__gte=0),
                name="reviews_auto_run_duration_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "created_at"), name="reviews_auto_run_status_idx"),
            models.Index(fields=("review", "created_at"), name="reviews_auto_run_review_idx"),
        ]


class SimilarityRun(VersionedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="similarity_runs")
    review = models.ForeignKey(Review, on_delete=models.PROTECT, related_name="similarity_runs")
    target_report_version = models.ForeignKey(
        "reports.ReportVersion", on_delete=models.PROTECT, related_name="target_similarity_runs"
    )
    algorithm_version = models.CharField(max_length=64)
    candidate_scope = models.CharField(max_length=32, default="SAME_PUBLICATION")
    candidate_snapshot = models.JSONField(default=list)
    input_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    threshold = models.DecimalField(max_digits=5, decimal_places=4)
    candidate_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_detail_masked = models.JSONField(default=dict)
    trace_id = models.CharField(max_length=32)
    retention_until = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reviews_similarity_run"
        constraints = [
            models.UniqueConstraint(
                fields=("review", "algorithm_version", "input_digest"),
                name="reviews_similarity_input_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(threshold__gte=0) & models.Q(threshold__lte=1),
                name="reviews_similarity_threshold_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("QUEUED", "RUNNING", "COMPLETED", "FAILED")),
                name="reviews_similarity_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("course", "status", "created_at"), name="reviews_sim_course_idx"),
            models.Index(fields=("retention_until",), name="reviews_sim_retention_idx"),
        ]


class SimilarityMatch(VersionedModel):
    public_id = public_id_field()
    run = models.ForeignKey(SimilarityRun, on_delete=models.PROTECT, related_name="matches")
    candidate_report_version = models.ForeignKey(
        "reports.ReportVersion", on_delete=models.PROTECT, related_name="similarity_matches"
    )
    score = models.DecimalField(max_digits=5, decimal_places=4)
    evidence = models.JSONField(default=list)
    evidence_purged_at = models.DateTimeField(null=True, blank=True)
    retention_until = models.DateTimeField()

    class Meta:
        db_table = "reviews_similarity_match"
        constraints = [
            models.UniqueConstraint(
                fields=("run", "candidate_report_version"),
                name="reviews_similarity_match_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(score__gte=0) & models.Q(score__lte=1),
                name="reviews_similarity_score_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("run", "score"), name="reviews_similarity_match_idx"),
            models.Index(fields=("retention_until",), name="reviews_match_retention_idx"),
        ]

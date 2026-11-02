from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import VersionedModel
from apps.courses.models import Course
from apps.experiments.models import ExperimentTask


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class ProjectionModel(VersionedModel):
    projection_version = models.CharField(max_length=64)
    source_cursor = models.CharField(max_length=128, blank=True, default="")
    calculated_at = models.DateTimeField()

    class Meta:
        abstract = True


class CourseDaily(ProjectionModel):
    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="analytics_daily")
    period_start = models.DateField()
    metrics = models.JSONField(default=dict)

    class Meta:
        db_table = "analytics_course_daily"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "period_start", "projection_version"),
                name="analytics_course_daily_uniq",
            )
        ]
        indexes = [
            models.Index(fields=("course", "period_start"), name="analytics_course_daily_idx")
        ]


class StudentRiskSignal(ProjectionModel):
    class Status(models.TextChoices):
        OPEN = "OPEN"
        ACKNOWLEDGED = "ACKNOWLEDGED"
        IGNORED = "IGNORED"
        CLOSED = "CLOSED"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="risk_signals")
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="risk_signals")
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, null=True, blank=True, related_name="risk_signals"
    )
    kind = models.CharField(max_length=64)
    severity = models.CharField(max_length=16, default="MEDIUM")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    explanation_masked = models.TextField()
    evidence = models.JSONField(default=dict)
    source_refs = models.JSONField(default=list)
    rule_version = models.CharField(max_length=64, blank=True, default="")
    model_version = models.CharField(max_length=64, blank=True, default="")
    source_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    valid_until = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="resolved_risk_signals"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "analytics_student_risk_signal"
        constraints = [
            models.UniqueConstraint(
                fields=("student", "kind", "source_digest"), name="analytics_risk_source_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("OPEN", "ACKNOWLEDGED", "IGNORED", "CLOSED")),
                name="analytics_risk_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("course", "status", "severity"), name="analytics_risk_course_idx"),
            models.Index(fields=("student", "status"), name="analytics_risk_student_idx"),
        ]


class CourseQualitySnapshot(ProjectionModel):
    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="quality_snapshots")
    period_start = models.DateField()
    quality_score = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    metrics = models.JSONField(default=dict)

    class Meta:
        db_table = "analytics_course_quality_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "period_start", "projection_version"),
                name="analytics_quality_snapshot_uniq",
            )
        ]
        indexes = [
            models.Index(fields=("course", "period_start"), name="analytics_quality_course_idx")
        ]


class LearningRecommendation(ProjectionModel):
    public_id = public_id_field()
    student = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="learning_recommendations"
    )
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="learning_recommendations"
    )
    task = models.ForeignKey(
        ExperimentTask,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="learning_recommendations",
    )
    kind = models.CharField(max_length=64)
    title = models.CharField(max_length=180)
    explanation_masked = models.TextField()
    evidence = models.JSONField(default=dict)
    source_refs = models.JSONField(default=list)
    rule_version = models.CharField(max_length=64, blank=True, default="")
    model_version = models.CharField(max_length=64, blank=True, default="")
    source_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    valid_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "analytics_learning_recommendation"
        constraints = [
            models.UniqueConstraint(
                fields=("student", "kind", "source_digest"), name="analytics_reco_source_uniq"
            )
        ]
        indexes = [
            models.Index(
                fields=("student", "course", "valid_until"), name="analytics_reco_scope_idx"
            )
        ]


class ResourceCostDaily(ProjectionModel):
    public_id = public_id_field()
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, null=True, blank=True, related_name="resource_costs"
    )
    period_start = models.DateField()
    resource_type = models.CharField(max_length=64)
    amount_minor = models.PositiveBigIntegerField(default=0)
    units = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    metadata = models.JSONField(default=dict)

    class Meta:
        db_table = "analytics_resource_cost_daily"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "period_start", "resource_type", "projection_version"),
                name="analytics_resource_cost_uniq",
            )
        ]
        indexes = [
            models.Index(fields=("course", "period_start"), name="analytics_cost_course_idx"),
            models.Index(fields=("resource_type", "period_start"), name="analytics_cost_type_idx"),
        ]

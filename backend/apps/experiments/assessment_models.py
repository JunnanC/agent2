"""Assessment records owned by experiments, registered from its models module."""

from django.db import models

from apps.core.models import AppendOnlyModel, VersionedModel


class AnswerDraft(VersionedModel):
    task = models.ForeignKey("experiments.ExperimentTask", on_delete=models.PROTECT)
    question = models.ForeignKey("experiments.PublicationTask", on_delete=models.PROTECT)
    selected_option_ids = models.JSONField(default=list)
    selected_language = models.CharField(max_length=16, blank=True, default="")

    class Meta:
        db_table = "experiments_answer_draft"
        constraints = [models.UniqueConstraint(
            fields=("task", "question"), name="assessment_answer_draft_uniq",
        )]


class CodeDraft(VersionedModel):
    task = models.ForeignKey("experiments.ExperimentTask", on_delete=models.PROTECT)
    question = models.ForeignKey("experiments.PublicationTask", on_delete=models.PROTECT)
    language = models.CharField(max_length=16)
    files = models.JSONField(default=dict)

    class Meta:
        db_table = "experiments_code_draft"
        constraints = [models.UniqueConstraint(
            fields=("task", "question", "language"), name="assessment_code_draft_uniq",
        )]


class AssessmentSection(VersionedModel):
    class Kind(models.TextChoices):
        CHOICE = "CHOICE"
        PROGRAMMING = "PROGRAMMING"

    class Status(models.TextChoices):
        NOT_SUBMITTED = "NOT_SUBMITTED"
        SUBMITTED = "SUBMITTED"
        RETURNED = "RETURNED"

    task = models.ForeignKey("experiments.ExperimentTask", on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NOT_SUBMITTED)
    current_submission = models.ForeignKey(
        "experiments.SectionSubmission", on_delete=models.PROTECT, null=True, blank=True,
        related_name="current_for_sections",
    )
    resubmit_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "experiments_assessment_section"
        constraints = [
            models.UniqueConstraint(fields=("task", "kind"), name="assessment_section_uniq"),
            models.CheckConstraint(
                condition=models.Q(kind__in=("CHOICE", "PROGRAMMING")),
                name="assessment_section_kind_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("NOT_SUBMITTED", "SUBMITTED", "RETURNED")),
                name="assessment_section_status_ck",
            ),
        ]


class SectionSubmission(AppendOnlyModel):
    section = models.ForeignKey(AssessmentSection, on_delete=models.PROTECT)
    version_no = models.PositiveIntegerField()
    publication_digest = models.CharField(max_length=64)
    report_version = models.ForeignKey(
        "reports.ReportVersion", on_delete=models.PROTECT, null=True, blank=True,
        related_name="section_submissions",
    )
    submitted_at = models.DateTimeField()
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "experiments_section_submission"
        constraints = [
            models.UniqueConstraint(
                fields=("section", "version_no"), name="assessment_submission_version_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gte=1), name="assessment_submission_version_ck",
            ),
        ]


class QuestionSubmission(AppendOnlyModel):
    submission = models.ForeignKey(
        SectionSubmission, on_delete=models.PROTECT, related_name="answers",
    )
    question = models.ForeignKey("experiments.PublicationTask", on_delete=models.PROTECT)
    selected_option_ids = models.JSONField(default=list)
    language = models.CharField(max_length=16, blank=True, default="")
    code_snapshot = models.ForeignKey(
        "workspaces.WorkspaceSnapshot", on_delete=models.PROTECT, null=True, blank=True,
        related_name="question_submissions",
    )

    class Meta:
        db_table = "experiments_question_submission"
        constraints = [models.UniqueConstraint(
            fields=("submission", "question"), name="assessment_submission_question_uniq",
        )]


class QuestionGrade(VersionedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        RUNNING = "RUNNING"
        RETRY = "RETRY"
        COMPLETED = "COMPLETED"

    answer = models.OneToOneField(
        QuestionSubmission, on_delete=models.PROTECT, related_name="grade",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    private_result = models.JSONField(default=dict)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "experiments_question_grade"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(score__isnull=True) | models.Q(score__gte=0),
                name="assessment_grade_score_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("PENDING", "RUNNING", "RETRY", "COMPLETED")),
                name="assessment_grade_status_ck",
            ),
        ]


class AssessmentRun(VersionedModel):
    task = models.ForeignKey("experiments.ExperimentTask", on_delete=models.PROTECT)
    question = models.ForeignKey("experiments.PublicationTask", on_delete=models.PROTECT)
    snapshot = models.ForeignKey("workspaces.WorkspaceSnapshot", on_delete=models.PROTECT)
    stdin = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, default="PENDING")
    stdout = models.TextField(blank=True, default="")
    stderr = models.TextField(blank=True, default="")
    result_status = models.CharField(max_length=32, blank=True, default="")
    lease_token = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "experiments_assessment_run"
        constraints = [models.CheckConstraint(
            condition=models.Q(status__in=("PENDING", "RUNNING", "RETRY", "COMPLETED")),
            name="assessment_run_status_ck",
        )]


class ReportGrade(VersionedModel):
    submission = models.OneToOneField(
        SectionSubmission, on_delete=models.PROTECT, related_name="report_grade",
    )
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    criterion_scores = models.JSONField(default=dict)
    feedback = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "experiments_report_grade"
        constraints = [models.CheckConstraint(
            condition=models.Q(score__isnull=True) | models.Q(score__gte=0),
            name="assessment_report_score_ck",
        )]

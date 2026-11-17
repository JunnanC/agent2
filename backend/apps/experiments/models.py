from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import AppendOnlyModel, VersionedModel
from apps.courses.models import Chapter, Course, Enrollment
from apps.governance.models import ImageAsset, ResourceProfile, RuntimeAdapter
from apps.labtemplates.models import TemplateVersion
from apps.reviews.models import RubricVersion

from .assessment_models import (  # noqa: F401 - register assessment models with Django
    AnswerDraft,
    AssessmentRun,
    AssessmentSection,
    CodeDraft,
    QuestionGrade,
    QuestionSubmission,
    ReportGrade,
    SectionSubmission,
)

TASK_STATUS_VALUES = (
    "ASSIGNED",
    "IN_PROGRESS",
    "REPORT_DRAFT",
    "UNDER_REVIEW",
    "APPROVED",
    "ARCHIVING",
    "COMPLETED",
    "CANCELLED",
    "EXPIRED",
    "FAILED",
)
EXTENSION_STATUS_VALUES = ("PENDING", "APPROVED", "REJECTED", "CANCELLED")


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class TaskPublication(VersionedModel):
    class AudienceMode(models.TextChoices):
        ALL_ACTIVE = "ALL_ACTIVE"
        SELECTED = "SELECTED"

    class LateEnrollmentPolicy(models.TextChoices):
        ASSIGN_UNTIL_DEADLINE = "ASSIGN_UNTIL_DEADLINE"
        DO_NOT_ASSIGN = "DO_NOT_ASSIGN"

    class ReviewMode(models.TextChoices):
        MANUAL = "MANUAL"
        MANUAL_WITH_AUTO_CHECK = "MANUAL_WITH_AUTO_CHECK"

    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHING = "PUBLISHING"
        PUBLISHED = "PUBLISHED"
        PUBLISH_FAILED = "PUBLISH_FAILED"
        CLOSED = "CLOSED"
        WITHDRAWN = "WITHDRAWN"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="task_publications")
    course_chapter = models.ForeignKey(
        "courses.Chapter",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="experiments",
    )
    retake_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="retake_publications",
    )
    template_version = models.ForeignKey(
        TemplateVersion, on_delete=models.PROTECT, related_name="task_publications"
    )
    # These fields are populated at publish time.  They deliberately duplicate
    # the template's runtime inputs so later governance/template edits cannot
    # change an already published task.
    template_spec_digest = models.CharField(
        max_length=64, null=True, blank=True, db_collation="ascii_bin"
    )
    template_digest = models.CharField(
        max_length=64, null=True, blank=True, db_collation="ascii_bin"
    )
    publication_digest = models.CharField(
        max_length=64, null=True, blank=True, db_collation="ascii_bin"
    )
    runtime_adapter = models.ForeignKey(
        RuntimeAdapter,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="experiment_task_publication_snapshots",
    )
    runtime_adapter_driver = models.CharField(max_length=32, blank=True, default="")
    runtime_adapter_config_ref = models.CharField(max_length=128, blank=True, default="")
    image = models.ForeignKey(
        ImageAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="experiment_task_publication_snapshots",
    )
    image_registry = models.CharField(max_length=255, blank=True, default="")
    image_repository = models.CharField(max_length=255, blank=True, default="")
    image_digest = models.CharField(max_length=71, blank=True, default="", db_collation="ascii_bin")
    resource_profile = models.ForeignKey(
        ResourceProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="experiment_task_publication_snapshots",
    )
    resource_profile_snapshot = models.JSONField(default=dict, blank=True)
    rubric_version = models.ForeignKey(
        RubricVersion,
        on_delete=models.PROTECT,
        related_name="task_publications",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default="")
    audience_mode = models.CharField(max_length=16, choices=AudienceMode.choices)
    late_enrollment_policy = models.CharField(
        max_length=32,
        choices=LateEnrollmentPolicy.choices,
        default=LateEnrollmentPolicy.ASSIGN_UNTIL_DEADLINE,
    )
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    score_release_at = models.DateTimeField(null=True, blank=True)
    assignment_deadline = models.DateTimeField(null=True, blank=True)
    report_required = models.BooleanField(default=True)
    review_mode = models.CharField(max_length=32, choices=ReviewMode.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    published_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="published_experiments"
    )
    published_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="closed_experiments"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="withdrawn_experiments",
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    publication_error = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "experiments_task_publication"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "DRAFT",
                        "PUBLISHING",
                        "PUBLISHED",
                        "PUBLISH_FAILED",
                        "CLOSED",
                        "WITHDRAWN",
                    )
                ),
                name="experiments_pub_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(window_end__gt=models.F("window_start")),
                name="experiments_pub_window_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(assignment_deadline__isnull=True)
                | models.Q(assignment_deadline__lte=models.F("window_end")),
                name="experiments_pub_deadline_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("course", "status", "window_end"), name="experiments_pub_course_idx"
            ),
            models.Index(
                fields=("template_version", "status"), name="experiments_pub_template_idx"
            ),
        ]


class PublicationChapter(AppendOnlyModel):
    """Immutable ordered chapter content captured when a publication is made."""

    public_id = public_id_field()
    publication = models.ForeignKey(
        TaskPublication, on_delete=models.PROTECT, related_name="chapter_snapshots"
    )
    source_chapter_id = models.CharField(max_length=26, db_collation="ascii_bin")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    learning_objectives = models.JSONField(default=list, blank=True)
    sort_order = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "experiments_publication_chapter"
        constraints = [
            models.UniqueConstraint(
                fields=("publication", "source_chapter_id"),
                name="experiments_pub_chapter_source_uniq",
            ),
            models.UniqueConstraint(
                fields=("publication", "sort_order"),
                name="experiments_pub_chapter_order_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(sort_order__gte=1),
                name="experiments_pub_chapter_order_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("publication", "sort_order"),
                name="exp_pub_chapter_order_idx",
            )
        ]


class PublicationTask(AppendOnlyModel):
    """Immutable ordered task content and runtime inputs captured at publish time."""

    public_id = public_id_field()
    publication_chapter = models.ForeignKey(
        PublicationChapter, on_delete=models.PROTECT, related_name="task_snapshots"
    )
    source_task_id = models.CharField(max_length=26, db_collation="ascii_bin")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    instructions = models.TextField(blank=True, default="")
    task_type = models.CharField(max_length=64)
    sort_order = models.PositiveIntegerField()
    image_digest = models.CharField(max_length=71, db_collation="ascii_bin")
    resource_profile_snapshot = models.JSONField(default=dict, blank=True)
    execution_snapshot = models.JSONField(default=dict, blank=True)
    submission_policy = models.JSONField(default=dict, blank=True)
    grading_policy = models.JSONField(default=dict, blank=True)
    question_spec = models.JSONField(default=dict, blank=True)
    marking_spec = models.JSONField(default=dict, blank=True)
    max_score = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    class Meta:
        db_table = "experiments_publication_task"
        constraints = [
            models.UniqueConstraint(
                fields=("publication_chapter", "source_task_id"),
                name="experiments_pub_task_source_uniq",
            ),
            models.UniqueConstraint(
                fields=("publication_chapter", "sort_order"),
                name="experiments_pub_task_order_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(sort_order__gte=1),
                name="experiments_pub_task_order_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("publication_chapter", "sort_order"),
                name="experiments_pub_task_order_idx",
            )
        ]


class PublicationAudience(AppendOnlyModel):
    class Kind(models.TextChoices):
        ALL_ACTIVE = "ALL_ACTIVE"
        SELECTED = "SELECTED"

    public_id = public_id_field()
    publication = models.ForeignKey(
        TaskPublication, on_delete=models.PROTECT, related_name="audience"
    )
    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="publication_audience",
    )
    audience_kind = models.CharField(max_length=16, choices=Kind.choices)
    snapshot_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    snapshot_enrollment_ids = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "experiments_publication_audience"
        constraints = [
            models.UniqueConstraint(
                fields=("publication", "enrollment"), name="experiments_audience_pub_enroll_uniq"
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(audience_kind="ALL_ACTIVE") & models.Q(enrollment__isnull=True))
                    | (models.Q(audience_kind="SELECTED") & models.Q(enrollment__isnull=False))
                ),
                name="experiments_audience_shape_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("publication", "created_at"), name="experiments_audience_pub_idx")
        ]


class PublicationPrerequisite(AppendOnlyModel):
    class Kind(models.TextChoices):
        CHAPTER = "CHAPTER"
        PUBLICATION = "PUBLICATION"

    public_id = public_id_field()
    publication = models.ForeignKey(
        TaskPublication, on_delete=models.PROTECT, related_name="prerequisites"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    chapter = models.ForeignKey(
        Chapter,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="experiment_prerequisites",
    )
    prerequisite_publication = models.ForeignKey(
        TaskPublication,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="required_by_publications",
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "experiments_publication_prerequisite"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(kind="CHAPTER")
                        & models.Q(chapter__isnull=False)
                        & models.Q(prerequisite_publication__isnull=True)
                    )
                    | (
                        models.Q(kind="PUBLICATION")
                        & models.Q(chapter__isnull=True)
                        & models.Q(prerequisite_publication__isnull=False)
                    )
                ),
                name="experiments_prereq_shape_ck",
            ),
            models.UniqueConstraint(
                fields=("publication", "chapter"), name="experiments_prereq_chapter_uniq"
            ),
            models.UniqueConstraint(
                fields=("publication", "prerequisite_publication"),
                name="experiments_prereq_pub_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=("publication", "created_at"), name="experiments_prereq_pub_idx")
        ]


class ExperimentTask(VersionedModel):
    class Status(models.TextChoices):
        ASSIGNED = "ASSIGNED"
        IN_PROGRESS = "IN_PROGRESS"
        REPORT_DRAFT = "REPORT_DRAFT"
        UNDER_REVIEW = "UNDER_REVIEW"
        APPROVED = "APPROVED"
        ARCHIVING = "ARCHIVING"
        COMPLETED = "COMPLETED"
        CANCELLED = "CANCELLED"
        EXPIRED = "EXPIRED"
        FAILED = "FAILED"

    class TerminalTarget(models.TextChoices):
        COMPLETED = "COMPLETED"
        CANCELLED = "CANCELLED"
        EXPIRED = "EXPIRED"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="experiment_tasks")
    publication = models.ForeignKey(TaskPublication, on_delete=models.PROTECT, related_name="tasks")
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.PROTECT, related_name="experiment_tasks"
    )
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="experiment_tasks")
    template_version = models.ForeignKey(
        TemplateVersion, on_delete=models.PROTECT, related_name="experiment_tasks"
    )
    runtime_type = models.CharField(max_length=16)
    template_spec_digest = models.CharField(
        max_length=64, null=True, blank=True, db_collation="ascii_bin"
    )
    runtime_adapter = models.ForeignKey(
        RuntimeAdapter,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="experiment_task_runtime_snapshots",
    )
    runtime_adapter_driver = models.CharField(max_length=32, blank=True, default="")
    runtime_adapter_config_ref = models.CharField(max_length=128, blank=True, default="")
    image = models.ForeignKey(
        ImageAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="experiment_task_runtime_snapshots",
    )
    image_registry = models.CharField(max_length=255, blank=True, default="")
    image_repository = models.CharField(max_length=255, blank=True, default="")
    image_digest = models.CharField(max_length=71, blank=True, default="", db_collation="ascii_bin")
    resource_profile = models.ForeignKey(
        ResourceProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="experiment_task_runtime_snapshots",
    )
    resource_profile_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ASSIGNED)
    terminal_target = models.CharField(
        max_length=16, choices=TerminalTarget.choices, null=True, blank=True
    )
    progress = models.PositiveSmallIntegerField(default=0)
    effective_deadline = models.DateTimeField(null=True, blank=True)
    current_failure = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    entered_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "experiments_experiment_task"
        constraints = [
            models.UniqueConstraint(
                fields=("publication", "student"), name="experiments_task_pub_student_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(progress__gte=0) & models.Q(progress__lte=100),
                name="experiments_task_progress_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=TASK_STATUS_VALUES), name="experiments_task_status_ck"
            ),
        ]
        indexes = [
            models.Index(
                fields=("student", "status", "runtime_type", "created_at"),
                name="experiments_task_student_idx",
            ),
            models.Index(
                fields=("course", "status", "updated_at"), name="experiments_task_course_idx"
            ),
            models.Index(fields=("publication", "status"), name="experiments_task_pub_idx"),
            models.Index(fields=("status", "updated_at"), name="experiments_task_status_idx"),
        ]


class ExperimentRetakeLink(VersionedModel):
    public_id = public_id_field()
    source_task = models.OneToOneField(
        ExperimentTask, on_delete=models.PROTECT, related_name="retake_link"
    )
    retake_publication = models.ForeignKey(
        TaskPublication, on_delete=models.PROTECT, related_name="retake_links"
    )
    retake_task = models.OneToOneField(
        ExperimentTask,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_retake_link",
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    registered_score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "experiments_experiment_retake_link"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(registered_score__isnull=True)
                | (models.Q(registered_score__gte=0) & models.Q(registered_score__lte=60)),
                name="experiments_retake_score_ck",
            )
        ]
        indexes = [
            models.Index(
                fields=("retake_publication", "created_at"),
                name="experiments_retake_pub_idx",
            )
        ]


class TaskStateTransition(AppendOnlyModel):
    public_id = public_id_field()
    task = models.ForeignKey(ExperimentTask, on_delete=models.PROTECT, related_name="transitions")
    from_status = models.CharField(max_length=20, blank=True, default="")
    to_status = models.CharField(max_length=20)
    trigger = models.CharField(max_length=64)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    detail_masked = models.JSONField(default=dict, blank=True)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "experiments_task_state_transition"
        indexes = [models.Index(fields=("task", "created_at"), name="experiments_trans_task_idx")]


class TaskExtensionRequest(VersionedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
        CANCELLED = "CANCELLED"

    public_id = public_id_field()
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="extension_requests"
    )
    requested_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="experiment_extension_requests"
    )
    original_deadline = models.DateTimeField()
    requested_deadline = models.DateTimeField()
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    effective_deadline = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "experiments_task_extension_request"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(requested_deadline__gt=models.F("original_deadline")),
                name="experiments_extension_time_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=EXTENSION_STATUS_VALUES),
                name="experiments_extension_status_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("task", "status", "created_at"), name="experiments_extension_task_idx"
            )
        ]


class TaskExtensionDecision(AppendOnlyModel):
    class Decision(models.TextChoices):
        APPROVE = "APPROVE"
        REJECT = "REJECT"

    public_id = public_id_field()
    request = models.ForeignKey(
        TaskExtensionRequest, on_delete=models.PROTECT, related_name="decisions"
    )
    actor = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="experiment_extension_decisions"
    )
    decision = models.CharField(max_length=8, choices=Decision.choices)
    effective_deadline = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "experiments_task_extension_decision"
        constraints = [
            models.UniqueConstraint(
                fields=("request",), name="experiments_extension_decision_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=("request", "created_at"), name="experiments_ext_decision_idx")
        ]

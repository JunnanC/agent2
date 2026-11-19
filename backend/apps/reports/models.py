from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import AppendOnlyModel, ObjectAsset, VersionedModel
from apps.experiments.models import ExperimentTask


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class ReportDraft(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        SUBMITTED = "SUBMITTED"

    public_id = public_id_field()
    task = models.OneToOneField(
        ExperimentTask, on_delete=models.PROTECT, related_name="report_draft"
    )
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="report_drafts")
    body_markdown = models.TextField(blank=True, default="")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reports_report_draft"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "SUBMITTED")),
                name="reports_draft_status_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("student", "status", "updated_at"), name="reports_draft_student_idx"
            ),
        ]


class ReportAttachment(AppendOnlyModel):
    public_id = public_id_field()
    draft = models.ForeignKey(ReportDraft, on_delete=models.PROTECT, related_name="attachments")
    asset = models.ForeignKey(ObjectAsset, on_delete=models.PROTECT, related_name="report_links")
    uploaded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="report_attachments"
    )
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "reports_report_attachment"
        constraints = [
            models.UniqueConstraint(
                fields=("draft", "asset"), name="reports_attachment_draft_asset_uniq"
            ),
            models.UniqueConstraint(fields=("asset",), name="reports_attachment_asset_uniq"),
        ]
        indexes = [
            models.Index(fields=("draft", "created_at"), name="reports_attachment_draft_idx")
        ]


class ReportVersion(AppendOnlyModel):
    public_id = public_id_field()
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="report_versions"
    )
    draft = models.ForeignKey(ReportDraft, on_delete=models.PROTECT, related_name="versions")
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="report_versions")
    version_no = models.PositiveIntegerField()
    body_markdown = models.TextField()
    body_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    snapshot_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    submitted_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="submitted_report_versions"
    )
    submitted_at = models.DateTimeField()
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "reports_report_version"
        constraints = [
            models.UniqueConstraint(
                fields=("task", "version_no"), name="reports_version_task_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gte=1), name="reports_version_no_ck"
            ),
        ]
        indexes = [models.Index(fields=("task", "created_at"), name="reports_version_task_idx")]


class ReportVersionAttachment(AppendOnlyModel):
    public_id = public_id_field()
    version = models.ForeignKey(ReportVersion, on_delete=models.PROTECT, related_name="attachments")
    attachment = models.ForeignKey(
        ReportAttachment, on_delete=models.PROTECT, related_name="version_links"
    )
    asset_digest = models.CharField(max_length=64, db_collation="ascii_bin")

    class Meta:
        db_table = "reports_report_version_attachment"
        constraints = [
            models.UniqueConstraint(
                fields=("version", "attachment"), name="reports_ver_attach_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=("version", "created_at"), name="reports_ver_attach_version_idx")
        ]


class ReportSubmission(VersionedModel):
    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED"
        RETURNED = "RETURNED"
        GRADED = "GRADED"

    task = models.OneToOneField(ExperimentTask, on_delete=models.PROTECT)
    asset = models.OneToOneField(ObjectAsset, on_delete=models.PROTECT)
    submitted_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUBMITTED)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    graded_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True)
    feedback = models.CharField(max_length=1000, blank=True, default="")

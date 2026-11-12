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
    workspace_snapshot = models.ForeignKey(
        "workspaces.WorkspaceSnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="report_drafts",
    )
    snapshot_digest = models.CharField(max_length=64, blank=True, default="")
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
    workspace_snapshot = models.ForeignKey(
        "workspaces.WorkspaceSnapshot", on_delete=models.PROTECT, related_name="report_versions",
        null=True, blank=True,
    )
    # Execution facts are copied at submission time.  The source run and output
    # objects are retained with PROTECT, while these fields make the report a
    # self-contained immutable audit record even if a worker later inspects the run.
    execution_run = models.ForeignKey(
        "workspaces.WorkspaceExecutionRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="report_versions",
    )
    execution_status = models.CharField(max_length=24, blank=True, default="")
    execution_result_summary = models.CharField(max_length=500, blank=True, default="")
    execution_rule_summary = models.JSONField(default=dict)
    execution_rule_digest = models.CharField(
        max_length=64, blank=True, default="", db_collation="ascii_bin"
    )
    execution_snapshot = models.ForeignKey(
        "workspaces.WorkspaceSnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="execution_report_versions",
    )
    execution_snapshot_digest = models.CharField(
        max_length=64, blank=True, default="", db_collation="ascii_bin"
    )
    execution_stdout_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="report_execution_stdout_versions",
    )
    execution_stderr_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="report_execution_stderr_versions",
    )
    execution_test_report_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="report_execution_test_report_versions",
    )
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
            models.CheckConstraint(
                condition=models.Q(execution_run__isnull=True)
                | models.Q(
                    execution_status__in=(
                        "PASSED",
                        "FAILED",
                        "TIMEOUT",
                        "RESOURCE_EXCEEDED",
                        "REJECTED",
                    )
                ),
                name="reports_version_exec_status_ck",
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


class SystemArtifact(AppendOnlyModel):
    class Kind(models.TextChoices):
        WORKSPACE_SNAPSHOT = "WORKSPACE_SNAPSHOT"

    public_id = public_id_field()
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="system_artifacts"
    )
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="system_artifacts")
    workspace_snapshot = models.ForeignKey(
        "workspaces.WorkspaceSnapshot", on_delete=models.PROTECT, related_name="system_artifacts"
    )
    asset = models.ForeignKey(
        ObjectAsset, on_delete=models.PROTECT, related_name="system_artifacts"
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    digest_sha256 = models.CharField(max_length=64, db_collation="ascii_bin")
    execution_run = models.ForeignKey(
        "workspaces.WorkspaceExecutionRun", on_delete=models.PROTECT,
        null=True, blank=True, related_name="system_artifacts",
    )
    execution_evidence = models.JSONField(default=dict)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "reports_system_artifact"
        constraints = [
            models.UniqueConstraint(
                fields=("task", "asset"), name="reports_artifact_task_asset_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=("WORKSPACE_SNAPSHOT",)),
                name="reports_artifact_kind_ck",
            ),
        ]
        indexes = [models.Index(fields=("task", "created_at"), name="reports_artifact_task_idx")]

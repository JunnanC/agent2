from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import (
    AppendOnlyModel,
    CompensationTask,
    FailureRecord,
    FileDownloadGrant,
    ObjectAsset,
    VersionedModel,
)
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


class ArchiveJob(VersionedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        VERIFYING = "VERIFYING"
        PASSED = "PASSED"
        FAILED = "FAILED"

    public_id = public_id_field()
    task = models.OneToOneField(
        ExperimentTask, on_delete=models.PROTECT, related_name="archive_job"
    )
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="archive_jobs")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    terminal_target = models.CharField(max_length=16, choices=ExperimentTask.TerminalTarget.choices)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    failure_record = models.ForeignKey(
        FailureRecord,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="archive_jobs",
    )
    compensation_task = models.ForeignKey(
        CompensationTask,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="archive_jobs",
    )
    trace_id = models.CharField(max_length=32)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "archives_archive_job"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("QUEUED", "RUNNING", "VERIFYING", "PASSED", "FAILED")
                ),
                name="archives_job_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(terminal_target__in=("COMPLETED", "CANCELLED", "EXPIRED")),
                name="archives_job_target_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1)
                & models.Q(attempt_count__lte=models.F("max_attempts")),
                name="archives_job_attempt_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("course", "status", "updated_at"), name="archives_job_course_idx"),
        ]


class ArchiveManifest(AppendOnlyModel):
    public_id = public_id_field()
    job = models.OneToOneField(ArchiveJob, on_delete=models.PROTECT, related_name="manifest")
    task = models.OneToOneField(
        ExperimentTask, on_delete=models.PROTECT, related_name="archive_manifest"
    )
    package_asset = models.OneToOneField(
        ObjectAsset, on_delete=models.PROTECT, related_name="archive_manifest"
    )
    entries = models.JSONField(default=list)
    manifest_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    package_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    object_count = models.PositiveIntegerField(default=0)
    total_size_bytes = models.PositiveBigIntegerField(default=0)
    retention_until = models.DateTimeField()
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "archives_archive_manifest"
        indexes = [
            models.Index(fields=("retention_until",), name="archives_manifest_ret_idx"),
            models.Index(fields=("manifest_digest",), name="archives_manifest_digest_idx"),
        ]


class ArchiveVerification(AppendOnlyModel):
    class Result(models.TextChoices):
        PASSED = "PASSED"
        FAILED = "FAILED"

    public_id = public_id_field()
    job = models.ForeignKey(ArchiveJob, on_delete=models.PROTECT, related_name="verifications")
    manifest = models.ForeignKey(
        ArchiveManifest,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="verifications",
    )
    package_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="archive_verifications",
    )
    attempt_no = models.PositiveIntegerField()
    result = models.CharField(max_length=16, choices=Result.choices)
    checks = models.JSONField(default=list)
    expected_digest = models.CharField(max_length=64, blank=True, default="")
    actual_digest = models.CharField(max_length=64, blank=True, default="")
    error_code = models.CharField(max_length=64, blank=True, default="")
    verified_at = models.DateTimeField()
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "archives_archive_verification"
        constraints = [
            models.UniqueConstraint(
                fields=("job", "attempt_no"), name="archives_verify_attempt_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(result__in=("PASSED", "FAILED")),
                name="archives_verify_result_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("job", "created_at"), name="archives_verify_job_idx"),
            models.Index(fields=("result", "created_at"), name="archives_verify_result_idx"),
        ]


class ArchiveExportGrant(AppendOnlyModel):
    public_id = public_id_field()
    manifest = models.ForeignKey(
        ArchiveManifest, on_delete=models.PROTECT, related_name="export_grants"
    )
    download_grant = models.OneToOneField(
        FileDownloadGrant, on_delete=models.PROTECT, related_name="archive_export"
    )
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="archive_exports")
    requested_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="requested_archive_exports"
    )
    approved_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="approved_archive_exports"
    )
    portal = models.CharField(max_length=16)
    scope = models.JSONField(default=dict)
    scope_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    retention_until = models.DateTimeField()
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "archives_export_grant"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(portal__in=("USER", "TEACHING", "PLATFORM")),
                name="archives_export_portal_ck",
            )
        ]
        indexes = [
            models.Index(fields=("course", "created_at"), name="archives_export_course_idx"),
            models.Index(fields=("requested_by", "created_at"), name="archives_export_actor_idx"),
            models.Index(fields=("retention_until",), name="archives_export_ret_idx"),
        ]

from django.db import models

from apps.core.identifiers import new_ulid
from apps.core.models import AppendOnlyModel, VersionedModel
from apps.courses.models import Course
from apps.experiments.models import ExperimentTask
from apps.governance.models import ImageAsset, QuotaReservation, ResourceProfile, RuntimeAdapter


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class ProvisioningInstance(VersionedModel):
    class Status(models.TextChoices):
        CREATING = "CREATING"
        READY = "READY"
        DESTROYING = "DESTROYING"
        DESTROYED = "DESTROYED"
        FAILED = "FAILED"
        ORPHANED = "ORPHANED"

    public_id = public_id_field()
    task = models.OneToOneField(
        ExperimentTask, on_delete=models.PROTECT, related_name="provisioning_instance"
    )
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="provisioning_instances"
    )
    runtime_adapter = models.ForeignKey(
        RuntimeAdapter, on_delete=models.PROTECT, related_name="provisioning_instances"
    )
    image = models.ForeignKey(
        ImageAsset, on_delete=models.PROTECT, related_name="provisioning_instances"
    )
    resource_profile = models.ForeignKey(
        ResourceProfile, on_delete=models.PROTECT, related_name="provisioning_instances"
    )
    runtime_type = models.CharField(max_length=16)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CREATING)
    external_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    endpoint = models.CharField(max_length=500, blank=True, default="")
    external_metadata = models.JSONField(default=dict, blank=True)
    failure_record = models.ForeignKey(
        "core.FailureRecord",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="provisioning_instances",
    )
    created_trace_id = models.CharField(max_length=32)
    ready_at = models.DateTimeField(null=True, blank=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "provisioning_instance"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "CREATING",
                        "READY",
                        "DESTROYING",
                        "DESTROYED",
                        "FAILED",
                        "ORPHANED",
                    )
                ),
                name="prov_instance_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("course", "status"), name="prov_instance_course_idx"),
            models.Index(fields=("status", "updated_at"), name="prov_instance_status_idx"),
        ]


class ProvisioningJob(VersionedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        RETRY = "RETRY"
        PASSED = "PASSED"
        FAILED = "FAILED"
        CANCELLED = "CANCELLED"

    class Stage(models.TextChoices):
        QUOTA_CHECK = "QUOTA_CHECK"
        IMAGE_PREPARE = "IMAGE_PREPARE"
        CREATE = "CREATE"
        NETWORK_ATTACH = "NETWORK_ATTACH"
        BOOT_PROBE = "BOOT_PROBE"
        WORKSPACE_READY = "WORKSPACE_READY"

    public_id = public_id_field()
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="provisioning_jobs"
    )
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="provisioning_jobs")
    reservation = models.ForeignKey(
        QuotaReservation, on_delete=models.PROTECT, related_name="provisioning_jobs"
    )
    attempt_no = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    current_stage = models.CharField(max_length=32, blank=True, default="")
    retryable = models.BooleanField(default=False)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    idempotency_key = models.CharField(max_length=128)
    trace_id = models.CharField(max_length=32)
    failure_record = models.ForeignKey(
        "core.FailureRecord",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="provisioning_jobs",
    )
    compensation_task = models.ForeignKey(
        "core.CompensationTask",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="provisioning_jobs",
    )
    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "provisioning_job"
        constraints = [
            models.UniqueConstraint(
                fields=("task", "attempt_no"), name="prov_job_task_attempt_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("QUEUED", "RUNNING", "RETRY", "PASSED", "FAILED", "CANCELLED")
                ),
                name="prov_job_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_no__gt=0) & models.Q(max_attempts__gt=0),
                name="prov_job_attempts_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("task", "status", "created_at"), name="prov_job_task_idx"),
            models.Index(fields=("course", "status", "updated_at"), name="prov_job_course_idx"),
            models.Index(fields=("status", "current_stage"), name="prov_job_stage_idx"),
        ]


class RuntimeCapacityReservation(VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        RELEASED = "RELEASED"

    public_id = public_id_field()
    reservation = models.OneToOneField(
        QuotaReservation, on_delete=models.PROTECT, related_name="runtime_capacity_binding"
    )
    runtime_adapter = models.ForeignKey(
        RuntimeAdapter, on_delete=models.PROTECT, related_name="capacity_reservations"
    )
    cpu_millicores = models.PositiveBigIntegerField()
    memory_mb = models.PositiveBigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "provisioning_runtime_capacity_reservation"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cpu_millicores__gt=0) & models.Q(memory_mb__gt=0),
                name="prov_capacity_reservation_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "RELEASED")),
                name="prov_capacity_reservation_status_ck",
            ),
        ]


class ProvisioningStageEvent(AppendOnlyModel):
    class Status(models.TextChoices):
        STARTED = "STARTED"
        PASSED = "PASSED"
        FAILED = "FAILED"
        SKIPPED = "SKIPPED"

    public_id = public_id_field()
    job = models.ForeignKey(ProvisioningJob, on_delete=models.PROTECT, related_name="stage_events")
    stage = models.CharField(max_length=32, choices=ProvisioningJob.Stage.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    attempt_no = models.PositiveIntegerField(default=1)
    detail_masked = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default="")
    trace_id = models.CharField(max_length=32)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "provisioning_stage_event"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("STARTED", "PASSED", "FAILED", "SKIPPED")),
                name="prov_stage_status_ck",
            ),
            models.UniqueConstraint(
                fields=("job", "stage", "attempt_no", "status"), name="prov_stage_event_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=("job", "created_at"), name="prov_stage_job_idx"),
            models.Index(fields=("stage", "status", "created_at"), name="prov_stage_state_idx"),
        ]

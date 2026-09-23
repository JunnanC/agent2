import uuid

from django.db import models

from .errors import ImmutableRecordError
from .identifiers import new_ulid


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs: object) -> int:
        raise ImmutableRecordError()

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ImmutableRecordError()


AppendOnlyManager = models.Manager.from_queryset(AppendOnlyQuerySet)


class VersionedQuerySet(models.QuerySet):
    def delete(self) -> tuple[int, dict[str, int]]:
        raise RuntimeError("Versioned business rows cannot be hard-deleted")


VersionedManager = models.Manager.from_queryset(VersionedQuerySet)


class VersionedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    row_version = models.PositiveBigIntegerField(default=1, editable=False)

    objects = VersionedManager()

    class Meta:
        abstract = True

    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise RuntimeError("Versioned rows must be changed through compare-and-swap services")
        super().save(*args, **kwargs)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise RuntimeError("Versioned business rows cannot be hard-deleted")


class AppendOnlyModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyManager()

    class Meta:
        abstract = True

    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise ImmutableRecordError()
        super().save(*args, **kwargs)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ImmutableRecordError()


class ObjectAsset(VersionedModel):
    class ScanStatus(models.TextChoices):
        PENDING = "PENDING"
        CLEAN = "CLEAN"
        INFECTED = "INFECTED"
        FAILED = "FAILED"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        PURGE_PENDING = "PURGE_PENDING"
        PURGED = "PURGED"

    public_id = models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )
    storage_backend = models.CharField(max_length=32, default="MINIO")
    bucket = models.CharField(max_length=128)
    object_key = models.CharField(max_length=500)
    object_version = models.CharField(max_length=128, blank=True, default="")
    digest_sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    media_type = models.CharField(max_length=255, blank=True, default="")
    original_name = models.CharField(max_length=255, blank=True, default="")
    owner_type = models.CharField(max_length=64)
    owner_ref = models.CharField(max_length=128)
    purpose = models.CharField(max_length=64)
    scan_status = models.CharField(
        max_length=16,
        choices=ScanStatus.choices,
        default=ScanStatus.PENDING,
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    failure_code = models.CharField(max_length=64, blank=True, default="")
    scan_completed_at = models.DateTimeField(null=True, blank=True)
    retention_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_object_asset"
        constraints = [
            models.UniqueConstraint(
                fields=("bucket", "object_key", "object_version"),
                name="core_asset_object_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(scan_status__in=("PENDING", "CLEAN", "INFECTED", "FAILED")),
                name="core_asset_scan_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "PURGE_PENDING", "PURGED")),
                name="core_asset_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("owner_type", "owner_ref"), name="core_asset_owner_idx"),
            models.Index(fields=("status", "retention_until"), name="core_asset_retention_idx"),
            models.Index(fields=("digest_sha256",), name="core_asset_digest_idx"),
        ]


class ObjectPurgeLog(AppendOnlyModel):
    class Result(models.TextChoices):
        PURGED = "PURGED"
        SKIPPED = "SKIPPED"
        FAILED = "FAILED"

    asset = models.ForeignKey(ObjectAsset, on_delete=models.PROTECT, related_name="purge_logs")
    object_key = models.CharField(max_length=512)
    object_version = models.CharField(max_length=128, blank=True, default="")
    digest_sha256 = models.CharField(max_length=64)
    result = models.CharField(max_length=16, choices=Result.choices)
    reason = models.CharField(max_length=255, blank=True, default="")
    error_code = models.CharField(max_length=64, blank=True, default="")
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "core_object_purge_log"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(result__in=("PURGED", "SKIPPED", "FAILED")),
                name="core_purge_result_ck",
            ),
        ]
        indexes = [models.Index(fields=("asset", "created_at"), name="core_purge_asset_idx")]


class FileDownloadGrant(VersionedModel):
    class Portal(models.TextChoices):
        USER = "USER"
        TEACHING = "TEACHING"
        PLATFORM = "PLATFORM"

    public_id = models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )
    asset = models.ForeignKey(ObjectAsset, on_delete=models.PROTECT, related_name="download_grants")
    requested_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="file_download_grants"
    )
    portal = models.CharField(max_length=16, choices=Portal.choices)
    course_ref = models.CharField(max_length=128, blank=True, default="")
    token_hash = models.CharField(max_length=64, unique=True, db_collation="ascii_bin")
    expires_at = models.DateTimeField()
    max_downloads = models.PositiveSmallIntegerField(default=1)
    download_count = models.PositiveSmallIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_file_download_grant"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(portal__in=("USER", "TEACHING", "PLATFORM")),
                name="core_file_grant_portal_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(max_downloads__gte=1)
                & models.Q(download_count__lte=models.F("max_downloads")),
                name="core_file_grant_count_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("asset", "expires_at"), name="core_file_grant_asset_idx"),
            models.Index(fields=("requested_by", "expires_at"), name="core_file_grant_actor_idx"),
        ]


class OutboxEvent(AppendOnlyModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=128)
    aggregate_type = models.CharField(max_length=64)
    aggregate_ref = models.CharField(max_length=128)
    payload = models.JSONField(default=dict)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "core_outbox_event"
        indexes = [
            models.Index(fields=("event_type", "created_at"), name="core_outbox_type_idx"),
            models.Index(
                fields=("aggregate_type", "aggregate_ref", "created_at"),
                name="core_outbox_subject_idx",
            ),
        ]


class OutboxDelivery(VersionedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        IN_FLIGHT = "IN_FLIGHT"
        RETRY = "RETRY"
        DELIVERED = "DELIVERED"
        DEAD = "DEAD"

    event = models.ForeignKey(OutboxEvent, on_delete=models.PROTECT, related_name="deliveries")
    destination = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=10)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    last_error_masked = models.TextField(blank=True, default="")

    class Meta:
        db_table = "core_outbox_delivery"
        constraints = [
            models.UniqueConstraint(
                fields=("event", "destination"),
                name="core_outbox_delivery_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("PENDING", "IN_FLIGHT", "RETRY", "DELIVERED", "DEAD")
                ),
                name="core_delivery_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1)
                & models.Q(attempt_count__lte=models.F("max_attempts")),
                name="core_delivery_attempts_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("status", "next_attempt_at", "lease_until"),
                name="core_delivery_schedule_idx",
            ),
        ]


class IdempotencyRecord(VersionedModel):
    class Status(models.TextChoices):
        PROCESSING = "PROCESSING"
        COMPLETED = "COMPLETED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_ref = models.CharField(max_length=64)
    auth_context = models.CharField(max_length=32)
    portal = models.CharField(max_length=16, blank=True, default="")
    method = models.CharField(max_length=8)
    endpoint = models.CharField(max_length=255)
    idempotency_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_headers = models.JSONField(default=dict)
    response_body = models.JSONField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_idempotency_record"
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "actor_ref",
                    "auth_context",
                    "portal",
                    "method",
                    "endpoint",
                    "idempotency_key",
                ),
                name="core_idempotency_scope_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("PROCESSING", "COMPLETED")),
                name="core_idem_status_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="PROCESSING", response_status__isnull=True)
                    | models.Q(status="COMPLETED", response_status__isnull=False)
                ),
                name="core_idem_response_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "expires_at"), name="core_idem_expiry_idx"),
        ]


class AuditLog(AppendOnlyModel):
    actor_ref = models.CharField(max_length=128)
    actor_portal = models.CharField(max_length=16, blank=True, default="")
    actor_context = models.JSONField(default=dict)
    action = models.CharField(max_length=128)
    course_ref = models.CharField(max_length=128, blank=True, default="")
    target_type = models.CharField(max_length=64)
    target_ref = models.CharField(max_length=128)
    before_masked = models.JSONField(null=True, blank=True)
    after_masked = models.JSONField(null=True, blank=True)
    result = models.CharField(max_length=32)
    error_code = models.CharField(max_length=64, blank=True, default="")
    client_ip_hash = models.CharField(max_length=64, blank=True, default="")
    user_agent_summary = models.CharField(max_length=255, blank=True, default="")
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "core_audit_log"
        indexes = [
            models.Index(
                fields=("target_type", "target_ref", "created_at"), name="core_audit_target_idx"
            ),
            models.Index(fields=("course_ref", "created_at"), name="core_audit_course_idx"),
            models.Index(fields=("actor_ref", "created_at"), name="core_audit_actor_idx"),
            models.Index(fields=("trace_id",), name="core_audit_trace_idx"),
        ]


class FailureRecord(AppendOnlyModel):
    failure_type = models.CharField(max_length=64)
    subject_type = models.CharField(max_length=64)
    subject_ref = models.CharField(max_length=128)
    error_code = models.CharField(max_length=64)
    message_masked = models.TextField(blank=True, default="")
    detail_masked = models.JSONField(default=dict)
    retryable = models.BooleanField(default=False)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "core_failure_record"
        indexes = [
            models.Index(
                fields=("subject_type", "subject_ref", "created_at"),
                name="core_failure_subject_idx",
            ),
            models.Index(fields=("error_code", "created_at"), name="core_failure_code_idx"),
        ]


class CompensationTask(VersionedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        IN_FLIGHT = "IN_FLIGHT"
        RETRY = "RETRY"
        COMPLETED = "COMPLETED"
        DEAD = "DEAD"

    public_id = models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )
    task_type = models.CharField(max_length=128)
    subject_type = models.CharField(max_length=64)
    subject_ref = models.CharField(max_length=128)
    payload_masked = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=10)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    last_failure = models.ForeignKey(
        FailureRecord,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="compensation_tasks",
    )
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "core_compensation_task"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("PENDING", "IN_FLIGHT", "RETRY", "COMPLETED", "DEAD")
                ),
                name="core_comp_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1)
                & models.Q(attempt_count__lte=models.F("max_attempts")),
                name="core_comp_attempts_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("status", "next_attempt_at", "lease_until"),
                name="core_comp_schedule_idx",
            ),
            models.Index(fields=("subject_type", "subject_ref"), name="core_comp_subject_idx"),
        ]

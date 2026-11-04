from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import AppendOnlyModel, FailureRecord, ObjectAsset, VersionedModel
from apps.courses.models import Course
from apps.experiments.models import ExperimentTask
from apps.provisioning.models import ProvisioningInstance


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class WorkspaceSession(VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        REVOKED = "REVOKED"
        EXPIRED = "EXPIRED"

    public_id = public_id_field()
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="workspace_sessions"
    )
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="workspace_sessions")
    instance = models.ForeignKey(
        ProvisioningInstance, on_delete=models.PROTECT, related_name="workspace_sessions"
    )
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="workspace_sessions")
    portal = models.CharField(max_length=16, default="USER")
    jti = models.CharField(max_length=64, unique=True, db_collation="ascii_bin")
    token_hash = models.CharField(max_length=128, unique=True, db_collation="ascii_bin")
    active_marker = models.CharField(max_length=64, null=True, blank=True, unique=True)
    capabilities = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=255, blank=True, default="")
    last_seen_at = models.DateTimeField(null=True, blank=True)
    current_version = models.PositiveIntegerField(default=0)
    language = models.CharField(max_length=16, default="python")
    latest_snapshot = models.ForeignKey(
        "WorkspaceSnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_for_sessions",
    )

    class Meta:
        db_table = "workspaces_workspace_session"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(portal="USER"), name="workspace_session_portal_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "REVOKED", "EXPIRED")),
                name="workspace_session_status_ck",
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(status="ACTIVE") & models.Q(revoked_at__isnull=True))
                    | (
                        models.Q(status__in=("REVOKED", "EXPIRED"))
                        & models.Q(revoked_at__isnull=False)
                    )
                ),
                name="workspace_session_revocation_shape_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("task", "student", "status"), name="workspace_session_task_idx"),
            models.Index(fields=("status", "expires_at"), name="workspace_session_expiry_idx"),
            models.Index(
                fields=("course", "status", "updated_at"), name="workspace_session_course_idx"
            ),
        ]


class WorkspaceSnapshot(AppendOnlyModel):
    public_id = public_id_field()
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="workspace_snapshots"
    )
    session = models.ForeignKey(
        WorkspaceSession, on_delete=models.PROTECT, related_name="snapshots"
    )
    asset = models.ForeignKey(
        ObjectAsset, on_delete=models.PROTECT, related_name="workspace_snapshots"
    )
    version_no = models.PositiveIntegerField()
    client_seq = models.PositiveBigIntegerField()
    base_version = models.PositiveIntegerField(default=0)
    digest_sha256 = models.CharField(max_length=64, db_collation="ascii_bin")
    size_bytes = models.PositiveBigIntegerField(default=0)
    media_type = models.CharField(max_length=255, blank=True, default="application/octet-stream")
    language = models.CharField(max_length=16, default="python")
    initial = models.BooleanField(default=False)
    saved_at = models.DateTimeField()
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "workspaces_workspace_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=("task", "version_no"), name="workspace_snapshot_version_uniq"
            ),
            models.UniqueConstraint(
                fields=("task", "client_seq"), name="workspace_snapshot_seq_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gt=0), name="workspace_snapshot_version_ck"
            ),
        ]
        indexes = [
            models.Index(fields=("task", "version_no"), name="workspace_snapshot_task_idx"),
            models.Index(fields=("session", "saved_at"), name="workspace_snapshot_session_idx"),
        ]


class WorkspaceAutosaveLog(AppendOnlyModel):
    class Result(models.TextChoices):
        CONFIRMED = "CONFIRMED"
        REPLAYED = "REPLAYED"
        STALE = "STALE"
        CONFLICT = "CONFLICT"
        FAILED = "FAILED"

    public_id = public_id_field()
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="workspace_autosaves"
    )
    session = models.ForeignKey(
        WorkspaceSession, on_delete=models.PROTECT, related_name="autosave_logs"
    )
    client_seq = models.PositiveBigIntegerField()
    request_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    snapshot = models.ForeignKey(
        WorkspaceSnapshot,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="autosave_logs",
    )
    result = models.CharField(max_length=16, choices=Result.choices)
    error_code = models.CharField(max_length=64, blank=True, default="")
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "workspaces_workspace_autosave_log"
        constraints = [
            models.UniqueConstraint(
                fields=("task", "client_seq"), name="workspace_autosave_seq_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=("task", "created_at"), name="workspace_autosave_task_idx"),
            models.Index(fields=("session", "client_seq"), name="workspace_autosave_session_idx"),
        ]


class WorkspaceStorageJob(VersionedModel):
    """Durable contract for asynchronous workspace volume operations.

    The row is the public state machine boundary.  Runtime and storage workers
    may advance it through CAS, while browser requests only create QUEUED rows
    and read a sanitized projection.
    """

    class Kind(models.TextChoices):
        INITIALIZE = "INITIALIZE"
        CAPTURE = "CAPTURE"
        RESTORE = "RESTORE"
        FINALIZE = "FINALIZE"
        SWITCH = "SWITCH"
        RESET = "RESET"

    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        PASSED = "PASSED"
        FAILED = "FAILED"
        CANCELLED = "CANCELLED"

    TERMINAL_STATUSES = frozenset({Status.PASSED, Status.FAILED, Status.CANCELLED})

    public_id = public_id_field()
    kind = models.CharField(max_length=16, choices=Kind.choices)
    target_language = models.CharField(max_length=16, blank=True, default="")
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="workspace_storage_jobs"
    )
    session = models.ForeignKey(
        WorkspaceSession, on_delete=models.PROTECT, related_name="storage_jobs"
    )
    instance = models.ForeignKey(
        ProvisioningInstance, on_delete=models.PROTECT, related_name="workspace_storage_jobs"
    )
    source_snapshot = models.ForeignKey(
        "WorkspaceSnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="restore_storage_jobs",
    )
    result_snapshot = models.ForeignKey(
        "WorkspaceSnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="capture_storage_jobs",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    client_seq = models.PositiveBigIntegerField(null=True, blank=True)
    base_version = models.PositiveIntegerField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128, db_collation="ascii_bin")
    request_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    failure_record = models.ForeignKey(
        FailureRecord,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workspace_storage_jobs",
    )
    trace_id = models.CharField(max_length=32)
    queued_at = models.DateTimeField(auto_now_add=True)
    last_dispatched_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workspaces_workspace_storage_job"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=("INITIALIZE", "CAPTURE", "RESTORE", "FINALIZE", "SWITCH", "RESET")
                ),
                name="workspace_storage_kind_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("QUEUED", "RUNNING", "PASSED", "FAILED", "CANCELLED")
                ),
                name="workspace_storage_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(client_seq__isnull=True) | models.Q(client_seq__gt=0),
                name="workspace_storage_client_seq_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(base_version__isnull=True) | models.Q(base_version__gte=0),
                name="workspace_storage_base_version_ck",
            ),
            models.UniqueConstraint(
                fields=("task", "client_seq"),
                name="workspace_storage_capture_seq_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=("task", "created_at"), name="workspace_storage_task_idx"),
            models.Index(
                fields=("session", "status", "created_at"),
                name="workspace_storage_session_idx",
            ),
            models.Index(fields=("status", "queued_at"), name="workspace_storage_queue_idx"),
            models.Index(
                fields=("status", "last_dispatched_at"),
                name="workspace_storage_dispatch_idx",
            ),
        ]


class WorkspaceCheckpoint(AppendOnlyModel):
    public_id = public_id_field()
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="workspace_checkpoints"
    )
    session = models.ForeignKey(
        WorkspaceSession, on_delete=models.PROTECT, related_name="checkpoints"
    )
    snapshot = models.ForeignKey(
        WorkspaceSnapshot, on_delete=models.PROTECT, related_name="checkpoints"
    )
    checkpoint_no = models.PositiveIntegerField()
    name = models.CharField(max_length=180)
    source_seq = models.PositiveBigIntegerField()
    digest_sha256 = models.CharField(max_length=64, db_collation="ascii_bin")
    retention_until = models.DateTimeField(null=True, blank=True)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "workspaces_workspace_checkpoint"
        constraints = [
            models.UniqueConstraint(
                fields=("task", "checkpoint_no"), name="workspace_checkpoint_no_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=("task", "created_at"), name="workspace_checkpoint_task_idx"),
            models.Index(fields=("retention_until",), name="ws_checkpoint_retention_idx"),
        ]


class OperationEvent(AppendOnlyModel):
    public_id = public_id_field()
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="workspace_operation_events"
    )
    session = models.ForeignKey(
        WorkspaceSession, on_delete=models.PROTECT, related_name="operation_events"
    )
    seq = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=64)
    phase = models.CharField(max_length=64, blank=True, default="")
    payload_masked = models.JSONField(default=dict)
    result_summary = models.CharField(max_length=500, blank=True, default="")
    occurred_at = models.DateTimeField()
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "workspaces_operation_event"
        constraints = [
            models.UniqueConstraint(fields=("task", "seq"), name="workspace_operation_seq_uniq"),
        ]
        indexes = [
            models.Index(fields=("task", "occurred_at", "id"), name="workspace_operation_task_idx"),
            models.Index(fields=("event_type", "occurred_at"), name="workspace_operation_type_idx"),
        ]


class WorkspaceExecutionRun(VersionedModel):
    """A single auditable execution of the frozen task rules.

    The row is mutable only through the execution service/CAS transition path.  Students
    never receive a write endpoint for this model; output assets are immutable ObjectAsset
    versions and therefore remain usable by later report/review stages.
    """

    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        PASSED = "PASSED"
        FAILED = "FAILED"
        TIMEOUT = "TIMEOUT"
        RESOURCE_EXCEEDED = "RESOURCE_EXCEEDED"
        REJECTED = "REJECTED"

    public_id = public_id_field()
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="workspace_execution_runs"
    )
    session = models.ForeignKey(
        WorkspaceSession, on_delete=models.PROTECT, related_name="execution_runs"
    )
    snapshot = models.ForeignKey(
        WorkspaceSnapshot,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="execution_runs",
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED)
    execution_rule_summary = models.JSONField(default=dict)
    execution_rule_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    idempotency_key = models.CharField(max_length=128, unique=True, db_collation="ascii_bin")
    stdout_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="execution_stdout_runs",
    )
    stderr_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="execution_stderr_runs",
    )
    test_report_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="execution_test_report_runs",
    )
    error_code = models.CharField(max_length=64, blank=True, default="")
    result_summary = models.CharField(max_length=500, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "workspaces_execution_run"
        constraints = [
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
                name="workspace_execution_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_ms__isnull=True) | models.Q(duration_ms__gte=0),
                name="workspace_execution_duration_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("task", "created_at", "id"), name="workspace_exec_task_idx"),
            models.Index(fields=("session", "created_at"), name="workspace_exec_session_idx"),
            models.Index(fields=("status", "created_at"), name="workspace_exec_status_idx"),
        ]

    @property
    def execution_spec(self) -> dict[str, object]:
        """Compatibility alias for callers using the template vocabulary."""

        return dict(self.execution_rule_summary or {})

    @property
    def execution_spec_digest(self) -> str:
        return self.execution_rule_digest

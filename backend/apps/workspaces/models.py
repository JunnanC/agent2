from django.db import models

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


class WorkspaceSnapshot(AppendOnlyModel):
    public_id = public_id_field()
    task = models.ForeignKey(
        ExperimentTask, on_delete=models.PROTECT, related_name="workspace_snapshots"
    )
    question = models.ForeignKey(
        "experiments.PublicationTask", on_delete=models.PROTECT, null=True, blank=True,
        related_name="code_snapshots",
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
        ]


class StudentWorkspace(VersionedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        RUNNING = "RUNNING"
        FAILED = "FAILED"
        EXPIRED = "EXPIRED"

    # ExperimentTask already identifies the student and freezes the image and adapter.
    task = models.OneToOneField(ExperimentTask, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField(db_index=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    @property
    def container_name(self) -> str:
        return f"edu-workspace-{self.task.public_id}-{int(self.expires_at.timestamp())}"

    @property
    def volume_name(self) -> str:
        return self.container_name + "-data"

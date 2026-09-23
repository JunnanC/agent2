from rest_framework import serializers

from .models import OperationEvent, WorkspaceCheckpoint, WorkspaceSession, WorkspaceSnapshot


class WorkspaceSessionSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    course_id = serializers.CharField()
    instance_id = serializers.CharField()
    portal = serializers.CharField()
    status = serializers.ChoiceField(choices=WorkspaceSession.Status.choices)
    capabilities = serializers.DictField()
    expires_at = serializers.DateTimeField()
    revoked_at = serializers.DateTimeField(allow_null=True)
    current_version = serializers.IntegerField()
    latest_client_seq = serializers.IntegerField()
    row_version = serializers.IntegerField()
    # The raw ticket is returned only by issue/renew responses and is never
    # persisted in the session projection or included in read-only selectors.
    workspace_token = serializers.CharField(required=False, read_only=True)


class WorkspaceEnterSerializer(serializers.Serializer):
    task = serializers.DictField()
    session = WorkspaceSessionSerializer()


class WorkspaceSnapshotSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    session_id = serializers.CharField()
    version_no = serializers.IntegerField()
    client_seq = serializers.IntegerField()
    base_version = serializers.IntegerField()
    digest_sha256 = serializers.CharField()
    size_bytes = serializers.IntegerField()
    media_type = serializers.CharField()
    saved_at = serializers.DateTimeField()


class WorkspaceCheckpointSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    session_id = serializers.CharField()
    checkpoint_no = serializers.IntegerField()
    name = serializers.CharField()
    source_seq = serializers.IntegerField()
    digest_sha256 = serializers.CharField()
    version_no = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    retention_until = serializers.DateTimeField(allow_null=True)


class WorkspaceCheckpointListSerializer(serializers.Serializer):
    items = WorkspaceCheckpointSerializer(many=True)
    current_version = serializers.IntegerField()
    row_version = serializers.IntegerField()


class OperationEventSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    seq = serializers.IntegerField()
    event_type = serializers.CharField()
    phase = serializers.CharField()
    payload = serializers.DictField()
    result_summary = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    trace_id = serializers.CharField()


class CheckpointWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=180, required=False, allow_blank=True)


class WorkspaceOperationSerializer(serializers.Serializer):
    operation = serializers.CharField(max_length=64)
    arguments = serializers.DictField(required=False)


def session_data(item: WorkspaceSession, *, token: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "public_id": item.public_id,
        "task_id": item.task.public_id,
        "course_id": item.course.public_id,
        "instance_id": item.instance.public_id,
        "portal": item.portal,
        "status": item.status,
        "capabilities": item.capabilities,
        "expires_at": item.expires_at,
        "revoked_at": item.revoked_at,
        "current_version": item.current_version,
        "latest_client_seq": item.latest_snapshot.client_seq if item.latest_snapshot_id else 0,
        "row_version": item.row_version,
    }
    if token is not None:
        value["workspace_token"] = token
    return value


def snapshot_data(item: WorkspaceSnapshot) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "task_id": item.task.public_id,
        "session_id": item.session.public_id,
        "version_no": item.version_no,
        "client_seq": item.client_seq,
        "base_version": item.base_version,
        "digest_sha256": item.digest_sha256,
        "size_bytes": item.size_bytes,
        "media_type": item.media_type,
        "saved_at": item.saved_at,
    }


def checkpoint_data(item: WorkspaceCheckpoint) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "task_id": item.task.public_id,
        "session_id": item.session.public_id,
        "checkpoint_no": item.checkpoint_no,
        "name": item.name,
        "source_seq": item.source_seq,
        "digest_sha256": item.digest_sha256,
        "version_no": item.snapshot.version_no,
        "created_at": item.created_at,
        "retention_until": item.retention_until,
    }


def operation_data(item: OperationEvent) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "task_id": item.task.public_id,
        "seq": item.seq,
        "event_type": item.event_type,
        "phase": item.phase,
        "payload": item.payload_masked,
        "result_summary": item.result_summary,
        "occurred_at": item.occurred_at,
        "trace_id": item.trace_id,
    }

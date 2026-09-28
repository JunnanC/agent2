from rest_framework import serializers

from .models import (
    OperationEvent,
    WorkspaceCheckpoint,
    WorkspaceExecutionRun,
    WorkspaceSession,
    WorkspaceSnapshot,
)


class WorkspaceSessionSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    course_id = serializers.CharField()
    instance_id = serializers.CharField()
    portal = serializers.CharField()
    status = serializers.ChoiceField(choices=WorkspaceSession.Status.choices)
    capabilities = serializers.DictField()
    workspace_urls = serializers.DictField(child=serializers.CharField())
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
    execution_run_id = serializers.CharField(required=False, allow_null=True)
    execution_status = serializers.CharField(required=False, allow_null=True)


class WorkspaceExecutionRunSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    session_id = serializers.CharField()
    snapshot_id = serializers.CharField(allow_null=True)
    status = serializers.ChoiceField(choices=WorkspaceExecutionRun.Status.choices)
    error_code = serializers.CharField()
    result_summary = serializers.CharField()
    started_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)
    duration_ms = serializers.IntegerField(allow_null=True)
    trace_id = serializers.CharField()


class WorkspaceExecutionRunListSerializer(serializers.Serializer):
    items = WorkspaceExecutionRunSerializer(many=True)


class CheckpointWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=180, required=False, allow_blank=True)


class WorkspaceOperationSerializer(serializers.Serializer):
    operation = serializers.CharField(max_length=64)
    arguments = serializers.DictField(required=False)


class WorkbenchTaskSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    course_id = serializers.CharField()
    publication_id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    status = serializers.CharField()
    deadline = serializers.DateTimeField(allow_null=True)
    assignment_deadline = serializers.DateTimeField(allow_null=True)
    report_required = serializers.BooleanField()
    report_strategy = serializers.ChoiceField(choices=("REPORT", "COMPLETE"))
    allowed_actions = serializers.ListField(child=serializers.CharField())
    allowed_operations = serializers.ListField(child=serializers.CharField())
    blockers = serializers.ListField(child=serializers.DictField())
    current_failure = serializers.DictField()
    row_version = serializers.IntegerField()


class WorkbenchContentSerializer(serializers.Serializer):
    description = serializers.CharField()
    objectives = serializers.ListField(child=serializers.JSONField())
    steps = serializers.ListField(child=serializers.JSONField())
    constraints = serializers.ListField(child=serializers.JSONField())
    deliverables = serializers.ListField(child=serializers.JSONField())
    materials = serializers.ListField(child=serializers.DictField())


class WorkbenchTemplateSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    name = serializers.CharField()
    version_id = serializers.CharField()
    version_no = serializers.IntegerField()
    dependencies = serializers.ListField(child=serializers.JSONField())
    workspace_capabilities = serializers.DictField()
    manual_asset_id = serializers.CharField(allow_null=True)
    starter_asset_id = serializers.CharField(allow_null=True)
    report_template_asset_id = serializers.CharField(allow_null=True)


class WorkbenchRecentExecutionSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    status = serializers.CharField()
    result_summary = serializers.CharField()
    finished_at = serializers.DateTimeField(allow_null=True)
    duration_ms = serializers.IntegerField(allow_null=True)


class WorkbenchTestsSerializer(serializers.Serializer):
    public_count = serializers.IntegerField()
    count = serializers.IntegerField()
    summary = serializers.ListField(child=serializers.DictField())
    recent_execution = WorkbenchRecentExecutionSerializer(allow_null=True)


class WorkbenchStageSerializer(serializers.Serializer):
    public_id = serializers.CharField(required=False)
    stage = serializers.CharField()
    status = serializers.CharField()
    attempt_no = serializers.IntegerField(allow_null=True)
    error_code = serializers.CharField(required=False)
    started_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)


class WorkbenchProvisioningSerializer(serializers.Serializer):
    status = serializers.CharField()
    job_id = serializers.CharField(allow_null=True)
    current_stage = serializers.CharField(allow_null=True)
    progress = serializers.IntegerField()
    attempt_no = serializers.IntegerField(required=False)
    retryable = serializers.BooleanField()
    failure = serializers.DictField(allow_null=True)
    stages = WorkbenchStageSerializer(many=True)
    events_channel = serializers.CharField()


class WorkbenchSubmissionSerializer(serializers.Serializer):
    required = serializers.BooleanField()
    kind = serializers.ChoiceField(choices=("REPORT", "SYSTEM_ARTIFACT"))
    strategy = serializers.ChoiceField(choices=("REPORT", "COMPLETE"))
    can_submit = serializers.BooleanField()
    blocked_reason = serializers.DictField(allow_null=True)
    draft_status = serializers.CharField(allow_null=True)


class WorkbenchSerializer(serializers.Serializer):
    task = WorkbenchTaskSerializer()
    content = WorkbenchContentSerializer()
    template = WorkbenchTemplateSerializer()
    tests = WorkbenchTestsSerializer()
    provisioning = WorkbenchProvisioningSerializer()
    submission = WorkbenchSubmissionSerializer()


def session_data(item: WorkspaceSession, *, token: str | None = None) -> dict[str, object]:
    workspace_urls = {
        capability: f"/workspace/{item.public_id}/{capability}/"
        for capability in ("webide", "notebook", "terminal", "preview")
        if bool((item.capabilities or {}).get(capability))
    }
    value: dict[str, object] = {
        "public_id": item.public_id,
        "task_id": item.task.public_id,
        "course_id": item.course.public_id,
        "instance_id": item.instance.public_id,
        "portal": item.portal,
        "status": item.status,
        "capabilities": item.capabilities,
        "workspace_urls": workspace_urls,
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
    payload = item.payload_masked
    result: dict[str, object] = {
        "public_id": item.public_id,
        "task_id": item.task.public_id,
        "seq": item.seq,
        "event_type": item.event_type,
        "phase": item.phase,
        "payload": payload,
        "result_summary": item.result_summary,
        "occurred_at": item.occurred_at,
        "trace_id": item.trace_id,
    }
    if "execution_run_id" in payload:
        result["execution_run_id"] = payload["execution_run_id"]
        result["execution_status"] = payload.get("execution_status")
    return result


def execution_run_data(item: WorkspaceExecutionRun) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "task_id": item.task.public_id,
        "session_id": item.session.public_id,
        "snapshot_id": item.snapshot.public_id if item.snapshot_id else None,
        "status": item.status,
        "error_code": item.error_code,
        "result_summary": item.result_summary,
        "started_at": item.started_at,
        "finished_at": item.finished_at,
        "duration_ms": item.duration_ms,
        "trace_id": item.trace_id,
    }

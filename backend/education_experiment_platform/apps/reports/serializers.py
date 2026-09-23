from rest_framework import serializers

from apps.core.models import ObjectAsset

from .models import ReportDraft, ReportVersion, SystemArtifact


class ReportDraftWriteSerializer(serializers.Serializer):
    body_markdown = serializers.CharField(allow_blank=True, max_length=500_000)


class ReportAttachmentCreateSerializer(serializers.Serializer):
    file_name = serializers.CharField(max_length=255)
    media_type = serializers.CharField(max_length=255)
    size_bytes = serializers.IntegerField(min_value=1)
    digest_sha256 = serializers.RegexField(r"^[0-9a-fA-F]{64}$")


class ReportAttachmentDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    file_name = serializers.CharField()
    media_type = serializers.CharField()
    size_bytes = serializers.IntegerField()
    digest_sha256 = serializers.CharField()
    scan_status = serializers.ChoiceField(choices=ObjectAsset.ScanStatus.choices)
    status = serializers.ChoiceField(choices=ObjectAsset.Status.choices)
    failure_code = serializers.CharField()
    attached = serializers.BooleanField()
    row_version = serializers.IntegerField()


class ReportAttachmentUploadDataSerializer(serializers.Serializer):
    asset = ReportAttachmentDataSerializer()
    upload = serializers.DictField()


class ReportAttachmentUploadResponseSerializer(serializers.Serializer):
    data = ReportAttachmentUploadDataSerializer()
    meta = serializers.DictField()


class ReportAttachmentResponseSerializer(serializers.Serializer):
    data = ReportAttachmentDataSerializer()
    meta = serializers.DictField()


class ReportDraftDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    body_markdown = serializers.CharField()
    snapshot_digest = serializers.CharField(allow_blank=True)
    status = serializers.ChoiceField(choices=ReportDraft.Status.choices)
    attachments = ReportAttachmentDataSerializer(many=True)
    row_version = serializers.IntegerField()
    updated_at = serializers.DateTimeField()


class ReportDraftResponseSerializer(serializers.Serializer):
    data = ReportDraftDataSerializer()
    meta = serializers.DictField()


class ReportVersionAttachmentDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    file_name = serializers.CharField()
    media_type = serializers.CharField()
    size_bytes = serializers.IntegerField()
    digest_sha256 = serializers.CharField()
    asset_id = serializers.CharField()


class ReportVersionDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    version_no = serializers.IntegerField()
    body_markdown = serializers.CharField()
    body_digest = serializers.CharField()
    snapshot_digest = serializers.CharField()
    submitted_at = serializers.DateTimeField()
    submitted_by_id = serializers.CharField()
    trace_id = serializers.CharField()
    attachments = ReportVersionAttachmentDataSerializer(many=True)


class ReportVersionResponseSerializer(serializers.Serializer):
    data = ReportVersionDataSerializer()
    meta = serializers.DictField()


class ReportVersionListResponseSerializer(serializers.Serializer):
    data = ReportVersionDataSerializer(many=True)
    meta = serializers.DictField()


class SystemArtifactDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    kind = serializers.ChoiceField(choices=SystemArtifact.Kind.choices)
    asset_id = serializers.CharField()
    digest_sha256 = serializers.CharField()
    created_at = serializers.DateTimeField()


class SystemArtifactResponseSerializer(serializers.Serializer):
    data = SystemArtifactDataSerializer()
    meta = serializers.DictField()


class ReportAttachmentStatusSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField())
    items = serializers.ListField(child=serializers.DictField())


class ReportPreviewDataSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("REPORT", "SYSTEM_ARTIFACT"))
    task_id = serializers.CharField()
    version = ReportVersionDataSerializer(required=False)
    artifact = SystemArtifactDataSerializer(required=False)


class ReportPreviewResponseSerializer(serializers.Serializer):
    data = ReportPreviewDataSerializer()
    meta = serializers.DictField()


class ReportCompleteDataSerializer(serializers.Serializer):
    artifact = SystemArtifactDataSerializer()
    task_status = serializers.ChoiceField(choices=("UNDER_REVIEW",))
    task_row_version = serializers.IntegerField()


class ReportCompleteResponseSerializer(serializers.Serializer):
    data = ReportCompleteDataSerializer()
    meta = serializers.DictField()


class ReportScanAnomalyItemSerializer(serializers.Serializer):
    asset_id = serializers.CharField()
    task_id = serializers.CharField()
    scan_status = serializers.ChoiceField(choices=ObjectAsset.ScanStatus.choices)
    failure_code = serializers.CharField()
    created_at = serializers.DateTimeField()


class ReportScanAnomalySummarySerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField())
    items = ReportScanAnomalyItemSerializer(many=True)


class GenericReportResponseSerializer(serializers.Serializer):
    data = ReportScanAnomalySummarySerializer()
    meta = serializers.DictField()


def attachment_data(asset: ObjectAsset, *, attached: bool) -> dict[str, object]:
    return {
        "public_id": asset.public_id,
        "file_name": asset.original_name,
        "media_type": asset.media_type,
        "size_bytes": asset.size_bytes,
        "digest_sha256": asset.digest_sha256,
        "scan_status": asset.scan_status,
        "status": asset.status,
        "failure_code": asset.failure_code,
        "attached": attached,
        "row_version": asset.row_version,
    }


def report_draft_data(draft: ReportDraft) -> dict[str, object]:
    attached_assets = {
        link.asset_id: link.asset
        for link in draft.attachments.all()
        if link.asset.scan_status == ObjectAsset.ScanStatus.CLEAN
        and link.asset.status == ObjectAsset.Status.ACTIVE
    }
    pending_assets = ObjectAsset.objects.filter(
        owner_type="REPORT_ATTACHMENT", owner_ref=draft.task.public_id
    ).order_by("created_at", "id")
    attachments = [
        attachment_data(asset, attached=asset.pk in attached_assets)
        for asset in pending_assets
        if asset.scan_status != ObjectAsset.ScanStatus.CLEAN or asset.pk in attached_assets
    ]
    return {
        "public_id": draft.public_id,
        "task_id": draft.task.public_id,
        "body_markdown": draft.body_markdown,
        "snapshot_digest": draft.snapshot_digest,
        "status": draft.status,
        "attachments": attachments,
        "row_version": draft.row_version,
        "updated_at": draft.updated_at,
    }


def report_version_data(version: ReportVersion) -> dict[str, object]:
    return {
        "public_id": version.public_id,
        "task_id": version.task.public_id,
        "version_no": version.version_no,
        "body_markdown": version.body_markdown,
        "body_digest": version.body_digest,
        "snapshot_digest": version.snapshot_digest,
        "submitted_at": version.submitted_at,
        "submitted_by_id": version.submitted_by.public_id,
        "trace_id": version.trace_id,
        "attachments": [
            {
                "public_id": row.attachment.public_id,
                "file_name": row.attachment.asset.original_name,
                "media_type": row.attachment.asset.media_type,
                "size_bytes": row.attachment.asset.size_bytes,
                "digest_sha256": row.asset_digest,
                "asset_id": row.attachment.asset.public_id,
            }
            for row in version.attachments.all().order_by("created_at", "id")
        ],
    }


def system_artifact_data(artifact: SystemArtifact) -> dict[str, object]:
    return {
        "public_id": artifact.public_id,
        "task_id": artifact.task.public_id,
        "kind": artifact.kind,
        "asset_id": artifact.asset.public_id,
        "digest_sha256": artifact.digest_sha256,
        "created_at": artifact.created_at,
    }

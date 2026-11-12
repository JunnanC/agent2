from rest_framework import serializers

from apps.core.models import ObjectAsset


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


class ReportAttachmentStatusSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField())
    items = serializers.ListField(child=serializers.DictField())


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


class GenericReportResponseSerializer(serializers.Serializer):
    data = serializers.DictField()
    meta = serializers.DictField()

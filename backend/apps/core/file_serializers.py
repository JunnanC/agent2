from rest_framework import serializers


class DownloadGrantDataSerializer(serializers.Serializer):
    grant_id = serializers.CharField()
    download_path = serializers.CharField()
    expires_at = serializers.DateTimeField()
    max_downloads = serializers.IntegerField()


class DownloadGrantResponseSerializer(serializers.Serializer):
    data = DownloadGrantDataSerializer()
    meta = serializers.DictField()


class DownloadGrantRevokeDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    revoked_at = serializers.DateTimeField(allow_null=True)
    row_version = serializers.IntegerField()


class DownloadGrantRevokeResponseSerializer(serializers.Serializer):
    data = DownloadGrantRevokeDataSerializer()
    meta = serializers.DictField()

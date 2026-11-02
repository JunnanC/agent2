from rest_framework import serializers

from .models import Notification, Preference


class NotificationResponseSerializer(serializers.Serializer):
    """Named placeholder for envelope responses represented by view helpers."""

    pass


class PreferenceSerializer(serializers.Serializer):
    channels = serializers.JSONField(required=False)
    muted_kinds = serializers.ListField(child=serializers.CharField(), required=False)
    digest_enabled = serializers.BooleanField(required=False)


def notification_data(item: Notification) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "portal": item.portal,
        "kind": item.kind,
        "title": item.title,
        "body": item.body_masked,
        "link_url": item.link_url,
        "course_id": item.course_ref or None,
        "task_id": item.task_ref or None,
        "scope": item.scope,
        "read_at": item.read_at,
        "created_at": item.created_at,
        "row_version": item.row_version,
    }


def preference_data(item: Preference) -> dict[str, object]:
    return {
        "portal": item.portal,
        "channels": item.channels,
        "muted_kinds": item.muted_kinds,
        "digest_enabled": item.digest_enabled,
        "row_version": item.row_version,
    }

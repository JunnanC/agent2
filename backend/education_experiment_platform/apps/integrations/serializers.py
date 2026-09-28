from rest_framework import serializers

from .models import (
    APIClient,
    APIClientGrant,
    OIDCIdentity,
    OIDCProvider,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookEndpoint,
)


class P13IntegrationResponseSerializer(serializers.Serializer):
    """Named placeholder for envelope responses represented by view helpers."""

    pass


class TokenSerializer(serializers.Serializer):
    client_id = serializers.CharField()
    client_secret = serializers.CharField()
    scope = serializers.CharField(required=False, allow_blank=True)


class OIDCProviderSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=160)
    issuer = serializers.URLField(max_length=500)
    client_id = serializers.CharField(max_length=255)
    client_secret = serializers.CharField(write_only=True, required=False)
    claim_mapping = serializers.JSONField(required=False)
    allowed_portals = serializers.ListField(
        child=serializers.ChoiceField(choices=("USER", "TEACHING", "PLATFORM")), required=False
    )
    status = serializers.ChoiceField(choices=("ACTIVE", "DISABLED"), required=False)


class APIClientSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    scopes = serializers.ListField(child=serializers.CharField(max_length=128), required=False)
    rate_limit_per_minute = serializers.IntegerField(min_value=1, required=False)
    status = serializers.ChoiceField(choices=("ACTIVE", "REVOKED"), required=False)


class APIClientGrantSerializer(serializers.Serializer):
    scope = serializers.CharField(max_length=128)
    resource_scope = serializers.ChoiceField(choices=("PLATFORM", "COURSE"), default="PLATFORM")
    course_id = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=("ACTIVE", "REVOKED"), required=False)


class WebhookSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    endpoint_url = serializers.URLField(max_length=500)
    event_allowlist = serializers.ListField(
        child=serializers.CharField(max_length=128), required=False
    )
    course_id = serializers.CharField(required=False, allow_blank=True)
    secret = serializers.CharField(required=False, write_only=True)


def provider_data(item: OIDCProvider) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "key": item.key,
        "name": item.name,
        "issuer": item.issuer,
        "client_id": item.client_id,
        "claim_mapping": item.claim_mapping,
        "allowed_portals": item.allowed_portals,
        "status": item.status,
        "row_version": item.row_version,
    }


def identity_data(item: OIDCIdentity) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "provider_id": item.provider.public_id,
        "account_id": item.account.public_id,
        "subject_hint": item.subject_hint,
        "status": item.status,
        "last_authenticated_at": item.last_authenticated_at,
        "row_version": item.row_version,
    }


def client_data(item: APIClient) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "client_id": item.client_id,
        "name": item.name,
        "allowed_scopes": item.allowed_scopes,
        "rate_limit_per_minute": item.rate_limit_per_minute,
        "status": item.status,
        "row_version": item.row_version,
    }


def grant_data(item: APIClientGrant) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "client_id": item.client.public_id,
        "scope": item.scope,
        "resource_scope": item.resource_scope,
        "course_id": item.course.public_id if item.course else None,
        "status": item.status,
        "row_version": item.row_version,
    }


def webhook_data(item: WebhookEndpoint) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "name": item.name,
        "event_allowlist": item.event_allowlist,
        "course_id": item.course.public_id if item.course else None,
        "status": item.status,
        "row_version": item.row_version,
    }


def delivery_data(item: WebhookDelivery) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "endpoint_id": item.endpoint.public_id,
        "event_id": item.event_id,
        "event_type": item.event_type,
        "status": item.status,
        "attempt_count": item.attempt_count,
        "last_status_code": item.last_status_code,
        "last_response_masked": item.last_response_masked,
        "next_retry_at": item.next_retry_at,
        "delivered_at": item.delivered_at,
        "row_version": item.row_version,
    }


def attempt_data(item: WebhookDeliveryAttempt) -> dict[str, object]:
    return {
        "attempt_no": item.attempt_no,
        "request_digest": item.request_digest,
        "response_status": item.response_status,
        "response_summary_masked": item.response_summary_masked,
        "result": item.result,
        "started_at": item.started_at,
        "finished_at": item.finished_at,
    }

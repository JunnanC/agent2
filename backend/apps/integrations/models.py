from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import AppendOnlyModel, VersionedModel
from apps.courses.models import Course


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26, default=new_ulid, unique=True, editable=False, db_collation="ascii_bin"
    )


class OIDCProvider(VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        DISABLED = "DISABLED"

    public_id = public_id_field()
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=160)
    issuer = models.URLField(max_length=500)
    issuer_hash = models.CharField(max_length=64, unique=True, db_collation="ascii_bin")
    client_id = models.CharField(max_length=255)
    client_secret_ciphertext = models.TextField()
    previous_client_secret_ciphertext = models.TextField(blank=True, default="")
    previous_secret_expires_at = models.DateTimeField(null=True, blank=True)
    claim_mapping = models.JSONField(default=dict)
    allowed_portals = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        db_table = "integrations_oidc_provider"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "DISABLED")),
                name="integrations_oidc_status_ck",
            )
        ]


class OIDCIdentity(VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        UNLINKED = "UNLINKED"

    public_id = public_id_field()
    provider = models.ForeignKey(OIDCProvider, on_delete=models.PROTECT, related_name="identities")
    account = models.ForeignKey(User, on_delete=models.PROTECT, related_name="oidc_identities")
    issuer_hash = models.CharField(max_length=64, db_collation="ascii_bin")
    subject_hash = models.CharField(max_length=64, db_collation="ascii_bin")
    subject_hint = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    last_authenticated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "integrations_oidc_identity"
        constraints = [
            models.UniqueConstraint(
                fields=("issuer_hash", "subject_hash"), name="integrations_oidc_subject_uniq"
            ),
            models.UniqueConstraint(
                fields=("provider", "account"), name="integrations_oidc_account_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "UNLINKED")),
                name="integrations_oidc_identity_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("provider", "status"), name="integrations_oidc_provider_idx")
        ]


class APIClient(VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        REVOKED = "REVOKED"

    public_id = public_id_field()
    client_id = models.CharField(max_length=64, unique=True, db_collation="ascii_bin")
    name = models.CharField(max_length=160)
    secret_hash = models.CharField(max_length=128, db_collation="ascii_bin")
    previous_secret_hash = models.CharField(
        max_length=128, blank=True, default="", db_collation="ascii_bin"
    )
    previous_secret_expires_at = models.DateTimeField(null=True, blank=True)
    allowed_scopes = models.JSONField(default=list)
    rate_limit_per_minute = models.PositiveIntegerField(default=60)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_api_clients"
    )

    class Meta:
        db_table = "integrations_api_client"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "REVOKED")),
                name="integrations_client_status_ck",
            )
        ]


class APIClientGrant(VersionedModel):
    public_id = public_id_field()
    client = models.ForeignKey(APIClient, on_delete=models.PROTECT, related_name="grants")
    scope = models.CharField(max_length=128)
    resource_scope = models.CharField(max_length=128, default="PLATFORM")
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, null=True, blank=True, related_name="integration_grants"
    )
    status = models.CharField(max_length=16, default="ACTIVE")

    class Meta:
        db_table = "integrations_api_client_grant"
        constraints = [
            models.UniqueConstraint(
                fields=("client", "scope", "resource_scope"), name="integrations_client_grant_uniq"
            )
        ]


class WebhookEndpoint(VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        DISABLED = "DISABLED"

    public_id = public_id_field()
    name = models.CharField(max_length=160)
    endpoint_url_ciphertext = models.TextField()
    endpoint_url_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    secret_ciphertext = models.TextField()
    previous_secret_ciphertext = models.TextField(blank=True, default="")
    previous_secret_expires_at = models.DateTimeField(null=True, blank=True)
    event_allowlist = models.JSONField(default=list)
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, null=True, blank=True, related_name="webhook_endpoints"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_webhook_endpoints"
    )

    class Meta:
        db_table = "integrations_webhook_endpoint"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "DISABLED")),
                name="integrations_webhook_status_ck",
            )
        ]


class WebhookDelivery(VersionedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        IN_FLIGHT = "IN_FLIGHT"
        RETRY = "RETRY"
        DELIVERED = "DELIVERED"
        DEAD = "DEAD"

    public_id = public_id_field()
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.PROTECT, related_name="deliveries"
    )
    event_id = models.CharField(max_length=64, db_collation="ascii_bin")
    event_type = models.CharField(max_length=128)
    body_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    last_response_masked = models.TextField(blank=True, default="")
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "integrations_webhook_delivery"
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "event_id"), name="integrations_webhook_delivery_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("PENDING", "IN_FLIGHT", "RETRY", "DELIVERED", "DEAD")
                ),
                name="integrations_webhook_delivery_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "next_retry_at"), name="int_webhook_schedule_idx")
        ]


class WebhookDeliveryAttempt(AppendOnlyModel):
    delivery = models.ForeignKey(WebhookDelivery, on_delete=models.PROTECT, related_name="attempts")
    attempt_no = models.PositiveIntegerField()
    request_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_summary_masked = models.TextField(blank=True, default="")
    result = models.CharField(max_length=32)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "integrations_webhook_delivery_attempt"
        constraints = [
            models.UniqueConstraint(
                fields=("delivery", "attempt_no"), name="integrations_webhook_attempt_uniq"
            )
        ]

from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import VersionedModel


def default_channels() -> dict[str, bool]:
    return {"in_app": True}


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class Notification(VersionedModel):
    public_id = public_id_field()
    account = models.ForeignKey(User, on_delete=models.PROTECT, related_name="notifications")
    portal = models.CharField(max_length=16)
    kind = models.CharField(max_length=64)
    title = models.CharField(max_length=180)
    body_masked = models.TextField()
    link_url = models.CharField(max_length=500, blank=True, default="")
    course_ref = models.CharField(max_length=128, blank=True, default="")
    task_ref = models.CharField(max_length=128, blank=True, default="")
    scope = models.JSONField(default=dict)
    source_event_id = models.CharField(max_length=64)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications_notification"
        constraints = [
            models.UniqueConstraint(
                fields=("account", "portal", "source_event_id", "kind"),
                name="notifications_event_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(portal__in=("USER", "TEACHING", "PLATFORM")),
                name="notifications_portal_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("account", "portal", "read_at", "created_at"),
                name="notifications_inbox_idx",
            ),
            models.Index(fields=("course_ref", "created_at"), name="notifications_course_idx"),
        ]


class Preference(VersionedModel):
    account = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="notification_preferences"
    )
    portal = models.CharField(max_length=16)
    channels = models.JSONField(default=default_channels)
    muted_kinds = models.JSONField(default=list)
    digest_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "notifications_preference"
        constraints = [
            models.UniqueConstraint(
                fields=("account", "portal"), name="notifications_pref_scope_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(portal__in=("USER", "TEACHING", "PLATFORM")),
                name="notifications_pref_portal_ck",
            ),
        ]

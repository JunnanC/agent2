from django.db.models import QuerySet

from apps.accounts.models import User

from .models import Notification, Preference


def visible_notifications(*, actor: User, portal: str) -> QuerySet[Notification]:
    return Notification.objects.filter(account=actor, portal=portal).order_by("-created_at")


def preference_for(*, actor: User, portal: str) -> Preference | None:
    return Preference.objects.filter(account=actor, portal=portal).first()

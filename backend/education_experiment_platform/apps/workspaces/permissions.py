import hashlib
import hmac

from django.conf import settings
from django.utils import timezone

from .errors import (
    WorkspacePortalDenied,
    WorkspaceSessionExpired,
    WorkspaceSessionInvalid,
    WorkspaceSessionRevoked,
    WorkspaceTaskMismatch,
)
from .models import WorkspaceSession


def token_digest(token: str) -> str:
    key = str(getattr(settings, "WORKSPACE_TOKEN_HMAC_KEY", settings.SECRET_KEY)).encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def require_workspace_session(
    *,
    session: WorkspaceSession,
    token: str,
    task_id: str | None = None,
    capability: str | None = None,
) -> WorkspaceSession:
    if not token:
        raise WorkspaceSessionInvalid()
    if not hmac.compare_digest(session.token_hash, token_digest(token)):
        raise WorkspaceSessionInvalid()
    if session.portal != "USER":
        raise WorkspacePortalDenied()
    if task_id and session.task.public_id != task_id:
        raise WorkspaceTaskMismatch()
    now = timezone.now()
    if session.status == WorkspaceSession.Status.REVOKED:
        raise WorkspaceSessionRevoked()
    if session.status == WorkspaceSession.Status.EXPIRED or session.expires_at <= now:
        raise WorkspaceSessionExpired()
    if session.task.status in {"COMPLETED", "CANCELLED", "EXPIRED", "ARCHIVING", "DESTROYING"}:
        raise WorkspaceSessionRevoked()
    if session.instance.status != "READY":
        raise WorkspaceSessionInvalid(detail={"instance_status": session.instance.status})
    if capability and not bool((session.capabilities or {}).get(capability)):
        raise WorkspaceTaskMismatch(detail={"capability": capability})
    return session


def mark_expired_if_needed(session: WorkspaceSession) -> WorkspaceSession:
    if session.status == WorkspaceSession.Status.ACTIVE and session.expires_at <= timezone.now():
        from apps.core.concurrency import compare_and_swap

        return compare_and_swap(
            WorkspaceSession,
            pk=session.pk,
            expected_version=session.row_version,
            changes={
                "status": WorkspaceSession.Status.EXPIRED,
                "active_marker": None,
                "revoked_at": timezone.now(),
                "revoke_reason": "ticket expired",
            },
        )
    return session

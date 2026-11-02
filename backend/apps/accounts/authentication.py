import time

from django.conf import settings
from django.http import HttpRequest
from rest_framework.authentication import BaseAuthentication, CSRFCheck

from apps.core.audit import append_audit, hash_client_ip

from .errors import (
    AccountStateConflict,
    CsrfFailed,
    PlatformAccessRequired,
    SessionExpired,
    SessionPortalMismatch,
    TeacherQualificationRequired,
)
from .metrics import PORTAL_ACCESS_DENIED_TOTAL
from .models import PlatformAdminAssignment, TeacherQualification, User
from .security import client_ip

SESSION_USER_ID = "account_user_id"
SESSION_PORTAL = "account_portal"
SESSION_AUTH_TIME = "account_auth_time"
SESSION_SECURITY_VERSION = "account_security_version"
SESSION_ABSOLUTE_EXPIRES_AT = "account_absolute_expires_at"

PORTAL_IDLE_SECONDS = {
    "USER": lambda: settings.USER_SESSION_IDLE_SECONDS,
    "TEACHING": lambda: settings.TEACHING_SESSION_IDLE_SECONDS,
    "PLATFORM": lambda: settings.PLATFORM_SESSION_IDLE_SECONDS,
}
PORTAL_ABSOLUTE_SECONDS = {
    "USER": lambda: settings.USER_SESSION_ABSOLUTE_SECONDS,
    "TEACHING": lambda: settings.TEACHING_SESSION_ABSOLUTE_SECONDS,
    "PLATFORM": lambda: settings.PLATFORM_SESSION_ABSOLUTE_SECONDS,
}


def enforce_csrf(request: HttpRequest) -> None:
    check = CSRFCheck(lambda _request: None)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise CsrfFailed(detail={"reason": "csrf_cookie_or_token_invalid"})


def establish_portal_session(request: HttpRequest, *, user: User, portal: str) -> None:
    request.session.cycle_key()
    now = int(time.time())
    request.session[SESSION_USER_ID] = user.pk
    request.session[SESSION_PORTAL] = portal
    request.session[SESSION_AUTH_TIME] = now
    request.session[SESSION_SECURITY_VERSION] = user.security_version
    request.session[SESSION_ABSOLUTE_EXPIRES_AT] = now + PORTAL_ABSOLUTE_SECONDS[portal]()
    request.session.set_expiry(PORTAL_IDLE_SECONDS[portal]())


def refresh_current_session_security(request: HttpRequest, *, user: User) -> None:
    request.session.cycle_key()
    request.session[SESSION_SECURITY_VERSION] = user.security_version
    request.session[SESSION_AUTH_TIME] = int(time.time())


def portal_admission(user: User, portal: str) -> None:
    if user.account_status != User.AccountStatus.ACTIVE:
        raise AccountStateConflict(detail={"status": user.account_status})
    if (
        portal == "TEACHING"
        and not TeacherQualification.objects.filter(
            user=user, status=TeacherQualification.Status.ACTIVE
        ).exists()
    ):
        raise TeacherQualificationRequired()
    if (
        portal == "PLATFORM"
        and not PlatformAdminAssignment.objects.filter(
            user=user, status=PlatformAdminAssignment.Status.ACTIVE
        ).exists()
    ):
        raise PlatformAccessRequired()


def _audit_session_denial(request: HttpRequest, user: User | None, code: str) -> None:
    append_audit(
        actor_ref=user.public_id if user else "anonymous",
        actor_portal=str(getattr(request, "portal", "")),
        actor_context={},
        action="auth.session.denied",
        target_type="session",
        target_ref="current",
        result="DENIED",
        error_code=code,
        client_ip_hash=hash_client_ip(client_ip(request), salt=settings.AUDIT_IP_HASH_SALT),
        user_agent_summary=request.headers.get("User-Agent", ""),
        trace_id=str(getattr(request, "trace_id", "")),
    )


class PortalSessionAuthentication(BaseAuthentication):
    def authenticate(self, request: HttpRequest) -> tuple[User, None] | None:
        user_id = request.session.get(SESSION_USER_ID)
        if not user_id:
            return None
        portal = str(getattr(request, "portal", ""))
        session_portal = request.session.get(SESSION_PORTAL)
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            request.session.flush()
            raise SessionExpired() from None
        if session_portal != portal:
            _audit_session_denial(request, user, "SESSION_PORTAL_MISMATCH")
            PORTAL_ACCESS_DENIED_TOTAL.labels(portal=portal, reason="portal_mismatch").inc()
            request.session.flush()
            raise SessionPortalMismatch()
        if request.session.get(SESSION_SECURITY_VERSION) != user.security_version or int(
            request.session.get(SESSION_ABSOLUTE_EXPIRES_AT, 0)
        ) <= int(time.time()):
            _audit_session_denial(request, user, "SESSION_EXPIRED")
            PORTAL_ACCESS_DENIED_TOTAL.labels(portal=portal, reason="expired").inc()
            request.session.flush()
            raise SessionExpired()
        try:
            portal_admission(user, portal)
        except (AccountStateConflict, TeacherQualificationRequired, PlatformAccessRequired) as exc:
            _audit_session_denial(request, user, exc.code)
            PORTAL_ACCESS_DENIED_TOTAL.labels(portal=portal, reason=exc.code.lower()).inc()
            request.session.flush()
            raise
        enforce_csrf(request)
        return user, None

    def authenticate_header(self, request: HttpRequest) -> str:
        return "Session"

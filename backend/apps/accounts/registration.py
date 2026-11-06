import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .errors import AccountAlreadyExists, EmailServiceUnavailable, InvalidVerificationToken
from .models import PendingRegistration, TeacherQualification, TeacherQualificationEvent, User
from .security import normalize_email, normalize_username, validate_new_password
from .services import ActorContext, _record_qualification_change, create_user_with_password_hash


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def start_registration(
    *,
    email: str,
    username: str,
    display_name: str,
    password: str,
    role: str,
    verification_url: str,
) -> None:
    validate_new_password(password)
    email = normalize_email(email)
    username = normalize_username(username)
    if User.objects.filter(email=email).exists():
        return
    if User.objects.filter(username=username).exists():
        raise AccountAlreadyExists(detail={"username": "already_used"})
    mailer = settings.MAILERS["default"]
    if (
        mailer["BACKEND"] == "django.core.mail.backends.smtp.EmailBackend"
        and not mailer["OPTIONS"]["host"]
    ):
        raise EmailServiceUnavailable()
    token = secrets.token_urlsafe(32)
    PendingRegistration.objects.update_or_create(
        email=email,
        defaults={
            "username": username,
            "display_name": display_name.strip(),
            "password_hash": make_password(password),
            "role": role,
            "token_hash": _digest(token),
            "expires_at": timezone.now() + timedelta(hours=24),
        },
    )
    link = f"{verification_url}?{urlencode({'token': token})}"
    try:
        send_mail(
            "验证您的平台注册邮箱",
            f"请在 24 小时内打开以下链接完成注册：\n{link}",
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
    except Exception as exc:
        raise EmailServiceUnavailable() from exc


@transaction.atomic
def complete_registration(*, token: str, role: str, context: ActorContext) -> User:
    pending = (
        PendingRegistration.objects.select_for_update().filter(token_hash=_digest(token)).first()
    )
    if pending is None or pending.expires_at <= timezone.now() or pending.role != role:
        raise InvalidVerificationToken()
    user = create_user_with_password_hash(
        email=pending.email,
        username=pending.username,
        display_name=pending.display_name,
        password_hash=pending.password_hash,
        context=context,
        registration_role=role,
    )
    if role == User.RegistrationRole.TEACHER:
        qualification = TeacherQualification.objects.create(
            user=user,
            status=TeacherQualification.Status.PENDING,
            granted_at=None,
            reason="Self registration pending review",
        )
        TeacherQualificationEvent.objects.create(
            qualification=qualification,
            from_status="",
            to_status=TeacherQualification.Status.PENDING,
            actor=user,
            reason=qualification.reason,
            trace_id=context.trace_id,
        )
        _record_qualification_change(qualification, "", context)
    pending.delete()
    return user

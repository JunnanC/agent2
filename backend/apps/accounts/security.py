import hashlib
import hmac

from django.conf import settings
from django.http import HttpRequest
from redis import Redis

from .errors import AuthenticationServiceUnavailable, PasswordInvalid, RateLimited


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def normalize_username(value: str) -> str:
    return value.strip().casefold()


def validate_new_password(password: str) -> None:
    if len(password) < 12 or password.isdigit() or password.isalpha():
        raise PasswordInvalid(detail={"password": "至少 12 位，且同时包含字母和非字母字符"})


def identity_number_digest(value: str) -> str:
    normalized = "".join(value.split()).upper()
    return hmac.new(
        settings.IDENTITY_HMAC_KEY.encode(),
        normalized.encode(),
        hashlib.sha256,
    ).hexdigest()


def mask_identity_number(value: str) -> str:
    normalized = "".join(value.split())
    if len(normalized) <= 4:
        return "*" * len(normalized)
    return f"{normalized[:2]}{'*' * (len(normalized) - 4)}{normalized[-2:]}"


def client_ip(request: HttpRequest) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",", maxsplit=1)[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def opaque_login_subject(identifier: str, ip_address: str, portal: str) -> str:
    value = f"{portal}:{normalize_email(identifier)}:{ip_address}"
    return hmac.new(
        settings.AUDIT_IP_HASH_SALT.encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest()


def _redis_client() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


def check_login_rate_limit(
    *, identifier: str, ip_address: str, portal: str, client: Redis | None = None
) -> str:
    subject = opaque_login_subject(identifier, ip_address, portal)
    key = f"auth:login:{subject}"
    redis_client = client or _redis_client()
    try:
        pipeline = redis_client.pipeline(transaction=True)
        pipeline.incr(key)
        pipeline.expire(key, settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        count, _ = pipeline.execute()
    except Exception as exc:
        raise AuthenticationServiceUnavailable() from exc
    if int(count) > settings.LOGIN_RATE_LIMIT_ATTEMPTS:
        raise RateLimited(detail={"retry_after": settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS})
    return key


def clear_login_rate_limit(key: str, *, client: Redis | None = None) -> None:
    redis_client = client or _redis_client()
    try:
        redis_client.delete(key)
    except Exception:
        return

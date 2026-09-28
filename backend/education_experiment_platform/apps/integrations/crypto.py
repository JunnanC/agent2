import hashlib
import hmac
import secrets

from django.conf import settings
from django.core import signing


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def seal(value: str) -> str:
    return signing.dumps(value, salt="integration-secret", compress=True)


def unseal(value: str) -> str:
    return str(signing.loads(value, salt="integration-secret", max_age=None))


def generate_secret(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def sign_webhook(*, secret: str, delivery_id: str, timestamp: int, body: bytes) -> str:
    body_digest = hashlib.sha256(body).hexdigest()
    message = f"{delivery_id}.{timestamp}.{body_digest}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def integration_signing_key() -> str:
    return str(getattr(settings, "IDENTITY_HMAC_KEY", settings.SECRET_KEY))

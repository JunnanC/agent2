"""Instance-scoped credentials for the workspace runtime boundary."""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings


def workspace_upstream_token(
    *,
    instance_id: str,
    task_id: str,
    spec_digest: str,
    key: str | bytes | None = None,
) -> str:
    """Derive the token accepted by exactly one managed workspace router."""

    instance = str(instance_id).strip()
    task = str(task_id).strip()
    digest = str(spec_digest).strip()
    if not instance or not task or not digest:
        return ""
    secret = key
    if secret is None:
        secret = getattr(settings, "WORKSPACE_UPSTREAM_HMAC_KEY", settings.SECRET_KEY)
    secret_bytes = secret.encode() if isinstance(secret, str) else bytes(secret)
    return hmac.new(
        secret_bytes,
        f"{instance}|{task}|{digest}".encode(),
        hashlib.sha256,
    ).hexdigest()

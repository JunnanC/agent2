import time
from dataclasses import dataclass

from django.conf import settings
from redis import Redis
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.accounts.errors import AuthenticationServiceUnavailable, RateLimited

from .metrics import INTEGRATION_RATE_LIMIT_REJECTIONS
from .models import APIClient
from .services import verify_access_token


@dataclass(frozen=True)
class IntegrationPrincipal:
    client: APIClient
    scopes: tuple[str, ...]
    auth_context: str = "INTEGRATION"

    @property
    def public_id(self) -> str:
        return self.client.public_id


class IntegrationTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):  # type: ignore[no-untyped-def]
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise AuthenticationFailed("Bearer token required")
        try:
            payload = verify_access_token(header[7:].strip())
            client = APIClient.objects.get(
                client_id=str(payload["client_id"]), status=APIClient.Status.ACTIVE
            )
        except Exception as exc:
            raise AuthenticationFailed("Access token invalid") from exc
        enforce_rate_limit(client)
        return IntegrationPrincipal(
            client=client, scopes=tuple(str(item) for item in payload.get("scopes", []))
        ), None


def enforce_rate_limit(client: APIClient, *, redis_client: Redis | None = None) -> None:
    """Apply a client-scoped fixed-window limit without exposing client IDs in metrics."""
    window = int(time.time() // 60)
    key = f"integration:rate:{client.client_id}:{window}"
    redis = redis_client or Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        pipeline = redis.pipeline(transaction=True)
        pipeline.incr(key)
        pipeline.expire(key, 70)
        count, _ = pipeline.execute()
    except Exception as exc:
        raise AuthenticationServiceUnavailable() from exc
    if int(count) > client.rate_limit_per_minute:
        INTEGRATION_RATE_LIMIT_REJECTIONS.inc()
        raise RateLimited(detail={"retry_after": 60 - int(time.time() % 60)})

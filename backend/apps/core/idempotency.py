import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction

from .concurrency import compare_and_swap
from .errors import IdempotencyKeyRequired, IdempotencyKeyReused, IdempotencyRequestInProgress
from .models import IdempotencyRecord

REPLAYABLE_HEADERS = {"etag", "location", "content-type"}


@dataclass(frozen=True)
class PrincipalScope:
    actor_ref: str
    auth_context: str
    portal: str = ""


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: Any
    headers: Mapping[str, str]
    replayed: bool = False


def request_digest(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _headers_for_storage(headers: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() in REPLAYABLE_HEADERS}


def execute_idempotent(
    *,
    principal: PrincipalScope,
    method: str,
    endpoint: str,
    key: str | None,
    payload: Any,
    operation: Callable[[], StoredResponse],
) -> StoredResponse:
    if not key or len(key) > 128:
        raise IdempotencyKeyRequired(detail={"header": "Idempotency-Key"})
    digest = request_digest(payload)
    lookup = {
        "actor_ref": principal.actor_ref,
        "auth_context": principal.auth_context,
        "portal": principal.portal,
        "method": method.upper(),
        "endpoint": endpoint,
        "idempotency_key": key,
    }

    with transaction.atomic():
        record = IdempotencyRecord.objects.select_for_update().filter(**lookup).first()
        if record is not None:
            if record.request_digest != digest:
                raise IdempotencyKeyReused(detail={"idempotency_key": key})
            if record.status == IdempotencyRecord.Status.COMPLETED:
                return StoredResponse(
                    status_code=record.response_status or 200,
                    body=record.response_body,
                    headers=record.response_headers,
                    replayed=True,
                )
            raise IdempotencyRequestInProgress(detail={"idempotency_key": key})

        try:
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    **lookup,
                    request_digest=digest,
                    status=IdempotencyRecord.Status.PROCESSING,
                )
        except IntegrityError:
            record = IdempotencyRecord.objects.select_for_update().get(**lookup)
            if record.request_digest != digest:
                raise IdempotencyKeyReused(detail={"idempotency_key": key}) from None
            if record.status == IdempotencyRecord.Status.COMPLETED:
                return StoredResponse(
                    status_code=record.response_status or 200,
                    body=record.response_body,
                    headers=record.response_headers,
                    replayed=True,
                )
            raise IdempotencyRequestInProgress(detail={"idempotency_key": key}) from None
        response = operation()
        normalized_body = json.loads(
            json.dumps(
                response.body,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                cls=DjangoJSONEncoder,
            )
        )
        compare_and_swap(
            IdempotencyRecord,
            pk=record.pk,
            expected_version=record.row_version,
            changes={
                "status": IdempotencyRecord.Status.COMPLETED,
                "response_status": response.status_code,
                "response_headers": _headers_for_storage(response.headers),
                "response_body": normalized_body,
            },
        )
        return StoredResponse(
            status_code=response.status_code,
            body=normalized_body,
            headers=response.headers,
        )

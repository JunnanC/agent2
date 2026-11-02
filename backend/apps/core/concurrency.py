import re
from typing import Any

from django.db import models
from django.db.models.functions import Now

from .errors import InvalidPrecondition, PreconditionRequired, ResourceNotFound, RowVersionConflict

ETAG_RE = re.compile(r'^(?:W/)?"(?P<version>[1-9][0-9]*)"$')


def etag_for_version(row_version: int) -> str:
    return f'"{row_version}"'


def parse_if_match(value: str | None) -> int:
    if not value:
        raise PreconditionRequired()
    match = ETAG_RE.fullmatch(value.strip())
    if not match:
        raise InvalidPrecondition(detail={"header": "If-Match"})
    return int(match.group("version"))


def compare_and_swap(
    model: type[models.Model],
    *,
    pk: object,
    expected_version: int,
    changes: dict[str, Any],
) -> models.Model:
    if "row_version" in changes or "created_at" in changes:
        raise ValueError("CAS changes cannot overwrite managed version fields")
    updated = model.objects.filter(pk=pk, row_version=expected_version).update(
        **changes,
        row_version=models.F("row_version") + 1,
        updated_at=Now(),
    )
    if updated == 0:
        if not model.objects.filter(pk=pk).exists():
            raise ResourceNotFound()
        raise RowVersionConflict(detail={"expected_row_version": expected_version})
    return model.objects.get(pk=pk)

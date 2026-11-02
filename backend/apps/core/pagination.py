from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from .errors import CoreError


class PaginationError(CoreError):
    code = "PAGINATION_INVALID"
    message = "分页参数无效"
    status_code = 400


@dataclass(frozen=True)
class PageSpec:
    page: int = 1
    page_size: int = 20

    @classmethod
    def parse(cls, page: object = 1, page_size: object = 20) -> PageSpec:
        try:
            result = cls(page=int(str(page)), page_size=int(str(page_size)))
        except (TypeError, ValueError) as exc:
            raise PaginationError() from exc
        if result.page < 1 or not 1 <= result.page_size <= 100:
            raise PaginationError(detail={"page": result.page, "page_size": result.page_size})
        return result

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def encode_cursor(values: dict[str, Any]) -> str:
    raw = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PaginationError(detail={"cursor": "invalid"}) from exc
    if not isinstance(value, dict):
        raise PaginationError(detail={"cursor": "invalid"})
    return value

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "setcookie",
    "csrf",
    "csrftoken",
    "password",
    "passwd",
    "secret",
    "token",
    "accesstoken",
    "refreshtoken",
    "workspacetoken",
    "signedurl",
    "credential",
    "idcard",
    "identitynumber",
    "clientip",
    "ipaddress",
    "remoteaddr",
}
SENSITIVE_VALUE = re.compile(
    r"(?i)(authorization|cookie|csrf|password|passwd|secret|(?:access|refresh|workspace)?token|"
    r"signed[_ -]?url|credential|id[_ -]?card|identity[_ -]?number|client[_ -]?ip)"
    r"([=:]\s*)([^\s&,;]+)"
)


def _normalized_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _normalized_key(key) in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SENSITIVE_VALUE.sub(r"\1\2[REDACTED]", value)
    return value

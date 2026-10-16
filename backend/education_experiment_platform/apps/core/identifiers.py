import hashlib
import secrets
import time

CROCKFORD_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """Return a 26-character ULID without adding a runtime dependency."""
    timestamp_ms = time.time_ns() // 1_000_000
    value = ((timestamp_ms & ((1 << 48) - 1)) << 80) | secrets.randbits(80)
    encoded = ["0"] * 26
    for index in range(25, -1, -1):
        encoded[index] = CROCKFORD_BASE32[value & 31]
        value >>= 5
    return "".join(encoded)


def normalize_trace_id(value: object) -> str:
    """Keep internal trace identifiers within the 32-character storage contract."""

    trace_id = str(value or "")
    if len(trace_id) <= 32:
        return trace_id
    return hashlib.sha256(trace_id.encode("utf-8")).hexdigest()[:32]

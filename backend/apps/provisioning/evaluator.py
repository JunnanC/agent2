"""Small, deterministic output evaluator used by runtime adapters."""

import math
import re
from collections.abc import Mapping
from typing import TypedDict


class PublicReport(TypedDict):
    status: str
    cases: int
    results: list[dict[str, object]]


_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def _numeric_token(value: str) -> float | None:
    if not _NUMBER.fullmatch(value):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def outputs_match(
    actual: str,
    expected: str,
    *,
    comparator: str = "token",
    absolute_tolerance: float = 1e-6,
    relative_tolerance: float = 1e-6,
) -> bool:
    actual_tokens, expected_tokens = actual.split(), expected.split()
    if len(actual_tokens) != len(expected_tokens):
        return False
    for left, right in zip(actual_tokens, expected_tokens, strict=True):
        if comparator != "numeric":
            if left != right:
                return False
            continue
        left_number, right_number = _numeric_token(left), _numeric_token(right)
        if left_number is None or right_number is None:
            non_finite = {"nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
            if left.lower() in non_finite or right.lower() in non_finite:
                return False
            if left != right:
                return False
        elif abs(left_number - right_number) > max(
            absolute_tolerance, relative_tolerance * abs(right_number)
        ):
            return False
    return True


def public_report(report: Mapping[str, object], public_count: int = 3) -> PublicReport:
    """Keep only safe case metadata; hidden inputs/outputs/logs never cross the boundary."""
    results = report.get("results", [])
    safe: list[dict[str, object]] = []
    if isinstance(results, list):
        for index, item in enumerate(results):
            if not isinstance(item, Mapping):
                continue
            if index < public_count:
                safe.append({
                    "status": str(item.get("status", "FAILED")),
                    "stdout": str(item.get("stdout", ""))[:65536],
                    "stderr": str(item.get("stderr", ""))[:65536],
                    "returncode": item.get("returncode"),
                    **{key: str(item[key])[:65536] for key in ("input", "expected") if key in item},
                })
            else:
                safe.append({"status": str(item.get("status", "FAILED")), "hidden": True})
    return {"status": str(report.get("status", "FAILED")), "cases": len(safe), "results": safe}

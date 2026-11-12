"""Explicit image-service double; no student execution or implicit driver fallback."""

import hashlib
from typing import Any


class ImageRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def resolve_image(self, *, registry: str, repository: str, tag: str) -> dict[str, Any]:
        self.calls.append(("IMAGE_RESOLVE", "call"))
        return {
            "digest": "sha256:"
            + hashlib.sha256(f"{registry}/{repository}:{tag}".encode()).hexdigest(),
            "logs": "image resolved",
        }

    def validate_image(self, *, digest: str) -> dict[str, Any]:
        return {"valid": True, "scan_status": "PENDING", "digest": digest}

    def build_image(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("IMAGE_BUILD", "call"))
        return self.resolve_image(
            registry=kwargs["registry"], repository=kwargs["repository"], tag=kwargs["tag"]
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "HEALTHY",
            "node_count": 1,
            "capacity_cpu_millicores": 4000,
            "available_cpu_millicores": 4000,
            "capacity_memory_mb": 8192,
            "available_memory_mb": 8192,
        }


_runtime = ImageRuntime()


def image_runtime() -> ImageRuntime:
    return _runtime


def reset_image_runtime() -> None:
    _runtime.calls.clear()

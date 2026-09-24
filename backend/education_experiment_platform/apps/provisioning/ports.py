from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class RuntimeSpec:
    task_id: str
    course_id: str
    student_id: str
    runtime_type: str
    image_digest: str
    resource_profile_id: str
    cpu_millicores: int
    memory_mb: int
    disk_gb: int
    network_policy: Mapping[str, object] = field(default_factory=dict)
    workspace_capabilities: Mapping[str, object] = field(default_factory=dict)
    trace_id: str = ""


@dataclass(frozen=True)
class RuntimeResult:
    external_id: str
    endpoint: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeInventoryItem:
    external_id: str
    status: str
    metadata: Mapping[str, object] = field(default_factory=dict)


class RuntimeAdapter(Protocol):
    def preflight(self, spec: RuntimeSpec) -> RuntimeResult: ...

    def prepare_image(self, spec: RuntimeSpec) -> None: ...

    def attach_network(self, spec: RuntimeSpec) -> None: ...

    def create(self, spec: RuntimeSpec, idempotency_key: str) -> RuntimeResult: ...

    def status(self, external_id: str) -> str: ...

    def endpoint(self, external_id: str) -> str: ...

    def snapshot(self, external_id: str) -> str: ...

    def destroy(self, external_id: str, idempotency_key: str) -> None: ...

    def inventory(self) -> list[RuntimeInventoryItem]: ...

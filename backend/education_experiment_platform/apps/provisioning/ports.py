from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class RuntimeSpec:
    task_id: str
    course_id: str
    student_id: str
    runtime_type: str
    image_registry: str
    image_repository: str
    image_digest: str
    resource_profile_id: str
    cpu_millicores: int
    memory_mb: int
    disk_gb: int
    network_policy: Mapping[str, object] = field(default_factory=dict)
    workspace_capabilities: Mapping[str, object] = field(default_factory=dict)
    ttl_seconds: int = 0
    workspace_port: int = 8080
    healthcheck_path: str = "/healthz"
    trace_id: str = ""
    instance_public_id: str = ""

    @property
    def image_ref(self) -> str:
        registry = self.image_registry.rstrip("/")
        repository = self.image_repository.lstrip("/")
        return f"{registry}/{repository}@{self.image_digest}"


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


@dataclass(frozen=True)
class RuntimeExecutionResult:
    """Normalized result returned by a runtime's one-shot judge execution."""

    status: str = "PASSED"
    stdout: str = ""
    stderr: str = ""
    test_report: Mapping[str, object] = field(default_factory=dict)
    error_code: str = ""
    result_summary: str = ""
    duration_ms: int | None = None


@dataclass(frozen=True)
class RuntimeWorkspaceArtifact:
    content: bytes
    size: int
    digest: str
    media_type: str
    relative_path: str


class RuntimeAdapter(Protocol):
    def preflight(self, spec: RuntimeSpec) -> RuntimeResult: ...

    def prepare_image(self, spec: RuntimeSpec) -> None: ...

    def attach_network(self, spec: RuntimeSpec) -> None: ...

    def create(self, spec: RuntimeSpec, idempotency_key: str) -> RuntimeResult: ...

    def status(self, external_id: str) -> str: ...

    def endpoint(self, external_id: str) -> str: ...

    def snapshot(self, external_id: str) -> str: ...

    def capture_workspace(
        self,
        *,
        external_id: str,
        relative_path: str,
        max_bytes: int,
    ) -> RuntimeWorkspaceArtifact: ...

    def restore_workspace(
        self,
        *,
        external_id: str,
        relative_path: str,
        content: bytes,
        expected_digest: str,
    ) -> None: ...

    def destroy(self, external_id: str, idempotency_key: str) -> None: ...

    def inventory(self) -> list[RuntimeInventoryItem]: ...

    def health(self) -> Mapping[str, object]: ...

    def coordinate_capacity(
        self, spec: RuntimeSpec, *, idempotency_key: str, replicas: int
    ) -> RuntimeResult: ...

    def release_capacity(self, *, idempotency_key: str) -> None: ...

    def destroy_judge(self, judge_id: str, idempotency_key: str = "") -> None: ...

    def inventory_resources(self) -> list[RuntimeInventoryItem]: ...

    def destroy_resource(self, external_id: str, idempotency_key: str = "") -> None: ...

    def execute(
        self,
        *,
        spec: RuntimeSpec,
        command: list[str],
        source: bytes,
        timeout_seconds: int,
        memory_mb: int,
        cpu_millicores: int,
        network_mode: str,
    ) -> RuntimeExecutionResult: ...

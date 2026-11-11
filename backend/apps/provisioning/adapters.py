import hashlib
import hmac
import io
import json
import mimetypes
import re
import tarfile
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from apps.core.project_archive import ProjectArchiveError, bundle, unpack
from apps.core.workspace_tokens import workspace_upstream_token

from .evaluator import outputs_match
from .ports import (
    RuntimeAdapter,
    RuntimeExecutionResult,
    RuntimeInventoryItem,
    RuntimeResult,
    RuntimeSpec,
    RuntimeWorkspaceArtifact,
)

MANAGED_LABEL = "edu.platform.managed"
KIND_LABEL = "edu.platform.kind"
RUNTIME_KIND = "student-runtime"
CAPACITY_KIND = "shared-prewarm"
NAME_PATTERN = re.compile(r"[^a-z0-9-]+")
IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_REGISTRY_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?(?::[0-9]{1,5})?$"
)
IMAGE_REPOSITORY_COMPONENT_PATTERN = re.compile(
    r"^[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*$"
)


class RuntimeAdapterFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = True,
        partial: bool = False,
        result: RuntimeResult | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.partial = partial
        self.result = result


def _config_int(value: object) -> int:
    if isinstance(value, (str, bytes, bytearray, int, float)):
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False) from exc
    raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False)


def _config_float(value: object) -> float:
    if isinstance(value, (str, bytes, bytearray, int, float)):
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False) from exc
    raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False)


def _validated_workspace_path(relative_path: str) -> str:
    """Accept the legacy main file or the fixed project root."""

    value = str(relative_path).replace("\\", "/")
    if value not in {"main.py", "."}:
        raise RuntimeAdapterFailure("WORKSPACE_PATH_INVALID", retryable=False)
    return value


def _workspace_artifact(content: bytes, relative_path: str) -> RuntimeWorkspaceArtifact:
    return RuntimeWorkspaceArtifact(
        content=content,
        size=len(content),
        digest=hashlib.sha256(content).hexdigest(),
        media_type=mimetypes.guess_type(relative_path)[0] or "text/plain",
        relative_path=relative_path,
    )


def _workspace_archive(relative_path: str, content: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo(relative_path)
        info.size = len(content)
        info.mode = 0o600
        info.uid = 10001
        info.gid = 10001
        info.uname = "workspace"
        info.gname = "workspace"
        archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _bounded_archive_bytes(stream: Any, max_bytes: int) -> bytes:
    if max_bytes < 1:
        raise RuntimeAdapterFailure("WORKSPACE_FILE_TOO_LARGE", retryable=False)
    buffer = io.BytesIO()
    chunks = [stream] if isinstance(stream, (bytes, bytearray)) else stream
    for chunk in chunks:
        data = bytes(chunk)
        if len(data) > max_bytes - buffer.tell():
            raise RuntimeAdapterFailure("WORKSPACE_FILE_TOO_LARGE", retryable=False)
        buffer.write(data)
    return buffer.getvalue()


def _extract_workspace_archive(archive_bytes: bytes, relative_path: str, max_bytes: int) -> bytes:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
            members = archive.getmembers()
            for item in members:
                if item.name not in {relative_path, f"./{relative_path}"}:
                    raise RuntimeAdapterFailure("WORKSPACE_FILE_INVALID", retryable=False)
                if not item.isreg() or item.issym() or item.islnk():
                    raise RuntimeAdapterFailure("WORKSPACE_FILE_INVALID", retryable=False)
            matching = [
                item for item in members if item.name in {relative_path, f"./{relative_path}"}
            ]
            if len(matching) != 1:
                raise RuntimeAdapterFailure("WORKSPACE_FILE_MISSING", retryable=False)
            member = matching[0]
            if member.size > max_bytes:
                raise RuntimeAdapterFailure("WORKSPACE_FILE_TOO_LARGE", retryable=False)
            handle = archive.extractfile(member)
            if handle is None:
                raise RuntimeAdapterFailure("WORKSPACE_FILE_MISSING", retryable=False)
            content = handle.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise RuntimeAdapterFailure("WORKSPACE_FILE_TOO_LARGE", retryable=False)
            return content
    except RuntimeAdapterFailure:
        raise
    except (tarfile.TarError, OSError) as exc:
        raise RuntimeAdapterFailure("WORKSPACE_FILE_INVALID", retryable=False) from exc


class FakeRuntimeFailure(RuntimeAdapterFailure):
    pass


def _consume_docker_stream(stream: Any, error_code: str) -> list[Any]:
    if isinstance(stream, (bytes, bytearray, Mapping)):
        stream = (stream,)
    consumed: list[Any] = []
    try:
        for item in stream or ():
            if isinstance(item, (bytes, bytearray)):
                with suppress(UnicodeDecodeError, json.JSONDecodeError):
                    item = json.loads(bytes(item).decode())
            if isinstance(item, Mapping) and (item.get("error") or item.get("errorDetail")):
                raise RuntimeAdapterFailure(error_code)
            consumed.append(item)
    except RuntimeAdapterFailure:
        raise
    except Exception as exc:
        raise RuntimeAdapterFailure(error_code) from exc
    return consumed


def _docker_registry_image_result(output: Any, client: Any, reference: str) -> Mapping[str, Any]:
    digest = ""
    for item in output or ():
        if isinstance(item, Mapping):
            aux = item.get("aux")
            candidates = [
                aux.get("Digest") if isinstance(aux, Mapping) else None,
                item.get("digest"),
            ]
            for candidate in candidates:
                value = str(candidate or "")
                if re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                    digest = value
                    break
            if digest:
                break
    if not digest:
        try:
            inspected = client.inspect_image(reference)
        except Exception:
            raise RuntimeAdapterFailure(
                "RUNTIME_IMAGE_DIGEST_UNAVAILABLE", retryable=False
            ) from None
        repo_digests = inspected.get("RepoDigests") or [] if isinstance(inspected, Mapping) else []
        for repo_digest in repo_digests:
            candidate = str(repo_digest).rsplit("@", 1)[-1]
            if re.fullmatch(r"sha256:[0-9a-f]{64}", candidate):
                digest = candidate
                break
    if not digest:
        raise RuntimeAdapterFailure("RUNTIME_IMAGE_DIGEST_UNAVAILABLE", retryable=False)
    return {"digest": digest, "logs": "docker image operation completed"}


def _docker_image_result(output: Any, client: Any, reference: str) -> Mapping[str, Any]:
    digest = ""
    for item in output or ():
        if isinstance(item, (bytes, bytearray)):
            try:
                item = json.loads(bytes(item).decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        if isinstance(item, Mapping):
            aux = item.get("aux")
            if isinstance(aux, Mapping):
                digest = str(aux.get("ID") or aux.get("Digest") or digest)
            digest = str(item.get("digest") or digest)
    inspected = client.inspect_image(reference)
    repo_digests = inspected.get("RepoDigests") or [] if isinstance(inspected, Mapping) else []
    for repo_digest in repo_digests:
        candidate = str(repo_digest).rsplit("@", 1)[-1]
        if re.fullmatch(r"sha256:[0-9a-f]{64}", candidate):
            digest = candidate
            break
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        candidate = str(inspected.get("Id", "")) if isinstance(inspected, Mapping) else ""
        digest = candidate if re.fullmatch(r"sha256:[0-9a-f]{64}", candidate) else ""
    if not digest:
        raise RuntimeAdapterFailure("RUNTIME_IMAGE_DIGEST_UNAVAILABLE", retryable=False)
    return {"digest": digest, "logs": "docker image operation completed"}


@dataclass
class FakeRuntimeAdapter:
    """Deterministic local adapter used by unit tests and non-Swarm Compose runs."""

    failures: dict[str, str] = field(default_factory=dict)
    timeouts: set[str] = field(default_factory=set)
    partial_success: set[str] = field(default_factory=set)
    instances: dict[str, RuntimeResult] = field(default_factory=dict)
    capacities: dict[str, RuntimeResult] = field(default_factory=dict)
    judge_instances: dict[str, RuntimeResult] = field(default_factory=dict)
    volumes: dict[str, RuntimeResult] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def capabilities(self) -> Mapping[str, bool]:
        return {
            "image_build": True,
            "real_container": False,
            "resource_limits": True,
            "workspace_access": False,
        }

    def build_image(
        self,
        *,
        registry: str,
        repository: str,
        tag: str,
        context: Mapping[str, Any],
        build_args: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        failure = self._step("IMAGE_BUILD")
        if failure:
            raise failure
        material = json.dumps(
            {
                "registry": registry,
                "repository": repository,
                "tag": tag,
                "context": {key: value for key, value in context.items() if key != "archive"},
                "build_args": sorted(build_args),
            },
            sort_keys=True,
            default=str,
        ).encode()
        return {
            "digest": "sha256:" + hashlib.sha256(material).hexdigest(),
            "logs": "fake image build complete",
        }

    def resolve_image(self, *, registry: str, repository: str, tag: str) -> Mapping[str, Any]:
        failure = self._step("IMAGE_RESOLVE")
        if failure:
            raise failure
        digest = hashlib.sha256(f"{registry}/{repository}:{tag}".encode()).hexdigest()
        return {"digest": "sha256:" + digest, "logs": "fake image resolve complete"}

    def validate_image(self, *, digest: str) -> Mapping[str, Any]:
        failure = self._step("IMAGE_VALIDATE")
        if failure:
            raise failure
        return {"valid": True, "scan_status": "PENDING", "digest": digest}

    def _step(self, stage: str) -> FakeRuntimeFailure | None:
        self.calls.append((stage, "call"))
        if stage in self.timeouts:
            raise TimeoutError(f"FAKE_{stage}_TIMEOUT")
        if stage in self.failures:
            failure = FakeRuntimeFailure(
                self.failures[stage], partial=stage in self.partial_success
            )
            if failure.partial:
                return failure
            raise failure
        return None

    def preflight(self, spec: RuntimeSpec) -> RuntimeResult:
        failure = self._step("QUOTA_CHECK")
        if failure:
            raise failure
        return RuntimeResult(external_id=f"fake-preflight:{spec.task_id}")

    def prepare_image(self, spec: RuntimeSpec) -> None:
        failure = self._step("IMAGE_PREPARE")
        if failure:
            raise failure

    def attach_network(self, spec: RuntimeSpec) -> None:
        failure = self._step("NETWORK_ATTACH")
        if failure:
            raise failure

    def create(self, spec: RuntimeSpec, idempotency_key: str) -> RuntimeResult:
        failure = self._step("CREATE")
        existing = self.instances.get(idempotency_key)
        if existing is not None:
            if failure:
                raise failure
            return existing
        result = RuntimeResult(
            external_id=f"fake-instance:{spec.task_id}:{idempotency_key[:12]}",
            endpoint=f"http://tasks.fake-runtime:{spec.workspace_port}",
            metadata={
                "driver": "FAKE",
                "idempotency_key": idempotency_key,
                "managed": True,
                "service_name": "fake-runtime",
                "task_id": spec.task_id,
                "course_id": spec.course_id,
                "student_id": spec.student_id,
                "instance_id": spec.instance_public_id,
                "config_ref": "runtime/fake",
                "workspace_port": spec.workspace_port,
            },
        )
        self.instances[idempotency_key] = result
        if failure:
            raise FakeRuntimeFailure(failure.code, partial=True, result=result)
        return result

    def status(self, external_id: str) -> str:
        failure = self._step("BOOT_PROBE")
        if failure:
            raise failure
        return (
            "READY"
            if any(item.external_id == external_id for item in self.instances.values())
            else "ABSENT"
        )

    def endpoint(self, external_id: str) -> str:
        failure = self._step("WORKSPACE_READY")
        if failure:
            raise failure
        for result in self.instances.values():
            if result.external_id == external_id:
                return result.endpoint
        return ""

    def snapshot(self, external_id: str) -> str:
        failure = self._step("OPTIONAL_SNAPSHOT")
        if failure:
            raise failure
        return f"fake-snapshot:{external_id}"

    def capture_workspace(
        self, *, external_id: str, relative_path: str, max_bytes: int
    ) -> RuntimeWorkspaceArtifact:
        del external_id, relative_path, max_bytes
        raise RuntimeAdapterFailure("WORKSPACE_CAPTURE_UNSUPPORTED", retryable=False)

    def restore_workspace(
        self,
        *,
        external_id: str,
        relative_path: str,
        content: bytes,
        expected_digest: str,
    ) -> None:
        del external_id, relative_path, content, expected_digest
        raise RuntimeAdapterFailure("WORKSPACE_CAPTURE_UNSUPPORTED", retryable=False)

    def destroy(self, external_id: str, idempotency_key: str) -> None:
        del idempotency_key
        failure = self._step("DESTROY_RUNTIME")
        if failure:
            raise failure
        for key, result in list(self.instances.items()):
            if result.external_id == external_id:
                self.instances.pop(key, None)
                break

    def inventory(self) -> list[RuntimeInventoryItem]:
        return [
            RuntimeInventoryItem(
                external_id=item.external_id,
                status="READY",
                metadata=dict(item.metadata),
            )
            for item in self.instances.values()
        ]

    def health(self) -> Mapping[str, object]:
        return {
            "status": "HEALTHY",
            "node_count": 1,
            "capacity_cpu_millicores": 0,
            "available_cpu_millicores": 0,
            "capacity_memory_mb": 0,
            "available_memory_mb": 0,
            "driver": "FAKE",
        }

    def coordinate_capacity(
        self, spec: RuntimeSpec, *, idempotency_key: str, replicas: int
    ) -> RuntimeResult:
        del spec, replicas
        result = self.capacities.get(idempotency_key)
        if result is None:
            result = RuntimeResult(
                external_id=f"fake-capacity:{self._id(idempotency_key)}",
                metadata={"driver": "FAKE", "managed": True, "kind": CAPACITY_KIND},
            )
            self.capacities[idempotency_key] = result
        return result

    def release_capacity(self, *, idempotency_key: str) -> None:
        self.capacities.pop(idempotency_key, None)

    def destroy_judge(self, judge_id: str, idempotency_key: str = "") -> None:
        """Idempotently release a one-shot judge resource.

        The fake adapter keeps this hook even though it does not create a real
        container.  That makes cleanup part of the adapter contract and prevents
        callers from having to special-case FakeRuntime.
        """

        del idempotency_key
        self.judge_instances.pop(judge_id, None)

    def inventory_resources(self) -> list[RuntimeInventoryItem]:
        """Return managed transient resources known by the adapter."""

        return [
            RuntimeInventoryItem(
                external_id=item.external_id,
                status="READY",
                metadata=dict(item.metadata),
            )
            for item in self.judge_instances.values()
        ]

    def destroy_resource(self, external_id: str, idempotency_key: str = "") -> None:
        del idempotency_key
        self.judge_instances.pop(external_id, None)
        self.volumes.pop(external_id, None)

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
        tests: bytes = b"",
        execution_plan: Mapping[str, list[str]] | None = None,
    ) -> RuntimeExecutionResult:
        """Return deterministic execution results for legacy simulated workspaces.

        FakeRuntime intentionally does not interpret student source.  The execution
        service still records the same immutable run shape used by Docker adapters.
        """

        del spec, command, source, timeout_seconds, memory_mb, cpu_millicores, network_mode, tests
        del execution_plan
        return RuntimeExecutionResult(
            status="PASSED",
            stdout="FakeRuntime execution accepted",
            result_summary="PASSED by FakeRuntime",
            duration_ms=0,
        )

    @staticmethod
    def _id(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:16]


@dataclass
class DockerLocalProtocolStub(FakeRuntimeAdapter):
    """In-memory DOCKER_LOCAL contract stub used before the real local adapter.

    This deliberately has no Docker client or socket dependency.  It exercises the
    same lifecycle surface as the future local adapter so provisioning orchestration
    can be verified without creating containers.  The stub remains opt-in through
    the runtime driver resolver and marks every result as a protocol stub.
    """

    config_ref: str = "runtime/local-algorithm"

    def _result(self, spec: RuntimeSpec, idempotency_key: str) -> RuntimeResult:
        return RuntimeResult(
            external_id=f"docker-local-stub:{spec.task_id}:{self._id(idempotency_key)[:12]}",
            endpoint=f"http://tasks.docker-local-stub:{spec.workspace_port}",
            metadata={
                "driver": "DOCKER_LOCAL",
                "config_ref": self.config_ref,
                "idempotency_key": idempotency_key,
                "managed": True,
                "protocol_stub": True,
                "service_name": "docker-local-stub",
                "task_id": spec.task_id,
                "course_id": spec.course_id,
                "student_id": spec.student_id,
                "instance_id": spec.instance_public_id,
                "workspace_port": spec.workspace_port,
            },
        )

    def preflight(self, spec: RuntimeSpec) -> RuntimeResult:
        failure = self._step("QUOTA_CHECK")
        if failure:
            raise failure
        if spec.runtime_type != "CONTAINER":
            raise RuntimeAdapterFailure("RUNTIME_TYPE_UNSUPPORTED", retryable=False)
        if not self.config_ref.strip():
            raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False)
        return RuntimeResult(
            external_id=f"docker-local-preflight:{spec.task_id}",
            metadata={
                "driver": "DOCKER_LOCAL",
                "config_ref": self.config_ref,
                "protocol_stub": True,
            },
        )

    def create(self, spec: RuntimeSpec, idempotency_key: str) -> RuntimeResult:
        failure = self._step("CREATE")
        existing = self.instances.get(idempotency_key)
        if existing is not None:
            if failure:
                raise failure
            return existing
        result = self._result(spec, idempotency_key)
        self.instances[idempotency_key] = result
        self.volumes.setdefault(
            f"volume:{result.external_id}",
            RuntimeResult(
                external_id=f"volume:{result.external_id}",
                metadata={
                    "driver": "DOCKER_LOCAL",
                    "managed": True,
                    "kind": "volume",
                    "config_ref": self.config_ref,
                    "task_id": spec.task_id,
                    "expires_at": int(time.time()) + max(spec.ttl_seconds, 0),
                },
            ),
        )
        if failure:
            raise FakeRuntimeFailure(failure.code, partial=True, result=result)
        return result

    def health(self) -> Mapping[str, object]:
        return {
            "status": "HEALTHY",
            "node_count": 1,
            "capacity_cpu_millicores": 0,
            "available_cpu_millicores": 0,
            "capacity_memory_mb": 0,
            "available_memory_mb": 0,
            "driver": "DOCKER_LOCAL",
            "config_ref": self.config_ref,
            "protocol_stub": True,
        }

    def coordinate_capacity(
        self, spec: RuntimeSpec, *, idempotency_key: str, replicas: int
    ) -> RuntimeResult:
        del spec
        if replicas < 0:
            raise RuntimeAdapterFailure("RUNTIME_CAPACITY_INVALID", retryable=False)
        result = self.capacities.get(idempotency_key)
        if result is None:
            result = RuntimeResult(
                external_id=f"docker-local-capacity:{self._id(idempotency_key)}",
                metadata={
                    "driver": "DOCKER_LOCAL",
                    "config_ref": self.config_ref,
                    "managed": True,
                    "kind": CAPACITY_KIND,
                    "protocol_stub": True,
                    "replicas": replicas,
                },
            )
            self.capacities[idempotency_key] = result
        return result

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
        tests: bytes = b"",
        execution_plan: Mapping[str, list[str]] | None = None,
    ) -> RuntimeExecutionResult:
        del spec, command, source, timeout_seconds, memory_mb, cpu_millicores, network_mode, tests
        del execution_plan
        return RuntimeExecutionResult(
            status="PASSED",
            stdout="DockerLocal protocol stub execution accepted",
            result_summary="PASSED by DockerLocal protocol stub",
            duration_ms=0,
        )

    def execute_judge(
        self,
        *,
        spec: RuntimeSpec,
        command: list[str],
        source: bytes,
        tests: bytes,
        timeout_seconds: int,
        memory_mb: int,
        cpu_millicores: int,
        network_mode: str,
        judge_id: str,
        execution_plan: Mapping[str, list[str]] | None = None,
    ) -> RuntimeExecutionResult:
        """Exercise the judge protocol without creating a Docker container."""

        del tests
        self.judge_instances[judge_id] = RuntimeResult(
            external_id=judge_id,
            metadata={
                "driver": "DOCKER_LOCAL",
                "managed": True,
                "kind": "judge",
                "config_ref": self.config_ref,
                "judge_id": judge_id,
                "task_id": spec.task_id,
            },
        )
        return self.execute(
            spec=spec,
            command=command,
            source=source,
            timeout_seconds=timeout_seconds,
            memory_mb=memory_mb,
            cpu_millicores=cpu_millicores,
            network_mode=network_mode,
        )

    def destroy_judge(self, judge_id: str, idempotency_key: str = "") -> None:
        """Destroy the protocol-stub judge and tolerate an already absent one."""

        del idempotency_key
        self.judge_instances.pop(judge_id, None)

    def inventory_resources(self) -> list[RuntimeInventoryItem]:
        return [
            RuntimeInventoryItem(
                external_id=item.external_id,
                status="READY",
                metadata=dict(item.metadata),
            )
            for item in [*self.judge_instances.values(), *self.volumes.values()]
        ]

    def destroy_resource(self, external_id: str, idempotency_key: str = "") -> None:
        del idempotency_key
        self.judge_instances.pop(external_id, None)
        self.volumes.pop(external_id, None)


class DockerLocalAdapter(DockerLocalProtocolStub):
    """Single-host Docker Engine adapter for local experiment workspaces.

    The protocol stub above remains intentionally in-memory for unit tests.  This
    adapter uses only the runtime worker's Docker socket and creates ordinary
    containers, which makes the local path useful without requiring Swarm.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        config: Mapping[str, object] | None = None,
        config_ref: str = "runtime/local-docker",
    ) -> None:
        self.config = dict(config or {})
        self.config_ref = config_ref.strip()
        if not self.config_ref:
            raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False)
        self.client = client or self._build_client()
        self._secret_volumes: dict[str, str] = {}

    def _build_client(self) -> Any:
        try:
            import docker
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise RuntimeAdapterFailure("RUNTIME_CLIENT_UNAVAILABLE", retryable=False) from exc
        try:
            return docker.APIClient(
                base_url=str(self.config.get("base_url") or settings.LOCAL_DOCKER_HOST),
                version=str(self.config.get("api_version") or "auto"),
                timeout=_config_int(self.config.get("request_timeout", 30)),
            )
        except RuntimeAdapterFailure:
            raise
        except Exception as exc:
            # APIClient negotiates the Docker API during construction.  Keep socket,
            # permission, and version-negotiation failures inside the adapter
            # contract so read-only inventory callers can degrade safely.
            raise RuntimeAdapterFailure("RUNTIME_CLIENT_UNAVAILABLE") from exc

    def capabilities(self) -> Mapping[str, bool]:
        return {
            "image_build": True,
            "real_container": True,
            "resource_limits": True,
            "workspace_access": True,
        }

    def _call(self, code: str, operation: Any) -> Any:
        try:
            return operation()
        except RuntimeAdapterFailure:
            raise
        except Exception as exc:
            raise RuntimeAdapterFailure(code) from exc

    @staticmethod
    def _safe_name(value: str, *, prefix: str = "experimental-platform-lab") -> str:
        normalized = NAME_PATTERN.sub("-", value.casefold()).strip("-") or "runtime"
        digest = hashlib.sha256(value.encode()).hexdigest()[:12]
        return f"{prefix}-{normalized[:8]}-{digest}"

    @staticmethod
    def _idempotency_digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _spec_digest(spec: RuntimeSpec) -> str:
        payload = {
            "task_id": spec.task_id,
            "course_id": spec.course_id,
            "student_id": spec.student_id,
            "image_ref": spec.image_ref,
            "cpu_millicores": spec.cpu_millicores,
            "cpu_limit_millicores": spec.cpu_limit_millicores,
            "memory_mb": spec.memory_mb,
            "memory_limit_mb": spec.memory_limit_mb,
            "disk_gb": spec.disk_gb,
            "network_policy": dict(spec.network_policy),
            "workspace_capabilities": dict(spec.workspace_capabilities),
            "workspace_port": spec.workspace_port,
            "healthcheck_path": spec.healthcheck_path,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _image_ref(self, spec: RuntimeSpec) -> str:
        configured = str(self.config.get("image") or "").strip()
        if configured:
            return configured
        if spec.image_registry == "local":
            return f"{spec.image_repository}@{spec.image_digest}"
        return spec.image_ref

    @staticmethod
    def _resource_limits(spec: RuntimeSpec) -> tuple[int, int]:
        cpu_limit = spec.cpu_limit_millicores or spec.cpu_millicores
        memory_limit = spec.memory_limit_mb or spec.memory_mb
        if (
            spec.cpu_millicores < 1
            or cpu_limit < 1
            or spec.cpu_millicores > cpu_limit
            or spec.memory_mb < 1
            or memory_limit < 1
            or spec.memory_mb > memory_limit
        ):
            raise RuntimeAdapterFailure("RUNTIME_RESOURCE_LIMIT_INVALID", retryable=False)
        return cpu_limit, memory_limit

    def _validate_image_and_resources(self, spec: RuntimeSpec) -> None:
        registry = spec.image_registry.strip().lower()
        repository = spec.image_repository.strip().lower()
        if (
            registry != spec.image_registry
            or repository != spec.image_repository
            or not IMAGE_REGISTRY_PATTERN.fullmatch(registry)
            or not repository
            or len(repository) > 255
            or not all(
                IMAGE_REPOSITORY_COMPONENT_PATTERN.fullmatch(component)
                for component in repository.split("/")
            )
            or not IMAGE_DIGEST_PATTERN.fullmatch(spec.image_digest)
        ):
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_REFERENCE_INVALID", retryable=False)
        self._resource_limits(spec)

    def _owns_managed_resource(self, labels: Mapping[str, object], kind: str) -> bool:
        config_ref = str(labels.get("edu.platform.config_ref") or "")
        return (
            labels.get(MANAGED_LABEL) == "true"
            and labels.get(KIND_LABEL) == kind
            and config_ref == self.config_ref
        )

    def _network_name(self) -> str:
        return str(
            self.config.get("runtime_network") or getattr(settings, "LOCAL_RUNTIME_NETWORK", "")
        )

    def _network_id(self) -> str:
        name = self._network_name()
        if not name:
            raise RuntimeAdapterFailure("RUNTIME_NETWORK_INVALID", retryable=False)
        networks = self._call(
            "RUNTIME_NETWORK_QUERY_FAILED", lambda: self.client.networks(names=[name])
        )
        if networks:
            return str(networks[0]["Id"])
        response = self._call(
            "RUNTIME_NETWORK_CREATE_FAILED",
            lambda: self.client.create_network(
                name=name,
                driver="bridge",
                internal=True,
                attachable=True,
                labels={MANAGED_LABEL: "true", KIND_LABEL: "runtime-gateway-network"},
            ),
        )
        return str(response["Id"])

    def _labels(
        self,
        *,
        kind: str,
        spec: RuntimeSpec,
        idempotency_key: str = "",
        external_id: str = "",
        expires_at: int | None = None,
    ) -> dict[str, str]:
        labels = {
            MANAGED_LABEL: "true",
            KIND_LABEL: kind,
            "edu.platform.task": spec.task_id,
            "edu.platform.course": spec.course_id,
            "edu.platform.student": spec.student_id,
            "edu.platform.trace": spec.trace_id,
            "edu.platform.spec_digest": self._spec_digest(spec),
            "edu.platform.instance": spec.instance_public_id,
            "edu.platform.config_ref": self.config_ref,
        }
        if idempotency_key:
            labels["edu.platform.idempotency"] = self._idempotency_digest(idempotency_key)
        if external_id:
            labels["edu.platform.judge"] = external_id
        if expires_at is not None:
            labels["edu.platform.expires_at"] = str(expires_at)
        return labels

    def _host_config(
        self,
        *,
        memory_mb: int,
        cpu_millicores: int,
        network_mode: str | None = None,
        volume_name: str = "",
        volume_target: str = "/workspace",
        volume_mode: str = "rw",
        read_only: bool = True,
        extra_binds: Mapping[str, Mapping[str, str]] | None = None,
    ) -> Any:
        if memory_mb < 1 or cpu_millicores < 1:
            raise RuntimeAdapterFailure("RUNTIME_RESOURCE_LIMIT_INVALID", retryable=False)
        binds: dict[str, Mapping[str, str]] = {}
        if volume_name:
            binds[volume_name] = {"bind": volume_target, "mode": volume_mode}
        if extra_binds:
            binds.update(extra_binds)
        kwargs: dict[str, object] = {
            "mem_limit": f"{memory_mb}m",
            "nano_cpus": cpu_millicores * 1_000_000,
            "pids_limit": _config_int(self.config.get("pids_limit", 256)),
            "read_only": read_only,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "tmpfs": {"/tmp": "rw,noexec,nosuid,size=128m,uid=10001,gid=10001"},
        }
        if network_mode:
            kwargs["network_mode"] = network_mode
        if binds:
            kwargs["binds"] = binds
        return self._call(
            "RUNTIME_HOST_CONFIG_FAILED",
            lambda: self.client.create_host_config(**kwargs),
        )

    def _healthcheck(self, spec: RuntimeSpec) -> dict[str, object]:
        del spec
        return {
            "Test": ["CMD", "/usr/local/bin/workspace-router", "healthcheck"],
            "Interval": 5_000_000_000,
            "Timeout": 2_000_000_000,
            "Retries": 12,
            "StartPeriod": 3_000_000_000,
        }

    def _container_result(self, container: Mapping[str, object]) -> RuntimeResult:
        config_value = container.get("Config")
        config = config_value if isinstance(config_value, Mapping) else {}
        labels_value = container.get("Labels") or config.get("Labels")
        labels = dict(labels_value) if isinstance(labels_value, Mapping) else {}
        container_id = str(container.get("Id") or container.get("ID") or "")
        name = str(container.get("Name") or "").lstrip("/")
        port = int(labels.get("edu.platform.workspace_port", 8080))
        return RuntimeResult(
            external_id=container_id,
            endpoint=f"http://tasks.{name}:{port}",
            metadata={
                "driver": "DOCKER_LOCAL",
                "config_ref": self.config_ref,
                "container_name": name,
                "service_name": name,
                "task_id": str(labels.get("edu.platform.task", "")),
                "course_id": str(labels.get("edu.platform.course", "")),
                "student_id": str(labels.get("edu.platform.student", "")),
                "instance_id": str(labels.get("edu.platform.instance", "")),
                "workspace_port": port,
                "managed": labels.get(MANAGED_LABEL) == "true",
                "kind": labels.get(KIND_LABEL, ""),
                "spec_digest": str(labels.get("edu.platform.spec_digest", "")),
                "expires_at": int(labels["edu.platform.expires_at"])
                if labels.get("edu.platform.expires_at", "").isdigit()
                else 0,
            },
        )

    def preflight(self, spec: RuntimeSpec) -> RuntimeResult:
        if spec.runtime_type != "CONTAINER":
            raise RuntimeAdapterFailure("RUNTIME_TYPE_UNSUPPORTED", retryable=False)
        self._validate_image_and_resources(spec)
        if not 1 <= spec.workspace_port <= 65535 or not spec.healthcheck_path.startswith("/"):
            raise RuntimeAdapterFailure("RUNTIME_WORKSPACE_CONTRACT_INVALID", retryable=False)
        if spec.network_policy.get("mode", "DENY_ALL") != "DENY_ALL":
            raise RuntimeAdapterFailure("RUNTIME_NETWORK_POLICY_INVALID", retryable=False)
        self._call("RUNTIME_UNAVAILABLE", self.client.ping)
        self._network_id()
        return RuntimeResult(
            external_id=f"local-preflight:{spec.task_id}",
            metadata={"driver": "DOCKER_LOCAL", "config_ref": self.config_ref},
        )

    def prepare_image(self, spec: RuntimeSpec) -> None:
        image = self._image_ref(spec)
        self._call("RUNTIME_IMAGE_QUERY_FAILED", lambda: self.client.inspect_image(image))

    def build_image(
        self,
        *,
        registry: str,
        repository: str,
        tag: str,
        context: Mapping[str, Any],
        build_args: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        archive = context.get("archive")
        if not isinstance(archive, (bytes, bytearray)):
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_CONTEXT_UNAVAILABLE", retryable=False)
        reference = f"{registry.rstrip('/')}/{repository.lstrip('/')}:{tag}"
        output = self._call(
            "RUNTIME_IMAGE_BUILD_FAILED",
            lambda: _consume_docker_stream(
                self.client.build(
                    fileobj=io.BytesIO(bytes(archive)),
                    custom_context=True,
                    encoding="gzip",
                    tag=reference,
                    buildargs=dict(build_args),
                    rm=True,
                    decode=True,
                ),
                "RUNTIME_IMAGE_BUILD_FAILED",
            ),
        )
        return _docker_image_result(output, self.client, reference)

    def resolve_image(self, *, registry: str, repository: str, tag: str) -> Mapping[str, Any]:
        reference = f"{registry.rstrip('/')}/{repository.lstrip('/')}:{tag}"

        def _pull_and_resolve() -> Mapping[str, Any]:
            output = _consume_docker_stream(
                self.client.pull(reference), "RUNTIME_IMAGE_PULL_FAILED"
            )
            return _docker_image_result(output, self.client, reference)

        return self._call("RUNTIME_IMAGE_PULL_FAILED", _pull_and_resolve)

    def validate_image(self, *, digest: str) -> Mapping[str, Any]:
        inspected = self._call(
            "RUNTIME_IMAGE_VALIDATE_FAILED", lambda: self.client.inspect_image(digest)
        )
        if not inspected:
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_VALIDATE_FAILED", retryable=False)
        return {"valid": True, "digest": digest, "scan_status": "PENDING"}

    def attach_network(self, spec: RuntimeSpec) -> None:
        self._network_id()

    def _existing(self, idempotency_key: str) -> list[dict[str, object]]:
        return list(
            self._call(
                "RUNTIME_CONTAINER_QUERY_FAILED",
                lambda: self.client.containers(
                    all=True,
                    filters={
                        "label": [
                            f"{MANAGED_LABEL}=true",
                            f"{KIND_LABEL}={RUNTIME_KIND}",
                            f"edu.platform.config_ref={self.config_ref}",
                            f"edu.platform.idempotency={self._idempotency_digest(idempotency_key)}",
                        ]
                    },
                ),
            )
        )

    def _volume_name(self, spec: RuntimeSpec, idempotency_key: str) -> str:
        return self._safe_name(
            f"{spec.task_id}:{idempotency_key}", prefix="experimental-platform-workspace"
        )

    def _secret_volume_name(self, spec: RuntimeSpec, idempotency_key: str) -> str:
        return self._safe_name(
            f"{spec.task_id}:{idempotency_key}", prefix="experimental-platform-secret"
        )

    def _stage_workspace_secret(
        self,
        *,
        spec: RuntimeSpec,
        idempotency_key: str,
        secret_volume: str,
        token: str,
    ) -> None:
        labels = {
            MANAGED_LABEL: "true",
            KIND_LABEL: "workspace-secret",
            "edu.platform.task": spec.task_id,
            "edu.platform.student": spec.student_id,
            "edu.platform.config_ref": self.config_ref,
        }
        self._call(
            "RUNTIME_SECRET_VOLUME_CREATE_FAILED",
            lambda: self.client.create_volume(name=secret_volume, driver="local", labels=labels),
        )
        stage_id = ""
        try:
            host_config = self._host_config(
                memory_mb=min(max(spec.memory_mb, 16), 64),
                cpu_millicores=min(max(spec.cpu_millicores, 10), 100),
                volume_name=secret_volume,
                volume_target="/run/secrets",
                read_only=False,
                network_mode="none",
            )
            staged = self._call(
                "RUNTIME_SECRET_STAGE_CREATE_FAILED",
                lambda: self.client.create_container(
                    image=self._image_ref(spec),
                    name=self._safe_name(
                        f"{spec.task_id}:{idempotency_key}",
                        prefix="experimental-platform-secret-stage",
                    ),
                    command=["python", "-c", "import time; time.sleep(30)"],
                    labels={**labels, "edu.platform.secret_stage": "true"},
                    host_config=host_config,
                ),
            )
            stage_id = str(staged["Id"])
            self._call("RUNTIME_SECRET_STAGE_START_FAILED", lambda: self.client.start(stage_id))
            archive = _workspace_archive("workspace_upstream_token", token.encode("ascii"))
            self._call(
                "RUNTIME_SECRET_UPLOAD_FAILED",
                lambda: self.client.put_archive(stage_id, "/run/secrets", archive),
            )
        finally:
            if stage_id:
                with suppress(Exception):
                    self.client.remove_container(stage_id, force=True, v=False)

    def _create_workspace(self, spec: RuntimeSpec, idempotency_key: str) -> RuntimeResult:
        expires_at = int(time.time()) + max(spec.ttl_seconds, 0)
        container_name = self._safe_name(spec.task_id)
        volume_name = self._volume_name(spec, idempotency_key)
        secret_volume_name = self._secret_volume_name(spec, idempotency_key)
        container_id = ""
        upstream_token = workspace_upstream_token(
            instance_id=spec.instance_public_id or idempotency_key,
            task_id=spec.task_id,
            spec_digest=self._spec_digest(spec),
        )
        if not upstream_token:
            raise RuntimeAdapterFailure("RUNTIME_UPSTREAM_TOKEN_UNAVAILABLE", retryable=False)
        cpu_limit, memory_limit = self._resource_limits(spec)
        labels = self._labels(
            kind=RUNTIME_KIND,
            spec=spec,
            idempotency_key=idempotency_key,
            expires_at=expires_at,
        )
        labels["edu.platform.workspace_port"] = str(spec.workspace_port)
        volume_labels = {
            MANAGED_LABEL: "true",
            KIND_LABEL: "volume",
            "edu.platform.task": spec.task_id,
            "edu.platform.instance": spec.instance_public_id,
            "edu.platform.student": spec.student_id,
            "edu.platform.config_ref": self.config_ref,
            "edu.platform.expires_at": str(expires_at),
        }
        try:
            self._call(
                "RUNTIME_VOLUME_CREATE_FAILED",
                lambda: self.client.create_volume(
                    name=volume_name, driver="local", labels=volume_labels
                ),
            )
            network_id = self._network_id()
            endpoint_config = self._call(
                "RUNTIME_NETWORK_CONFIG_FAILED",
                lambda: self.client.create_endpoint_config(aliases=[f"tasks.{container_name}"]),
            )
            networking_config = self._call(
                "RUNTIME_NETWORK_CONFIG_FAILED",
                lambda: self.client.create_networking_config({network_id: endpoint_config}),
            )
            host_config = self._host_config(
                memory_mb=memory_limit,
                cpu_millicores=cpu_limit,
                volume_name=volume_name,
                extra_binds={
                    secret_volume_name: {
                        "bind": "/run/secrets",
                        "mode": "ro",
                    }
                },
            )
            self._stage_workspace_secret(
                spec=spec,
                idempotency_key=idempotency_key,
                secret_volume=secret_volume_name,
                token=upstream_token,
            )
            container = self._call(
                "RUNTIME_CREATE_FAILED",
                lambda: self.client.create_container(
                    image=self._image_ref(spec),
                    name=container_name,
                    labels=labels,
                    host_config=host_config,
                    networking_config=networking_config,
                    healthcheck=self._healthcheck(spec),
                ),
            )
            container_id = str(container["Id"])
            self._call("RUNTIME_START_FAILED", lambda: self.client.start(container_id))
            inspected = self._call(
                "RUNTIME_CONTAINER_QUERY_FAILED",
                lambda: self.client.inspect_container(container_id),
            )
            self._secret_volumes[container_id] = secret_volume_name
            return self._container_result(inspected)
        except RuntimeAdapterFailure as exc:
            if container_id:
                try:
                    inspected = self._inspect(container_id)
                except RuntimeAdapterFailure:
                    inspected = None
                if inspected is not None:
                    result = self._container_result(inspected)
                    raise RuntimeAdapterFailure(
                        exc.code, retryable=exc.retryable, partial=True, result=result
                    ) from exc
                with suppress(Exception):
                    self.client.remove_container(container_id, force=True, v=False)
            with suppress(RuntimeAdapterFailure):
                self._remove_managed_volume(volume_name)
            with suppress(RuntimeAdapterFailure):
                self._remove_managed_secret_volume(secret_volume_name)
            raise
        except Exception as exc:
            with suppress(RuntimeAdapterFailure):
                self._remove_managed_volume(volume_name)
            with suppress(RuntimeAdapterFailure):
                self._remove_managed_secret_volume(secret_volume_name)
            raise RuntimeAdapterFailure("RUNTIME_CREATE_FAILED") from exc

    def create(self, spec: RuntimeSpec, idempotency_key: str) -> RuntimeResult:
        self._validate_image_and_resources(spec)
        existing = self._existing(idempotency_key)
        if existing:
            result = self._container_result(existing[0])
            if result.metadata.get("spec_digest") and result.metadata[
                "spec_digest"
            ] != self._spec_digest(spec):
                raise RuntimeAdapterFailure("RUNTIME_IDEMPOTENCY_CONFLICT", retryable=False)
            return result
        try:
            return self._create_workspace(spec, idempotency_key)
        except RuntimeAdapterFailure as exc:
            if exc.partial and exc.result is not None:
                raise
            raise

    def _inspect(self, external_id: str) -> dict[str, object] | None:
        try:
            return dict(self.client.inspect_container(external_id))
        except Exception as exc:
            if self._is_not_found(exc):
                return None
            raise RuntimeAdapterFailure("RUNTIME_CONTAINER_QUERY_FAILED") from exc

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        return (
            status_code == 404
            or type(exc).__name__.casefold() == "notfound"
            or "not found" in str(exc).casefold()
        )

    def status(self, external_id: str) -> str:
        timeout = _config_int(self.config.get("boot_timeout", 60))
        poll_interval = max(0.05, _config_float(self.config.get("poll_interval", 0.25)))
        deadline = time.monotonic() + max(timeout, 0)
        while True:
            container = self._inspect(external_id)
            if container is None:
                return "ABSENT"
            state_value = container.get("State")
            state = dict(state_value) if isinstance(state_value, Mapping) else {}
            if bool(state.get("OOMKilled")):
                raise RuntimeAdapterFailure("RUNTIME_RESOURCE_EXCEEDED", retryable=False)
            if str(state.get("Status", "")).casefold() in {"dead", "exited"}:
                return "FAILED"
            if state.get("Running"):
                health_value = state.get("Health")
                health = dict(health_value) if isinstance(health_value, Mapping) else {}
                health_status = str(health.get("Status", "")).casefold()
                if health_status == "unhealthy":
                    raise RuntimeAdapterFailure("RUNTIME_HEALTH_FAILED")
                if health_status in {"healthy", ""}:
                    return "READY"
            if time.monotonic() >= deadline:
                raise TimeoutError("RUNTIME_BOOT_TIMEOUT")
            time.sleep(poll_interval)

    def endpoint(self, external_id: str) -> str:
        container = self._inspect(external_id)
        if container is None:
            raise RuntimeAdapterFailure("RUNTIME_CONTAINER_NOT_FOUND", retryable=False)
        return self._container_result(container).endpoint

    def snapshot(self, external_id: str) -> str:
        if self._inspect(external_id) is None:
            raise RuntimeAdapterFailure("RUNTIME_CONTAINER_NOT_FOUND", retryable=False)
        return f"docker-local-container:{external_id}"

    def _workspace_container(self, external_id: str) -> dict[str, object]:
        container = self._inspect(external_id)
        if container is None:
            raise RuntimeAdapterFailure("RUNTIME_CONTAINER_NOT_FOUND", retryable=False)
        config_value = container.get("Config")
        config = config_value if isinstance(config_value, Mapping) else {}
        labels_value = config.get("Labels") or container.get("Labels")
        labels = dict(labels_value) if isinstance(labels_value, Mapping) else {}
        if not self._owns_managed_resource(labels, RUNTIME_KIND):
            raise RuntimeAdapterFailure("RUNTIME_RESOURCE_NOT_MANAGED", retryable=False)
        state_value = container.get("State")
        state = state_value if isinstance(state_value, Mapping) else {}
        if not state.get("Running"):
            raise RuntimeAdapterFailure("WORKSPACE_VOLUME_UNAVAILABLE")
        return container

    def capture_workspace(
        self, *, external_id: str, relative_path: str, max_bytes: int
    ) -> RuntimeWorkspaceArtifact:
        path = _validated_workspace_path(relative_path)
        if max_bytes < 1:
            raise RuntimeAdapterFailure("WORKSPACE_FILE_TOO_LARGE", retryable=False)
        before = self._workspace_container(external_id)
        try:
            if path == ".":
                created = self.client.exec_create(
                    external_id,
                    ["tar", "--exclude=.git", "--exclude=.vscode", "--exclude=__pycache__",
                     "--exclude=.pytest_cache", "--exclude=.cache", "--exclude=.edu-build",
                     "--exclude=*.class", "--exclude=*.o", "--exclude=*.pyc",
                     "-C", "/", "-cf", "-", "workspace"],
                    user="10001:10001", stdout=True, stderr=False,
                )
                capture_id = str(created["Id"])
                stream = self.client.exec_start(capture_id, stream=True)
            else:
                stream, _stat = self.client.get_archive(external_id, f"/workspace/{path}")
            archive_bytes = _bounded_archive_bytes(stream, max_bytes=max_bytes + 1024 * 1024)
            if path == "." and self.client.exec_inspect(capture_id).get("ExitCode") != 0:
                raise RuntimeAdapterFailure("WORKSPACE_CAPTURE_CONFLICT", retryable=False)
        except RuntimeAdapterFailure:
            raise
        except Exception as exc:
            raise RuntimeAdapterFailure("WORKSPACE_FILE_MISSING", retryable=False) from exc
        if path == ".":
            try:
                content = bundle(
                    unpack(archive_bytes, max_bytes=max_bytes, docker_root=True, generated=True),
                    max_bytes=max_bytes,
                )
            except ProjectArchiveError as exc:
                raise RuntimeAdapterFailure(str(exc), retryable=False) from exc
        else:
            content = _extract_workspace_archive(archive_bytes, path, max_bytes)
        after = self._workspace_container(external_id)
        before_id = str(before.get("Id") or before.get("ID") or external_id)
        after_id = str(after.get("Id") or after.get("ID") or external_id)
        if before_id != after_id:
            raise RuntimeAdapterFailure("WORKSPACE_CAPTURE_CONFLICT", retryable=False)
        if path != ".":
            try:
                content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RuntimeAdapterFailure("WORKSPACE_FILE_INVALID", retryable=False) from exc
        return _workspace_artifact(content, path)

    def _exec(self, external_id: str, command: list[str]) -> None:
        try:
            created = self.client.exec_create(external_id, command, user="10001:10001")
            exec_id = str(created.get("Id") if isinstance(created, Mapping) else created)
            self.client.exec_start(exec_id, detach=False)
            result = self.client.exec_inspect(exec_id)
        except Exception as exc:
            raise RuntimeAdapterFailure("WORKSPACE_RESTORE_FAILED") from exc
        exit_code = int(result.get("ExitCode", 1)) if isinstance(result, Mapping) else 1
        if exit_code != 0:
            raise RuntimeAdapterFailure("WORKSPACE_RESTORE_FAILED")

    def restore_workspace(
        self,
        *,
        external_id: str,
        relative_path: str,
        content: bytes,
        expected_digest: str,
    ) -> None:
        path = _validated_workspace_path(relative_path)
        self._workspace_container(external_id)
        digest = hashlib.sha256(content).hexdigest()
        if not expected_digest or not hmac.compare_digest(digest, str(expected_digest)):
            raise RuntimeAdapterFailure("WORKSPACE_DIGEST_MISMATCH", retryable=False)
        if path == ".":
            self._restore_project(external_id, bytes(content))
            return
        temporary = f"/workspace/.edu-restore-{digest[:24]}"
        archive = _workspace_archive(temporary.rsplit("/", 1)[-1], bytes(content))
        try:
            if self.client.put_archive(external_id, "/workspace", archive) is False:
                raise RuntimeAdapterFailure("WORKSPACE_RESTORE_FAILED")
            self._exec(external_id, [
                "python", "-I", "-c",
                f"import os; os.replace({temporary!r}, '/workspace/{path}')",
            ])
            artifact = self.capture_workspace(
                external_id=external_id, relative_path=path, max_bytes=len(content)
            )
            if not hmac.compare_digest(artifact.digest, digest):
                raise RuntimeAdapterFailure("WORKSPACE_RESTORE_FAILED")
        except RuntimeAdapterFailure:
            raise
        except Exception as exc:
            raise RuntimeAdapterFailure("WORKSPACE_RESTORE_FAILED") from exc

    def _restore_project(self, external_id: str, content: bytes) -> None:
        try:
            files = unpack(content, max_bytes=20 * 1024 * 1024, require_manifest=True)
        except ProjectArchiveError as exc:
            raise RuntimeAdapterFailure(str(exc), retryable=False) from exc
        payload = json.dumps({
            name: value.decode("utf-8") for name, value in files.items()
        }).encode()
        script = """import json,os,shutil,sys,tempfile
root='/workspace'
files=json.loads(sys.stdin.buffer.read(int(sys.argv[1])))
stage=tempfile.mkdtemp(prefix='.edu-stage-',dir=root)
backup=tempfile.mkdtemp(prefix='.edu-backup-',dir=root)
moved=[]
installed=[]
try:
 for name,value in files.items():
  path=os.path.join(stage,name)
  if name.endswith('/'):
   os.makedirs(path,exist_ok=True)
   continue
  os.makedirs(os.path.dirname(path),exist_ok=True)
  with open(path,'w',encoding='utf-8',newline='') as handle: handle.write(value)
 for name in os.listdir(root):
  if name in {os.path.basename(stage),os.path.basename(backup)}: continue
  os.rename(os.path.join(root,name),os.path.join(backup,name))
  moved.append(name)
 for name in os.listdir(stage):
  os.rename(os.path.join(stage,name),os.path.join(root,name))
  installed.append(name)
except BaseException:
 for name in installed: os.rename(os.path.join(root,name),os.path.join(stage,name))
 for name in moved: os.rename(os.path.join(backup,name),os.path.join(root,name))
 shutil.rmtree(stage)
 shutil.rmtree(backup)
 raise
else:
 shutil.rmtree(stage)
 shutil.rmtree(backup)
"""
        connection = None
        try:
            created = self.client.exec_create(
                external_id, ["python", "-I", "-c", script, str(len(payload))],
                user="10001:10001", stdin=True,
            )
            exec_id = str(created["Id"])
            connection = self.client.exec_start(exec_id, socket=True)
            transport = getattr(connection, "_sock", connection)
            transport.sendall(payload)
            deadline = time.monotonic() + 60
            while True:
                result = self.client.exec_inspect(exec_id)
                if not result.get("Running"):
                    if result.get("ExitCode") != 0:
                        raise RuntimeAdapterFailure("WORKSPACE_RESTORE_FAILED")
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeAdapterFailure("WORKSPACE_RESTORE_FAILED")
                time.sleep(0.05)
        except RuntimeAdapterFailure:
            raise
        except Exception as exc:
            raise RuntimeAdapterFailure("WORKSPACE_RESTORE_FAILED") from exc
        finally:
            if connection is not None:
                connection.close()

    def destroy(self, external_id: str, idempotency_key: str) -> None:
        del idempotency_key
        container = self._inspect(external_id)
        if container is None:
            secret_volume_name = self._secret_volumes.get(external_id, "")
            if secret_volume_name:
                self._remove_managed_secret_volume(secret_volume_name)
                self._secret_volumes.pop(external_id, None)
            return
        config_value = container.get("Config")
        config = config_value if isinstance(config_value, Mapping) else {}
        labels_value = config.get("Labels") or container.get("Labels")
        labels = dict(labels_value) if isinstance(labels_value, Mapping) else {}
        if not self._owns_managed_resource(labels, RUNTIME_KIND):
            raise RuntimeAdapterFailure("RUNTIME_RESOURCE_NOT_MANAGED", retryable=False)
        volume_name = self._volume_name_from_container(container)
        if volume_name:
            self._retain_workspace_volume(
                volume_name, task_id=str(labels.get("edu.platform.task") or "")
            )
        mounted_secret = self._secret_volume_name_from_container(container)
        secret_volume_name = mounted_secret or self._secret_volumes.get(external_id, "")
        self._call(
            "RUNTIME_DESTROY_FAILED",
            lambda: self.client.remove_container(external_id, force=True, v=False),
        )
        if secret_volume_name:
            try:
                self._remove_managed_secret_volume(secret_volume_name)
            except RuntimeAdapterFailure:
                self._secret_volumes[external_id] = secret_volume_name
                raise
        self._secret_volumes.pop(external_id, None)

    def _retain_workspace_volume(self, volume_name: str, *, task_id: str) -> None:
        try:
            volume = self.client.inspect_volume(volume_name)
        except Exception as exc:
            raise RuntimeAdapterFailure("RUNTIME_VOLUME_RETENTION_FAILED") from exc
        labels = dict(volume.get("Labels") or {})
        if (
            not self._owns_managed_resource(labels, "volume")
            or not task_id
            or labels.get("edu.platform.task") != task_id
        ):
            raise RuntimeAdapterFailure("RUNTIME_RESOURCE_NOT_MANAGED", retryable=False)
        update_volume = getattr(self.client, "update_volume", None)
        if not callable(update_volume):
            # Docker Local volume labels are immutable. Keep the validated
            # creation-time expiry so a reconciler can still collect it.
            return
        labels["edu.platform.expires_at"] = str(
            int(time.time())
            + max(60, int(getattr(settings, "WORKSPACE_VOLUME_RETENTION_SECONDS", 900)))
        )
        self._call(
            "RUNTIME_VOLUME_RETENTION_FAILED",
            lambda: update_volume(volume_name, labels=labels),
        )

    def _volume_name_from_container(self, container: Mapping[str, object]) -> str:
        mounts_value = container.get("Mounts")
        mounts = mounts_value if isinstance(mounts_value, list) else []
        for mount in mounts:
            if not isinstance(mount, Mapping):
                continue
            if str(mount.get("Destination", "")) == "/workspace":
                return str(mount.get("Name") or mount.get("Source") or "")
        return ""

    def _secret_volume_name_from_container(self, container: Mapping[str, object]) -> str:
        mounts_value = container.get("Mounts")
        mounts = mounts_value if isinstance(mounts_value, list) else []
        for mount in mounts:
            if not isinstance(mount, Mapping):
                continue
            if str(mount.get("Destination", "")) == "/run/secrets":
                return str(mount.get("Name") or mount.get("Source") or "")
        return ""

    def _remove_managed_volume(self, volume_name: str) -> bool:
        try:
            volume = self.client.inspect_volume(volume_name)
        except Exception as exc:
            if self._is_not_found(exc):
                return False
            raise RuntimeAdapterFailure("RUNTIME_RESOURCE_QUERY_FAILED") from exc
        labels = dict(volume.get("Labels") or {})
        if not self._owns_managed_resource(labels, "volume"):
            raise RuntimeAdapterFailure("RUNTIME_RESOURCE_NOT_MANAGED", retryable=False)
        self._call(
            "RUNTIME_RESOURCE_DESTROY_FAILED",
            lambda: self.client.remove_volume(volume_name, force=True),
        )
        return True

    def _remove_managed_secret_volume(self, volume_name: str) -> bool:
        if not volume_name:
            return False
        try:
            volume = self.client.inspect_volume(volume_name)
        except Exception as exc:
            if self._is_not_found(exc):
                return False
            raise RuntimeAdapterFailure("RUNTIME_RESOURCE_QUERY_FAILED") from exc
        labels = dict(volume.get("Labels") or {})
        if not self._owns_managed_resource(labels, "workspace-secret"):
            raise RuntimeAdapterFailure("RUNTIME_RESOURCE_NOT_MANAGED", retryable=False)
        self._call(
            "RUNTIME_RESOURCE_DESTROY_FAILED",
            lambda: self.client.remove_volume(volume_name, force=True),
        )
        return True

    def _inventory_item(self, container: Mapping[str, object]) -> RuntimeInventoryItem:
        result = self._container_result(container)
        return RuntimeInventoryItem(
            external_id=result.external_id,
            status=self.status(result.external_id),
            metadata=dict(result.metadata),
        )

    def inventory(self) -> list[RuntimeInventoryItem]:
        containers = self._call(
            "RUNTIME_CONTAINER_QUERY_FAILED",
            lambda: self.client.containers(
                all=True,
                filters={
                    "label": [
                        f"{MANAGED_LABEL}=true",
                        f"{KIND_LABEL}={RUNTIME_KIND}",
                        f"edu.platform.config_ref={self.config_ref}",
                    ]
                },
            ),
        )
        result: list[RuntimeInventoryItem] = []
        for container in containers:
            try:
                result.append(self._inventory_item(container))
            except RuntimeAdapterFailure:
                result.append(
                    RuntimeInventoryItem(
                        external_id=str(container.get("Id", "")),
                        status="FAILED",
                        metadata={"driver": "DOCKER_LOCAL", "managed": True, "kind": RUNTIME_KIND},
                    )
                )
        return result

    def health(self) -> Mapping[str, object]:
        try:
            self.client.ping()
            info = self.client.info()
            return {
                "status": "HEALTHY",
                "node_count": 1,
                "capacity_cpu_millicores": int(info.get("NCPU", 0)) * 1000,
                "available_cpu_millicores": int(info.get("NCPU", 0)) * 1000,
                "capacity_memory_mb": int(info.get("MemTotal", 0)) // (1024 * 1024),
                "available_memory_mb": int(info.get("MemTotal", 0)) // (1024 * 1024),
                "driver": "DOCKER_LOCAL",
                "config_ref": self.config_ref,
            }
        except RuntimeAdapterFailure:
            raise
        except Exception:
            return {
                "status": "UNAVAILABLE",
                "node_count": 0,
                "capacity_cpu_millicores": 0,
                "available_cpu_millicores": 0,
                "capacity_memory_mb": 0,
                "available_memory_mb": 0,
                "driver": "DOCKER_LOCAL",
                "config_ref": self.config_ref,
                "error_code": "RUNTIME_UNAVAILABLE",
            }

    def coordinate_capacity(
        self, spec: RuntimeSpec, *, idempotency_key: str, replicas: int
    ) -> RuntimeResult:
        del spec, idempotency_key
        if replicas < 0:
            raise RuntimeAdapterFailure("RUNTIME_CAPACITY_INVALID", retryable=False)
        return RuntimeResult(
            external_id="",
            metadata={"driver": "DOCKER_LOCAL", "managed": True, "replicas": replicas},
        )

    def release_capacity(self, *, idempotency_key: str) -> None:
        del idempotency_key

    def _archive(self, files: Mapping[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for name, content in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o444
                archive.addfile(info, io.BytesIO(content))
        return buffer.getvalue()

    @staticmethod
    def _test_cases(tests: bytes) -> list[tuple[str, object, bool]]:
        try:
            payload = json.loads(tests.decode()) if tests else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            raw_cases = payload.get("cases", [])
        elif isinstance(payload, list):
            raw_cases = payload
        else:
            raw_cases = []
        cases: list[tuple[str, object, bool]] = []
        if isinstance(raw_cases, list):
            for case in raw_cases:
                if isinstance(case, dict):
                    has_expected = "expected" in case or "output" in case
                    expected = case.get("expected", case.get("output"))
                    stdin = case.get("input", case.get("stdin", ""))
                else:
                    has_expected = False
                    expected = None
                    stdin = case
                cases.append((str(stdin or ""), expected, has_expected))
        if cases:
            return cases
        return [(tests.decode(errors="replace"), None, False)]

    @staticmethod
    def _runner_source(
        command: list[str],
        case_inputs: list[str],
        compile_command: list[str] | None = None,
        run_command: list[str] | None = None,
    ) -> bytes:
        # The submitted file is copied under the private judge directory.  The
        # command remains the server-generated ``python <entrypoint>`` contract,
        # but the runner resolves the entrypoint to that private path.
        runner_command = ["python", f"/judge/{command[1]}"]
        compile_argv = list(compile_command or [])
        run_argv = list(run_command or runner_command)
        if compile_argv:
            compile_argv = [
                f"/judge/{arg}"
                if arg.endswith((".c", ".cpp", ".cc", ".java", ".go"))
                and not arg.startswith("/")
                else arg
                for arg in compile_argv
            ]
        encoded_command = json.dumps(runner_command, ensure_ascii=True)
        encoded_inputs = json.dumps(case_inputs, ensure_ascii=True)
        return f"""import json, os, subprocess, time

COMMAND = {encoded_command}
COMPILE = {json.dumps(compile_argv, ensure_ascii=True)}
RUN = {json.dumps(run_argv, ensure_ascii=True)}
CASE_INPUTS = {encoded_inputs}
EXECUTION_DEADLINE = time.monotonic() + float(os.environ.get("TOTAL_TIMEOUT", "5"))
MAX_OUTPUT = max(1, int(os.environ.get("MAX_OUTPUT_BYTES", "65536")))


def tokens(value):
    return str(value or "").split()


os.makedirs("/tmp/.cache", exist_ok=True)
os.chdir("/judge")
os.environ["GOCACHE"] = "/tmp/.cache/go-build"
os.environ["GOPATH"] = "/tmp/.cache/go"
if COMPILE and COMPILE[0] == "go":
    COMPILE[0] = "/usr/local/go/bin/go"
if COMPILE:
    built = subprocess.run(
        COMPILE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=float(os.environ.get("CASE_TIMEOUT", "5")),
    )
    if built.returncode:
        print(json.dumps({{
            "status": "FAILED", "cases": 0,
            "compile_stderr": built.stderr.decode(errors="replace"),
        }}))
        raise SystemExit(0)


def run_one(stdin):
    remaining = EXECUTION_DEADLINE - time.monotonic()
    if remaining <= 0:
        return {{"status": "TIMEOUT", "stdout": "", "stderr": "timeout"}}
    try:
        completed = subprocess.run(
            RUN or COMMAND,
            input=str(stdin or "").encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=min(float(os.environ.get("CASE_TIMEOUT", "5")), remaining),
        )
    except subprocess.TimeoutExpired as exc:
        return {{
            "status": "TIMEOUT",
            "stdout": (exc.stdout or b"").decode(errors="replace"),
            "stderr": "timeout",
        }}
    stdout = completed.stdout.decode(errors="replace")
    stderr = completed.stderr.decode(errors="replace")
    if len(stdout.encode()) > MAX_OUTPUT or len(stderr.encode()) > MAX_OUTPUT:
        return {{"status": "OUTPUT_LIMIT", "stdout": stdout[:MAX_OUTPUT], "stderr": "output limit"}}
    if completed.returncode == 0:
        status = "PASSED"
    elif completed.returncode == -9:
        status = "RESOURCE_EXCEEDED"
    else:
        status = "FAILED"
    return {{
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": completed.returncode,
    }}


results = []
for stdin in CASE_INPUTS:
    item = run_one(stdin)
    results.append(item)
    if item["status"] != "PASSED":
        break
status = next(
    (item["status"] for item in results if item["status"] != "PASSED"),
    "PASSED",
)
print(
    json.dumps(
        {{"status": status, "cases": len(results), "results": results}},
        ensure_ascii=True,
    )
)
""".encode()

    def _stage_judge_files(
        self,
        *,
        spec: RuntimeSpec,
        command: list[str],
        source: bytes,
        case_inputs: list[str],
        compile_command: list[str] | None = None,
        run_command: list[str] | None = None,
        memory_mb: int,
        cpu_millicores: int,
        resource_id: str,
        expires_at: int,
    ) -> str:
        """Populate a private volume without making the judge rootfs writable."""

        volume_name = self._safe_name(resource_id, prefix="experimental-platform-judge-data")
        volume_labels = self._labels(
            kind="volume",
            spec=spec,
            external_id=resource_id,
            expires_at=expires_at,
        )
        # A worker crash may leave a stager or judge with the deterministic
        # name. Remove only matching managed resources before replaying.
        self.destroy_judge(resource_id, f"judge-replay:{resource_id}")
        try:
            existing_volume = self.client.inspect_volume(volume_name)
        except Exception:
            existing_volume = None
        if isinstance(existing_volume, Mapping):
            existing_labels = dict(existing_volume.get("Labels") or {})
            if (
                existing_labels.get(MANAGED_LABEL) != "true"
                or existing_labels.get(KIND_LABEL) != "volume"
                or existing_labels.get("edu.platform.judge") != resource_id
            ):
                raise RuntimeAdapterFailure("RUNTIME_RESOURCE_NOT_MANAGED", retryable=False)
            self._call(
                "RUNTIME_RESOURCE_DESTROY_FAILED",
                lambda: self.client.remove_volume(volume_name, force=True),
            )
        self._call(
            "RUNTIME_VOLUME_CREATE_FAILED",
            lambda: self.client.create_volume(
                name=volume_name, driver="local", labels=volume_labels
            ),
        )
        inspected_volume = self._call(
            "RUNTIME_RESOURCE_QUERY_FAILED",
            lambda: self.client.inspect_volume(volume_name),
        )
        actual_labels = dict(inspected_volume.get("Labels") or {})
        if actual_labels.get(MANAGED_LABEL) != "true" or actual_labels.get(KIND_LABEL) != "volume":
            raise RuntimeAdapterFailure("RUNTIME_RESOURCE_NOT_MANAGED", retryable=False)

        stage_id = ""
        stage_labels = self._labels(
            kind="judge-stager",
            spec=spec,
            external_id=resource_id,
            expires_at=expires_at,
        )
        files: dict[str, bytes]
        try:
            files = unpack(source, max_bytes=20 * 1024 * 1024, require_manifest=True)
            if command[1] not in files:
                raise ProjectArchiveError("RUNTIME_ENTRYPOINT_NOT_FOUND")
        except ProjectArchiveError:
            files = {command[1]: source}
        files["runner.py"] = self._runner_source(command, case_inputs, compile_command, run_command)
        archive = self._archive(files)
        staged_successfully = False
        try:
            stage_host_config = self._host_config(
                memory_mb=memory_mb,
                cpu_millicores=cpu_millicores,
                network_mode="none",
                volume_name=volume_name,
                volume_target="/staging",
                volume_mode="rw",
                read_only=False,
            )
            staged = self._call(
                "RUNTIME_JUDGE_STAGE_CREATE_FAILED",
                lambda: self.client.create_container(
                    image=self._image_ref(spec),
                    name=self._safe_name(resource_id, prefix="experimental-platform-judge-stage"),
                    command=["python", "-c", "import time; time.sleep(30)"],
                    labels=stage_labels,
                    host_config=stage_host_config,
                ),
            )
            stage_id = str(staged["Id"])
            self._call(
                "RUNTIME_JUDGE_STAGE_START_FAILED",
                lambda: self.client.start(stage_id),
            )
            self._call(
                "RUNTIME_JUDGE_UPLOAD_FAILED",
                lambda: self.client.put_archive(stage_id, "/staging", archive),
            )
            staged_successfully = True
            return volume_name
        finally:
            if stage_id:
                with suppress(Exception):
                    self.client.remove_container(stage_id, force=True, v=True)
            if not staged_successfully:
                with suppress(RuntimeAdapterFailure):
                    self._remove_managed_volume(volume_name)

    def _run_container(
        self,
        *,
        spec: RuntimeSpec,
        command: list[str],
        source: bytes,
        tests: bytes,
        timeout_seconds: int,
        memory_mb: int,
        cpu_millicores: int,
        network_mode: str,
        resource_id: str,
        kind: str = "judge",
        execution_plan: Mapping[str, list[str]] | None = None,
    ) -> RuntimeExecutionResult:
        if (
            len(command) != 2
            or command[0] != "python"
            or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", command[1])
            or any(part in {".", ".."} for part in command[1].split("/"))
        ):
            raise RuntimeAdapterFailure("RUNTIME_COMMAND_NOT_ALLOWED", retryable=False)
        if network_mode != "DENY_ALL":
            raise RuntimeAdapterFailure("RUNTIME_NETWORK_NOT_ALLOWED", retryable=False)
        expires_at = int(time.time()) + max(timeout_seconds, 60)
        labels = self._labels(
            kind=kind,
            spec=spec,
            external_id=resource_id,
            expires_at=expires_at,
        )
        name = self._safe_name(resource_id, prefix="experimental-platform-judge")
        test_cases = self._test_cases(tests)
        volume_name = self._stage_judge_files(
            spec=spec,
            command=command,
            source=source,
            case_inputs=[case[0] for case in test_cases],
            compile_command=(execution_plan or {}).get("compile") if execution_plan else None,
            run_command=(execution_plan or {}).get("run") if execution_plan else None,
            memory_mb=memory_mb,
            cpu_millicores=cpu_millicores,
            resource_id=resource_id,
            expires_at=expires_at,
        )
        container_id = ""
        started = time.monotonic()
        try:
            host_config = self._host_config(
                memory_mb=memory_mb,
                cpu_millicores=cpu_millicores,
                network_mode="none",
                volume_name=volume_name,
                volume_target="/judge",
                volume_mode="ro",
            )
            if execution_plan and execution_plan.get("compile"):
                host_config["Tmpfs"]["/tmp"] = "rw,exec,nosuid,size=128m,uid=10001,gid=10001"
            created = self._call(
                "RUNTIME_JUDGE_CREATE_FAILED",
                lambda: self.client.create_container(
                    image=self._image_ref(spec),
                    name=name,
                    command=["python", "/judge/runner.py"],
                    environment={
                        "CASE_TIMEOUT": str(max(float(timeout_seconds), 0.1)),
                        "TOTAL_TIMEOUT": str(max(float(timeout_seconds), 0.1)),
                        "MAX_OUTPUT_BYTES": "65536",
                    },
                    labels=labels,
                    host_config=host_config,
                ),
            )
            container_id = str(created["Id"])
            self._call("RUNTIME_JUDGE_START_FAILED", lambda: self.client.start(container_id))
            wait_result = self._call(
                "RUNTIME_JUDGE_WAIT_FAILED",
                lambda: self.client.wait(container_id, timeout=max(1, int(timeout_seconds) + 2)),
            )
            status_code = (
                int(wait_result.get("StatusCode", 1)) if isinstance(wait_result, Mapping) else 1
            )
            inspected = self._call(
                "RUNTIME_JUDGE_QUERY_FAILED",
                lambda: self.client.inspect_container(container_id),
            )
            state = dict(inspected.get("State") or {})
            stdout = self.client.logs(container_id, stdout=True, stderr=False).decode(
                errors="replace"
            )
            stderr = self.client.logs(container_id, stdout=False, stderr=True).decode(
                errors="replace"
            )
            report: dict[str, object] = {}
            for line in reversed(stdout.splitlines()):
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and "status" in value:
                    report = value
                    break
            if bool(state.get("OOMKilled")):
                return RuntimeExecutionResult(
                    status="RESOURCE_EXCEEDED",
                    stdout=stdout[-20000:],
                    stderr=stderr[-20000:],
                    error_code="RUNTIME_MEMORY_EXCEEDED",
                    result_summary="Execution exceeded memory limit",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            if status_code == 124 or report.get("status") == "TIMEOUT":
                return RuntimeExecutionResult(
                    status="TIMEOUT",
                    stdout=stdout[-20000:],
                    stderr=stderr[-20000:],
                    error_code="RUNTIME_TIMEOUT",
                    test_report=report,
                    result_summary="Execution timed out",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            report_results = report.get("results", [])
            if report.get("status") == "OUTPUT_LIMIT" or any(
                isinstance(item, Mapping) and item.get("status") == "OUTPUT_LIMIT"
                for item in (report_results if isinstance(report_results, list) else [])
            ):
                return RuntimeExecutionResult(
                    status="RESOURCE_EXCEEDED",
                    stdout=stdout[-20000:],
                    stderr=stderr[-20000:],
                    error_code="RUNTIME_OUTPUT_LIMIT",
                    result_summary="Execution output exceeded limit",
                    test_report=report,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            default_status = "PASSED" if status_code == 0 else "FAILED"
            result_status = str(report.get("status") or default_status)
            report_results = report.get("results")
            if isinstance(report_results, list):
                for index, (_stdin, expected, has_expected) in enumerate(test_cases):
                    if not has_expected or index >= len(report_results):
                        continue
                    item = report_results[index]
                    if not isinstance(item, dict) or item.get("status") != "PASSED":
                        continue
                    actual = item.get("stdout", "") if isinstance(item, Mapping) else ""
                    try:
                        test_config = json.loads(tests.decode()) if tests else {}
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        test_config = {}
                    comparator = (
                        str(test_config.get("comparator", "token"))
                        if isinstance(test_config, Mapping) else "token"
                    )
                    absolute_tolerance = (
                        float(test_config.get("absolute_tolerance", 1e-6))
                        if isinstance(test_config, Mapping) else 1e-6
                    )
                    relative_tolerance = (
                        float(test_config.get("relative_tolerance", 1e-6))
                        if isinstance(test_config, Mapping) else 1e-6
                    )
                    if not outputs_match(
                        str(actual or ""), str(expected if expected is not None else ""),
                        comparator=comparator,
                        absolute_tolerance=absolute_tolerance,
                        relative_tolerance=relative_tolerance,
                    ):
                        item["status"] = "FAILED"
                        report.setdefault("failed_case", index + 1)
                        if result_status == "PASSED":
                            result_status = "FAILED"
                            report["status"] = "FAILED"
            allowed_statuses = {
                "PASSED",
                "FAILED",
                "TIMEOUT",
                "RESOURCE_EXCEEDED",
            }
            if result_status not in allowed_statuses:
                result_status = "FAILED"
            error_code = ""
            if result_status == "TIMEOUT":
                error_code = "RUNTIME_TIMEOUT"
            elif result_status == "RESOURCE_EXCEEDED":
                error_code = "RUNTIME_MEMORY_EXCEEDED"
            elif result_status != "PASSED":
                if "compile_stderr" in report:
                    error_code = "RUNTIME_COMPILE_FAILED"
                elif isinstance(report_results, list) and any(
                    isinstance(item, Mapping) and item.get("returncode") not in (None, 0)
                    for item in report_results
                ):
                    error_code = "RUNTIME_EXECUTION_FAILED"
                else:
                    error_code = "RUNTIME_ALGORITHM_FAILED"
            return RuntimeExecutionResult(
                status=result_status,
                stdout=stdout[-20000:],
                stderr=stderr[-20000:],
                test_report=report,
                error_code=error_code,
                result_summary=result_status,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:
            if isinstance(exc, RuntimeAdapterFailure):
                raise
            raise RuntimeAdapterFailure("RUNTIME_JUDGE_FAILED") from exc
        finally:
            if container_id:
                # Cleanup is retried by the existing compensation path.
                with suppress(Exception):
                    self.client.remove_container(container_id, force=True, v=True)
            with suppress(RuntimeAdapterFailure):
                self._remove_managed_volume(volume_name)

    def execute_judge(
        self,
        *,
        spec: RuntimeSpec,
        command: list[str],
        source: bytes,
        tests: bytes,
        timeout_seconds: int,
        memory_mb: int,
        cpu_millicores: int,
        network_mode: str,
        judge_id: str,
        execution_plan: Mapping[str, list[str]] | None = None,
    ) -> RuntimeExecutionResult:
        return self._run_container(
            spec=spec,
            command=command,
            source=source,
            tests=tests,
            timeout_seconds=timeout_seconds,
            memory_mb=memory_mb,
            cpu_millicores=cpu_millicores,
            network_mode=network_mode,
            resource_id=judge_id,
            execution_plan=execution_plan,
        )

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
        tests: bytes = b"",
        execution_plan: Mapping[str, list[str]] | None = None,
    ) -> RuntimeExecutionResult:
        return self._run_container(
            spec=spec,
            command=command,
            source=source,
            tests=tests,
            timeout_seconds=timeout_seconds,
            memory_mb=memory_mb,
            cpu_millicores=cpu_millicores,
            network_mode=network_mode,
            resource_id=f"execution-{spec.task_id}-{hashlib.sha256(source).hexdigest()[:12]}",
            execution_plan=execution_plan,
        )

    def destroy_judge(self, judge_id: str, idempotency_key: str = "") -> None:
        del idempotency_key
        containers = self._call(
            "RUNTIME_JUDGE_QUERY_FAILED",
            lambda: self.client.containers(
                all=True,
                filters={"label": [f"{MANAGED_LABEL}=true", f"edu.platform.judge={judge_id}"]},
            ),
        )
        for container in containers:
            labels = dict(container.get("Labels") or {})
            kind = str(labels.get(KIND_LABEL) or "")
            if kind not in {"judge", "judge-stager"} or not self._owns_managed_resource(
                labels, kind
            ):
                continue
            container_id = str(container.get("Id") or "")
            if container_id:
                self._call(
                    "RUNTIME_JUDGE_DESTROY_FAILED",
                    lambda container_id=container_id: self.client.remove_container(
                        container_id, force=True, v=True
                    ),
                )

    def inventory_resources(self) -> list[RuntimeInventoryItem]:
        result: list[RuntimeInventoryItem] = []
        containers = self._call(
            "RUNTIME_RESOURCE_QUERY_FAILED",
            lambda: self.client.containers(
                all=True,
                filters={
                    "label": [
                        f"{MANAGED_LABEL}=true",
                        f"edu.platform.config_ref={self.config_ref}",
                    ]
                },
            ),
        )
        for container in containers:
            labels = dict(container.get("Labels") or {})
            kind = str(labels.get(KIND_LABEL) or "")
            if kind not in {"judge", "judge-stager"}:
                continue
            external_id = str(labels.get("edu.platform.judge") or container.get("Id") or "")
            if external_id:
                result.append(
                    RuntimeInventoryItem(
                        external_id=external_id,
                        status=str(container.get("State") or "UNKNOWN").upper(),
                        metadata={
                            "driver": "DOCKER_LOCAL",
                            "config_ref": self.config_ref,
                            "kind": kind,
                            "managed": True,
                            "judge_id": external_id,
                            "task_id": str(labels.get("edu.platform.task", "")),
                            "expires_at": int(labels.get("edu.platform.expires_at", "0") or 0),
                        },
                    )
                )
        volumes = self._call(
            "RUNTIME_RESOURCE_QUERY_FAILED",
            lambda: self.client.volumes(
                filters={
                    "label": [
                        f"{MANAGED_LABEL}=true",
                        f"{KIND_LABEL}=volume",
                        f"edu.platform.config_ref={self.config_ref}",
                    ]
                }
            ),
        )
        for volume in (volumes.get("Volumes") or []) if isinstance(volumes, Mapping) else []:
            labels = dict(volume.get("Labels") or {})
            name = str(volume.get("Name") or "")
            if name:
                result.append(
                    RuntimeInventoryItem(
                        external_id=name,
                        status="READY",
                        metadata={
                            "driver": "DOCKER_LOCAL",
                            "config_ref": self.config_ref,
                            "kind": "volume",
                            "managed": True,
                            "task_id": str(labels.get("edu.platform.task", "")),
                            "expires_at": int(labels.get("edu.platform.expires_at", "0") or 0),
                        },
                    )
                )
        return result

    def destroy_resource(self, external_id: str, idempotency_key: str = "") -> None:
        del idempotency_key
        try:
            if self._remove_managed_volume(external_id):
                return
        except RuntimeAdapterFailure as exc:
            if exc.code != "RUNTIME_RESOURCE_NOT_MANAGED":
                raise
        try:
            if self._remove_managed_secret_volume(external_id):
                return
        except RuntimeAdapterFailure as exc:
            if exc.code != "RUNTIME_RESOURCE_NOT_MANAGED":
                raise
        self.destroy_judge(external_id)


class DockerSwarmAdapter:
    """Docker Engine API adapter. Only runtime workers may receive its credentials."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        config: Mapping[str, object] | None = None,
        config_ref: str = "runtime/swarm",
    ):
        self.config = dict(config or {})
        self.config_ref = config_ref.strip() or "runtime/swarm"
        self.client = client or self._build_client()
        self._service_secrets: dict[str, str] = {}

    def _build_client(self) -> Any:
        try:
            import docker
            from docker.tls import TLSConfig
        except ImportError as exc:  # pragma: no cover - deployment packaging guard
            raise RuntimeAdapterFailure("RUNTIME_CLIENT_UNAVAILABLE", retryable=False) from exc

        base_url = str(self.config.get("base_url") or settings.SWARM_DOCKER_HOST)
        tls: bool | TLSConfig = False
        if bool(self.config.get("tls_verify", settings.SWARM_DOCKER_TLS_VERIFY)):
            tls = TLSConfig(
                client_cert=(
                    str(self.config.get("client_cert") or settings.SWARM_DOCKER_CERT_PATH),
                    str(self.config.get("client_key") or settings.SWARM_DOCKER_KEY_PATH),
                ),
                ca_cert=str(self.config.get("ca_cert") or settings.SWARM_DOCKER_CA_PATH),
                verify=True,
            )
        return docker.APIClient(
            base_url=base_url,
            version=str(self.config.get("api_version") or settings.SWARM_DOCKER_API_VERSION),
            tls=tls,
            timeout=_config_int(
                self.config.get("request_timeout", settings.SWARM_REQUEST_TIMEOUT_SECONDS)
            ),
        )

    def capabilities(self) -> Mapping[str, bool]:
        return {
            "image_build": True,
            "real_container": True,
            "resource_limits": True,
            "workspace_access": True,
        }

    @staticmethod
    def _safe_name(task_id: str, *, prefix: str = "experimental-platform-lab") -> str:
        normalized = NAME_PATTERN.sub("-", task_id.casefold()).strip("-")
        digest = hashlib.sha256(task_id.encode()).hexdigest()[:10]
        return f"{prefix}-{normalized[:8]}-{digest}"

    @staticmethod
    def _idempotency_digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _spec_digest(spec: RuntimeSpec) -> str:
        payload = {
            "task_id": spec.task_id,
            "course_id": spec.course_id,
            "student_id": spec.student_id,
            "image_ref": spec.image_ref,
            "cpu_millicores": spec.cpu_millicores,
            "cpu_limit_millicores": spec.cpu_limit_millicores,
            "memory_mb": spec.memory_mb,
            "memory_limit_mb": spec.memory_limit_mb,
            "disk_gb": spec.disk_gb,
            "network_policy": dict(spec.network_policy),
            "workspace_capabilities": dict(spec.workspace_capabilities),
            "workspace_port": spec.workspace_port,
            "healthcheck_path": spec.healthcheck_path,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _call(self, code: str, operation: Any) -> Any:
        try:
            return operation()
        except RuntimeAdapterFailure:
            raise
        except Exception as exc:
            raise RuntimeAdapterFailure(code) from exc

    def _network_name(self) -> str:
        return str(self.config.get("runtime_network") or settings.SWARM_RUNTIME_NETWORK)

    def _networks(self, spec: RuntimeSpec) -> list[dict[str, object]]:
        network_name = self._network_name()
        values = self._call(
            "RUNTIME_NETWORK_QUERY_FAILED", lambda: self.client.networks(names=[network_name])
        )
        if values:
            network_id = str(values[0]["Id"])
        else:
            response = self._call(
                "RUNTIME_NETWORK_CREATE_FAILED",
                lambda: self.client.create_network(
                    name=network_name,
                    driver="overlay",
                    internal=True,
                    attachable=False,
                    scope="swarm",
                    options={"encrypted": ""},
                    labels={
                        MANAGED_LABEL: "true",
                        KIND_LABEL: "runtime-gateway-network",
                    },
                ),
            )
            network_id = str(response["Id"])

        result: list[dict[str, object]] = [
            {"Target": network_id, "Aliases": [self._safe_name(spec.task_id)]}
        ]
        policy_mode = str(
            spec.network_policy.get("mode")
            or spec.network_policy.get("default_egress")
            or "DENY_ALL"
        ).upper()
        if policy_mode == "ALLOWLIST":
            policy_ref = str(spec.network_policy.get("policy_ref") or "")
            configured = self.config.get("egress_networks", {})
            egress_networks = configured if isinstance(configured, Mapping) else {}
            egress_target = str(egress_networks.get(policy_ref) or "")
            if not policy_ref or not egress_target:
                raise RuntimeAdapterFailure("RUNTIME_EGRESS_POLICY_UNAVAILABLE", retryable=False)
            result.append({"Target": egress_target})
        elif policy_mode != "DENY_ALL":
            raise RuntimeAdapterFailure("RUNTIME_NETWORK_POLICY_INVALID", retryable=False)
        return result

    def preflight(self, spec: RuntimeSpec) -> RuntimeResult:
        if spec.runtime_type != "CONTAINER":
            raise RuntimeAdapterFailure("RUNTIME_TYPE_UNSUPPORTED", retryable=False)
        if (
            not spec.image_registry
            or not spec.image_repository
            or not spec.image_digest.startswith("sha256:")
        ):
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_REFERENCE_INVALID", retryable=False)
        if not 1 <= spec.workspace_port <= 65535 or not spec.healthcheck_path.startswith("/"):
            raise RuntimeAdapterFailure("RUNTIME_WORKSPACE_CONTRACT_INVALID", retryable=False)
        self._call("RUNTIME_UNAVAILABLE", self.client.ping)
        info = self._call("RUNTIME_UNAVAILABLE", self.client.info)
        swarm = info.get("Swarm", {}) if isinstance(info, dict) else {}
        if str(swarm.get("LocalNodeState", "")).casefold() != "active":
            raise RuntimeAdapterFailure("RUNTIME_SWARM_INACTIVE")
        return RuntimeResult(
            external_id=f"swarm-preflight:{spec.task_id}",
            metadata={"driver": "DOCKER_SWARM", "image_ref": spec.image_ref},
        )

    def prepare_image(self, spec: RuntimeSpec) -> None:
        del spec

    def build_image(
        self,
        *,
        registry: str,
        repository: str,
        tag: str,
        context: Mapping[str, Any],
        build_args: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        archive = context.get("archive")
        if not isinstance(archive, (bytes, bytearray)):
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_CONTEXT_UNAVAILABLE", retryable=False)
        reference = f"{registry.rstrip('/')}/{repository.lstrip('/')}:{tag}"
        self._call(
            "RUNTIME_IMAGE_BUILD_FAILED",
            lambda: _consume_docker_stream(
                self.client.build(
                    fileobj=io.BytesIO(bytes(archive)),
                    custom_context=True,
                    encoding="gzip",
                    tag=reference,
                    buildargs=dict(build_args),
                    rm=True,
                    decode=True,
                ),
                "RUNTIME_IMAGE_BUILD_FAILED",
            ),
        )
        push_output = self._call(
            "RUNTIME_IMAGE_PUSH_FAILED",
            lambda: _consume_docker_stream(
                self.client.push(reference, decode=True),
                "RUNTIME_IMAGE_PUSH_FAILED",
            ),
        )
        return _docker_registry_image_result(push_output, self.client, reference)

    def resolve_image(self, *, registry: str, repository: str, tag: str) -> Mapping[str, Any]:
        reference = f"{registry.rstrip('/')}/{repository.lstrip('/')}:{tag}"

        def _pull_and_resolve() -> Mapping[str, Any]:
            output = _consume_docker_stream(
                self.client.pull(reference), "RUNTIME_IMAGE_PULL_FAILED"
            )
            return _docker_registry_image_result(output, self.client, reference)

        return self._call("RUNTIME_IMAGE_PULL_FAILED", _pull_and_resolve)

    def validate_image(self, *, digest: str) -> Mapping[str, Any]:
        inspected = self._call(
            "RUNTIME_IMAGE_VALIDATE_FAILED", lambda: self.client.inspect_image(digest)
        )
        if not inspected:
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_VALIDATE_FAILED", retryable=False)
        return {"valid": True, "digest": digest, "scan_status": "PENDING"}

    def attach_network(self, spec: RuntimeSpec) -> None:
        self._networks(spec)

    def _existing(self, idempotency_digest: str) -> list[dict[str, Any]]:
        return list(
            self._call(
                "RUNTIME_SERVICE_QUERY_FAILED",
                lambda: self.client.services(
                    filters={
                        "label": [
                            f"{MANAGED_LABEL}=true",
                            f"{KIND_LABEL}={RUNTIME_KIND}",
                            f"edu.platform.idempotency={idempotency_digest}",
                        ]
                    }
                ),
            )
        )

    def _result(self, service: Mapping[str, Any]) -> RuntimeResult:
        spec = service.get("Spec", {}) if isinstance(service, Mapping) else {}
        labels = spec.get("Labels", {}) if isinstance(spec, Mapping) else {}
        name = str(spec.get("Name") or labels.get("edu.platform.service_name") or "")
        external_id = str(service.get("ID") or "")
        port = int(labels.get("edu.platform.workspace_port", 8080))
        return RuntimeResult(
            external_id=external_id,
            endpoint=f"http://tasks.{name}:{port}",
            metadata={
                "driver": "DOCKER_SWARM",
                "service_id": external_id,
                "service_name": name,
                "task_id": str(labels.get("edu.platform.task", "")),
                "course_id": str(labels.get("edu.platform.course", "")),
                "student_id": str(labels.get("edu.platform.student", "")),
                "instance_id": str(labels.get("edu.platform.instance", "")),
                "config_ref": self.config_ref,
                "spec_digest": str(labels.get("edu.platform.spec_digest", "")),
                "workspace_port": port,
                "managed": True,
            },
        )

    def create(self, spec: RuntimeSpec, idempotency_key: str) -> RuntimeResult:
        idempotency_digest = self._idempotency_digest(idempotency_key)
        spec_digest = self._spec_digest(spec)
        existing = self._existing(idempotency_digest)
        if existing:
            result = self._result(existing[0])
            if result.metadata.get("spec_digest") != spec_digest:
                raise RuntimeAdapterFailure("RUNTIME_IDEMPOTENCY_CONFLICT", retryable=False)
            return result

        service_name = self._safe_name(spec.task_id)
        labels = {
            MANAGED_LABEL: "true",
            KIND_LABEL: RUNTIME_KIND,
            "edu.platform.task": spec.task_id,
            "edu.platform.course": spec.course_id,
            "edu.platform.student": spec.student_id,
            "edu.platform.trace": spec.trace_id,
            "edu.platform.idempotency": idempotency_digest,
            "edu.platform.spec_digest": spec_digest,
            "edu.platform.instance": spec.instance_public_id,
            "edu.platform.config_ref": self.config_ref,
            "edu.platform.service_name": service_name,
            "edu.platform.workspace_port": str(spec.workspace_port),
            "edu.platform.expires_at": str(int(time.time()) + max(spec.ttl_seconds, 0)),
        }
        upstream_token = workspace_upstream_token(
            instance_id=spec.instance_public_id or idempotency_key,
            task_id=spec.task_id,
            spec_digest=spec_digest,
        )
        secret_name = self._safe_name(
            f"{spec.task_id}:{idempotency_key}", prefix="experimental-platform-secret"
        )
        secret_ref: dict[str, object] | None = None
        if upstream_token and callable(getattr(self.client, "create_secret", None)):
            try:
                self.client.create_secret(
                    name=secret_name,
                    data=upstream_token.encode("ascii"),
                    labels={**labels, KIND_LABEL: "workspace-secret"},
                )
            except Exception as exc:
                raise RuntimeAdapterFailure("RUNTIME_SECRET_CREATE_FAILED") from exc
            secret_ref = {
                "SecretName": secret_name,
                "File": {
                    "Name": "workspace_upstream_token",
                    "UID": "10001",
                    "GID": "10001",
                    "Mode": 0o400,
                },
            }
        task_template: dict[str, Any] = {
            "ContainerSpec": {
                "Image": spec.image_ref,
                "Labels": labels,
                "ReadOnly": False,
                "Privileges": {"NoNewPrivileges": True},
                "Healthcheck": {
                    "Test": [
                        "CMD-SHELL",
                        (
                            f"curl -fsS -o /dev/null http://127.0.0.1:{spec.workspace_port}"
                            f"{spec.healthcheck_path} || exit 1"
                        ),
                    ],
                    "Interval": 10_000_000_000,
                    "Timeout": 3_000_000_000,
                    "Retries": 6,
                    "StartPeriod": 20_000_000_000,
                },
            },
            "Resources": {
                "Limits": {
                    "NanoCPUs": (spec.cpu_limit_millicores or spec.cpu_millicores)
                    * 1_000_000,
                    "MemoryBytes": (spec.memory_limit_mb or spec.memory_mb) * 1024 * 1024,
                },
                "Reservations": {
                    "NanoCPUs": spec.cpu_millicores * 1_000_000,
                    "MemoryBytes": spec.memory_mb * 1024 * 1024,
                },
            },
            "RestartPolicy": {"Condition": "none", "MaxAttempts": 1},
            "Placement": {"Constraints": ["node.labels.edu.role.runtime == true"]},
            "Networks": self._networks(spec),
        }
        if secret_ref is not None:
            container_spec = task_template["ContainerSpec"]
            if isinstance(container_spec, dict):
                container_spec["Secrets"] = [secret_ref]
        try:
            response = self.client.create_service(
                task_template=task_template,
                name=service_name,
                labels=labels,
                endpoint_spec={"Mode": "vip"},
                update_config={
                    "Parallelism": 1,
                    "Order": "start-first",
                    "FailureAction": "rollback",
                },
                rollback_config={"Parallelism": 1, "Order": "stop-first"},
            )
            service = self.client.inspect_service(response["ID"])
            result = self._result(service)
            if secret_ref is not None:
                self._service_secrets[result.external_id] = secret_name
            return result
        except Exception as exc:
            recovered = self._existing(idempotency_digest)
            if recovered:
                result = self._result(recovered[0])
                if secret_ref is not None:
                    self._service_secrets[result.external_id] = secret_name
                raise RuntimeAdapterFailure(
                    "RUNTIME_CREATE_UNCONFIRMED", partial=True, result=result
                ) from exc
            if secret_ref is not None and callable(getattr(self.client, "remove_secret", None)):
                with suppress(Exception):
                    self.client.remove_secret(secret_name)
            raise RuntimeAdapterFailure("RUNTIME_CREATE_FAILED") from exc

    def _status_once(self, external_id: str) -> str:
        try:
            self.client.inspect_service(external_id)
        except Exception:
            return "ABSENT"
        tasks = self._call(
            "RUNTIME_STATUS_FAILED", lambda: self.client.tasks(filters={"service": external_id})
        )
        if not tasks:
            return "CREATING"
        states = {str(task.get("Status", {}).get("State", "")).casefold() for task in tasks}
        if states & {"failed", "rejected", "orphaned"}:
            raise RuntimeAdapterFailure("RUNTIME_TASK_FAILED")
        if "running" in states:
            running_task = next(
                task
                for task in tasks
                if str(task.get("Status", {}).get("State", "")).casefold() == "running"
            )
            container_id = str(
                running_task.get("Status", {}).get("ContainerStatus", {}).get("ContainerID", "")
            )
            if container_id and hasattr(self.client, "inspect_container"):
                container = self._call(
                    "RUNTIME_STATUS_FAILED",
                    lambda: self.client.inspect_container(container_id),
                )
                health_status = str(
                    container.get("State", {}).get("Health", {}).get("Status", "")
                ).casefold()
                if health_status == "unhealthy":
                    raise RuntimeAdapterFailure("RUNTIME_HEALTH_FAILED")
                if health_status == "starting":
                    return "CREATING"
            return "READY"
        return "CREATING"

    def status(self, external_id: str) -> str:
        timeout = _config_int(self.config.get("boot_timeout", settings.SWARM_BOOT_TIMEOUT_SECONDS))
        poll_interval = _config_float(
            self.config.get("poll_interval", settings.SWARM_POLL_INTERVAL_SECONDS)
        )
        deadline = time.monotonic() + max(timeout, 0)
        while True:
            status = self._status_once(external_id)
            if status in {"READY", "ABSENT"}:
                return status
            if time.monotonic() >= deadline:
                raise TimeoutError("RUNTIME_BOOT_TIMEOUT")
            time.sleep(max(poll_interval, 0.05))

    def endpoint(self, external_id: str) -> str:
        service = self._call(
            "RUNTIME_SERVICE_QUERY_FAILED", lambda: self.client.inspect_service(external_id)
        )
        return self._result(service).endpoint

    def snapshot(self, external_id: str) -> str:
        self._call("RUNTIME_SERVICE_QUERY_FAILED", lambda: self.client.inspect_service(external_id))
        return f"swarm-service:{external_id}"

    def _running_container_id(self, external_id: str) -> str:
        tasks = self._call(
            "RUNTIME_STATUS_FAILED", lambda: self.client.tasks(filters={"service": external_id})
        )
        for task in tasks:
            status = task.get("Status", {}) if isinstance(task, Mapping) else {}
            if str(status.get("State", "")).casefold() != "running":
                continue
            container_id = str(status.get("ContainerStatus", {}).get("ContainerID", ""))
            if container_id:
                return container_id
        raise RuntimeAdapterFailure("WORKSPACE_VOLUME_UNAVAILABLE")

    def _workspace_adapter(self) -> DockerLocalAdapter:
        # The Engine API has the same get/put archive and exec operations for
        # Swarm task containers.  The helper contains the shared path and
        # atomic-write validation without exposing a second public adapter API.
        return DockerLocalAdapter(
            client=self.client,
            config={"runtime_network": self._network_name()},
            config_ref="runtime/swarm-workspace",
        )

    def capture_workspace(
        self, *, external_id: str, relative_path: str, max_bytes: int
    ) -> RuntimeWorkspaceArtifact:
        container_id = self._running_container_id(external_id)
        return self._workspace_adapter().capture_workspace(
            external_id=container_id,
            relative_path=relative_path,
            max_bytes=max_bytes,
        )

    def restore_workspace(
        self,
        *,
        external_id: str,
        relative_path: str,
        content: bytes,
        expected_digest: str,
    ) -> None:
        container_id = self._running_container_id(external_id)
        self._workspace_adapter().restore_workspace(
            external_id=container_id,
            relative_path=relative_path,
            content=content,
            expected_digest=expected_digest,
        )

    def destroy(self, external_id: str, idempotency_key: str) -> None:
        del idempotency_key
        try:
            service = self.client.inspect_service(external_id)
        except Exception:
            return
        labels = service.get("Spec", {}).get("Labels", {})
        if labels.get(MANAGED_LABEL) != "true" or labels.get(KIND_LABEL) != RUNTIME_KIND:
            raise RuntimeAdapterFailure("RUNTIME_RESOURCE_NOT_MANAGED", retryable=False)
        self._call("RUNTIME_DESTROY_FAILED", lambda: self.client.remove_service(external_id))
        secret_name = self._service_secrets.pop(external_id, "")
        if secret_name and callable(getattr(self.client, "remove_secret", None)):
            with suppress(Exception):
                self.client.remove_secret(secret_name)

    def inventory(self) -> list[RuntimeInventoryItem]:
        services = self._call(
            "RUNTIME_SERVICE_QUERY_FAILED",
            lambda: self.client.services(
                filters={"label": [f"{MANAGED_LABEL}=true", f"{KIND_LABEL}={RUNTIME_KIND}"]}
            ),
        )
        result: list[RuntimeInventoryItem] = []
        for service in services:
            runtime = self._result(service)
            try:
                status = self._status_once(runtime.external_id)
            except RuntimeAdapterFailure:
                status = "FAILED"
            labels = service.get("Spec", {}).get("Labels", {})
            tasks = self._call(
                "RUNTIME_STATUS_FAILED",
                lambda service_id=runtime.external_id: self.client.tasks(
                    filters={"service": service_id}
                ),
            )
            result.append(
                RuntimeInventoryItem(
                    external_id=runtime.external_id,
                    status=status,
                    metadata={
                        **dict(runtime.metadata),
                        "task_id": str(labels.get("edu.platform.task", "")),
                        "course_id": str(labels.get("edu.platform.course", "")),
                        "managed": True,
                        "task_count": len(tasks),
                        "health": status,
                    },
                )
            )
        return result

    def health(self) -> Mapping[str, object]:
        try:
            self.client.ping()
            info = self.client.info()
            swarm = info.get("Swarm", {})
            nodes = self.client.nodes(filters={"node.label": ["edu.role.runtime=true"]})
            nodes = [
                node
                for node in nodes
                if node.get("Status", {}).get("State", "ready") == "ready"
                and node.get("Spec", {}).get("Availability", "active") == "active"
            ]
            cpu = (
                sum(
                    int(node.get("Description", {}).get("Resources", {}).get("NanoCPUs", 0))
                    for node in nodes
                )
                // 1_000_000
            )
            memory = sum(
                int(node.get("Description", {}).get("Resources", {}).get("MemoryBytes", 0))
                for node in nodes
            ) // (1024 * 1024)
            active = str(swarm.get("LocalNodeState", "")).casefold() == "active"
            reserved_cpu = 0
            reserved_memory = 0
            services = self.client.services(filters={"label": [f"{MANAGED_LABEL}=true"]})
            for service in services:
                service_spec = service.get("Spec", {})
                resources = service_spec.get("TaskTemplate", {}).get("Resources", {})
                reservations = resources.get("Reservations", {})
                replicas = int(
                    service_spec.get("Mode", {}).get("Replicated", {}).get("Replicas", 1)
                )
                reserved_cpu += int(reservations.get("NanoCPUs", 0)) * replicas // 1_000_000
                reserved_memory += (
                    int(reservations.get("MemoryBytes", 0)) * replicas // (1024 * 1024)
                )
            return {
                "status": "HEALTHY" if active and nodes else "DEGRADED",
                "node_count": len(nodes),
                "capacity_cpu_millicores": cpu,
                "available_cpu_millicores": max(0, cpu - reserved_cpu),
                "capacity_memory_mb": memory,
                "available_memory_mb": max(0, memory - reserved_memory),
                "driver": "DOCKER_SWARM",
            }
        except Exception:
            return {
                "status": "UNAVAILABLE",
                "node_count": 0,
                "capacity_cpu_millicores": 0,
                "available_cpu_millicores": 0,
                "capacity_memory_mb": 0,
                "available_memory_mb": 0,
                "driver": "DOCKER_SWARM",
            }

    def coordinate_capacity(
        self, spec: RuntimeSpec, *, idempotency_key: str, replicas: int
    ) -> RuntimeResult:
        if replicas < 0:
            raise RuntimeAdapterFailure("RUNTIME_CAPACITY_INVALID", retryable=False)
        self.preflight(spec)
        digest = self._idempotency_digest(idempotency_key)
        existing = list(
            self._call(
                "RUNTIME_CAPACITY_QUERY_FAILED",
                lambda: self.client.services(
                    filters={
                        "label": [
                            f"{MANAGED_LABEL}=true",
                            f"{KIND_LABEL}={CAPACITY_KIND}",
                            f"edu.platform.idempotency={digest}",
                        ]
                    }
                ),
            )
        )
        if replicas == 0:
            if existing:
                self._call(
                    "RUNTIME_CAPACITY_RELEASE_FAILED",
                    lambda: self.client.remove_service(existing[0]["ID"]),
                )
            return RuntimeResult(external_id="", metadata={"replicas": 0})
        if existing:
            service = existing[0]
            current = int(
                service.get("Spec", {}).get("Mode", {}).get("Replicated", {}).get("Replicas", 0)
            )
            if current != replicas:
                self._call(
                    "RUNTIME_CAPACITY_SCALE_FAILED",
                    lambda: self.client.update_service(
                        service["ID"],
                        version=service["Version"]["Index"],
                        mode={"Replicated": {"Replicas": replicas}},
                    ),
                )
                service = self.client.inspect_service(service["ID"])
            return RuntimeResult(
                external_id=str(service["ID"]),
                metadata={"driver": "DOCKER_SWARM", "managed": True, "replicas": replicas},
            )
        name = self._safe_name(idempotency_key, prefix="experimental-platform-warmup")
        labels = {
            MANAGED_LABEL: "true",
            KIND_LABEL: CAPACITY_KIND,
            "edu.platform.course": spec.course_id,
            "edu.platform.idempotency": digest,
            "edu.platform.expires_at": str(int(time.time()) + max(spec.ttl_seconds, 0)),
        }
        task_template = {
            "ContainerSpec": {
                "Image": spec.image_ref,
                "Labels": labels,
                "Privileges": {"NoNewPrivileges": True},
            },
            "Resources": {
                "Limits": {
                    "NanoCPUs": spec.cpu_millicores * 1_000_000,
                    "MemoryBytes": spec.memory_mb * 1024 * 1024,
                },
                "Reservations": {
                    "NanoCPUs": spec.cpu_millicores * 1_000_000,
                    "MemoryBytes": spec.memory_mb * 1024 * 1024,
                },
            },
            "RestartPolicy": {"Condition": "any", "Delay": 5_000_000_000},
            "Placement": {"Constraints": ["node.labels.edu.role.runtime == true"]},
            "Networks": self._networks(spec),
        }
        response = self._call(
            "RUNTIME_CAPACITY_CREATE_FAILED",
            lambda: self.client.create_service(
                task_template=task_template,
                name=name,
                labels=labels,
                mode={"Replicated": {"Replicas": replicas}},
                endpoint_spec={"Mode": "vip"},
                update_config={"Parallelism": 1, "FailureAction": "rollback"},
                rollback_config={"Parallelism": 1},
            ),
        )
        return RuntimeResult(
            external_id=str(response["ID"]),
            metadata={"driver": "DOCKER_SWARM", "managed": True, "replicas": replicas},
        )

    def release_capacity(self, *, idempotency_key: str) -> None:
        digest = self._idempotency_digest(idempotency_key)
        services = self._call(
            "RUNTIME_CAPACITY_QUERY_FAILED",
            lambda: self.client.services(
                filters={
                    "label": [
                        f"{MANAGED_LABEL}=true",
                        f"{KIND_LABEL}={CAPACITY_KIND}",
                        f"edu.platform.idempotency={digest}",
                    ]
                }
            ),
        )
        for service in services:
            self._call(
                "RUNTIME_CAPACITY_RELEASE_FAILED",
                lambda service_id=service["ID"]: self.client.remove_service(service_id),
            )

    def destroy_judge(self, judge_id: str, idempotency_key: str = "") -> None:
        """Remove all managed one-shot judge containers for ``judge_id``.

        A missing container is success.  Label checks are mandatory so a cleanup
        retry can never remove an unrelated user container.
        """

        del idempotency_key
        containers = self._call(
            "RUNTIME_JUDGE_QUERY_FAILED",
            lambda: self.client.containers(
                all=True,
                filters={
                    "label": [
                        f"{MANAGED_LABEL}=true",
                        f"{KIND_LABEL}=judge",
                        f"edu.platform.judge={judge_id}",
                    ]
                },
            ),
        )
        for container in containers:
            container_id = str(container.get("Id") or container.get("ID") or "")
            if not container_id:
                continue
            self._call(
                "RUNTIME_JUDGE_DESTROY_FAILED",
                lambda container_id=container_id: self.client.remove_container(
                    container_id, force=True, v=True
                ),
            )

    def inventory_resources(self) -> list[RuntimeInventoryItem]:
        """List managed transient judge containers for reconciliation."""

        containers = self._call(
            "RUNTIME_RESOURCE_QUERY_FAILED",
            lambda: self.client.containers(
                all=True,
                filters={"label": [f"{MANAGED_LABEL}=true", f"{KIND_LABEL}=judge"]},
            ),
        )
        result: list[RuntimeInventoryItem] = []
        for container in containers:
            labels = container.get("Labels", {}) or {}
            external_id = str(labels.get("edu.platform.judge") or container.get("Id") or "")
            if not external_id:
                continue
            result.append(
                RuntimeInventoryItem(
                    external_id=external_id,
                    status=str(container.get("State") or "UNKNOWN").upper(),
                    metadata={
                        "driver": "DOCKER_SWARM",
                        "managed": labels.get(MANAGED_LABEL) == "true",
                        "kind": "judge",
                        "task_id": str(labels.get("edu.platform.task", "")),
                        "judge_id": external_id,
                    },
                )
            )
        return result

    def destroy_resource(self, external_id: str, idempotency_key: str = "") -> None:
        """Generic transient-resource hook; currently judge resources are supported."""

        self.destroy_judge(external_id, idempotency_key)

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
        tests: bytes = b"",
        execution_plan: Mapping[str, list[str]] | None = None,
    ) -> RuntimeExecutionResult:
        """One-shot judging is unavailable for this Swarm adapter.

        Keep this method explicit so queued execution fails safely instead of
        falling back to an unrestricted shell.
        """

        del spec, command, source, timeout_seconds, memory_mb, cpu_millicores, network_mode, tests
        del execution_plan
        raise RuntimeAdapterFailure("RUNTIME_EXECUTION_NOT_IMPLEMENTED", retryable=False)


_fake_runtime = FakeRuntimeAdapter()
_docker_local_protocol_stubs: dict[str, DockerLocalProtocolStub] = {}
_docker_local_adapters: dict[str, DockerLocalAdapter] = {}


def fake_runtime() -> FakeRuntimeAdapter:
    return _fake_runtime


def reset_fake_runtime() -> None:
    _fake_runtime.failures.clear()
    _fake_runtime.timeouts.clear()
    _fake_runtime.partial_success.clear()
    _fake_runtime.instances.clear()
    _fake_runtime.capacities.clear()
    _fake_runtime.judge_instances.clear()
    _fake_runtime.volumes.clear()
    _fake_runtime.calls.clear()


def docker_local_protocol_stub(
    config_ref: str = "runtime/local-algorithm",
) -> DockerLocalProtocolStub:
    """Return the stable in-memory stub for one local runtime configuration."""

    clean_ref = config_ref.strip()
    if not clean_ref:
        raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False)
    stub = _docker_local_protocol_stubs.get(clean_ref)
    if stub is None:
        stub = DockerLocalProtocolStub(config_ref=clean_ref)
        _docker_local_protocol_stubs[clean_ref] = stub
    return stub


def reset_docker_local_protocol_stub() -> None:
    for stub in _docker_local_protocol_stubs.values():
        stub.failures.clear()
        stub.timeouts.clear()
        stub.partial_success.clear()
        stub.instances.clear()
        stub.capacities.clear()
        stub.judge_instances.clear()
        stub.volumes.clear()
        stub.calls.clear()
    _docker_local_protocol_stubs.clear()
    _docker_local_adapters.clear()


def runtime_for_driver(driver: str, *, config_ref: str = "") -> RuntimeAdapter:
    if driver == "FAKE":
        return _fake_runtime
    if driver == "DOCKER_LOCAL":
        if str(getattr(settings, "LOCAL_RUNTIME_MODE", "REAL")).upper() == "REAL":
            clean_ref = config_ref.strip()
            if not clean_ref:
                raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False)
            adapter = _docker_local_adapters.get(clean_ref)
            if adapter is None:
                configs = settings.RUNTIME_ADAPTER_CONFIGS
                config = configs.get(clean_ref, {}) if isinstance(configs, Mapping) else {}
                adapter = DockerLocalAdapter(config=config, config_ref=clean_ref)
                _docker_local_adapters[clean_ref] = adapter
            return adapter
        return docker_local_protocol_stub(config_ref)
    if driver == "DOCKER_SWARM":
        configs = settings.RUNTIME_ADAPTER_CONFIGS
        config = configs.get(config_ref, {}) if isinstance(configs, Mapping) else {}
        return DockerSwarmAdapter(config=config, config_ref=config_ref)
    raise RuntimeAdapterFailure("RUNTIME_ADAPTER_NOT_IMPLEMENTED", retryable=False)


def runtime_adapter_for(code: str) -> RuntimeAdapter:
    """Resolve the configured runtime mode without exposing driver details to callers."""

    mode = str(getattr(settings, "RUNTIME_MODE", "local")).strip().lower()
    clean_code = (code or str(getattr(settings, "RUNTIME_ADAPTER_CODE", ""))).strip()
    if mode not in {"fake", "local", "swarm"}:
        raise RuntimeAdapterFailure("RUNTIME_MODE_INVALID", retryable=False)
    if mode == "fake":
        return _fake_runtime
    if not clean_code:
        raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False)
    configs = getattr(settings, "RUNTIME_ADAPTER_CONFIGS", {})
    if not isinstance(configs, Mapping) or clean_code not in configs:
        raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False)
    config = configs[clean_code]
    if not isinstance(config, Mapping):
        raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False)
    if mode == "local":
        adapter = _docker_local_adapters.get(clean_code)
        if adapter is None:
            adapter = DockerLocalAdapter(config=config, config_ref=clean_code)
            _docker_local_adapters[clean_code] = adapter
        return adapter
    return DockerSwarmAdapter(config=config, config_ref=clean_code)

"""Docker image administration and health; student execution uses StdioExecutor."""
import io
import json
import re
from collections.abc import Mapping
from contextlib import suppress
from typing import Any

from django.conf import settings


class RuntimeAdapterFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = True,
        partial: bool = False,
        result: Any = None,
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


class DockerLocalAdapter:
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

    def _call(self, code: str, operation: Any) -> Any:
        try:
            return operation()
        except RuntimeAdapterFailure:
            raise
        except Exception as exc:
            raise RuntimeAdapterFailure(code) from exc

    def build_image(
        self,
        *,
        registry: str,
        repository: str,
        tag: str,
        context: Mapping[str, Any],
        build_args: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if not settings.RUNTIME_IMAGE_OPERATIONS_ENABLED:
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_OPERATIONS_DISABLED", retryable=False)
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
        if not settings.RUNTIME_IMAGE_OPERATIONS_ENABLED:
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_OPERATIONS_DISABLED", retryable=False)
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

    def health(self) -> Mapping[str, object]:
        try:
            self.client.ping()
            info = self.client.info()
            cpu = int(info.get("NCPU", 0)) * 1000
            memory = int(info.get("MemTotal", 0)) // (1024 * 1024)
            if settings.RUNTIME_CAPACITY_CPU_MILLICORES > 0:
                cpu = min(cpu, settings.RUNTIME_CAPACITY_CPU_MILLICORES)
            if settings.RUNTIME_CAPACITY_MEMORY_MB > 0:
                memory = min(memory, settings.RUNTIME_CAPACITY_MEMORY_MB)
            return {
                "status": "HEALTHY",
                "node_count": 1,
                "capacity_cpu_millicores": cpu,
                "available_cpu_millicores": cpu,
                "capacity_memory_mb": memory,
                "available_memory_mb": memory,
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


def runtime_for_driver(driver: str, *, config_ref: str = "") -> DockerLocalAdapter:
    if driver != "DOCKER_LOCAL":
        raise RuntimeAdapterFailure("RUNTIME_ADAPTER_NOT_SUPPORTED", retryable=False)
    if settings.LOCAL_RUNTIME_MODE != "REAL":
        raise RuntimeAdapterFailure("REAL_DOCKER_REQUIRED", retryable=False)
    if not config_ref.strip():
        raise RuntimeAdapterFailure("RUNTIME_CONFIG_INVALID", retryable=False)
    config = settings.RUNTIME_ADAPTER_CONFIGS.get(config_ref, {})
    return DockerLocalAdapter(config=config, config_ref=config_ref)

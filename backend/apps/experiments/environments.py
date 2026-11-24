"""Course-scoped runtime configuration, testing and live usage samples."""

from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import docker
from celery import shared_task
from django.conf import settings
from django.core.cache import caches
from django.utils import timezone

from apps.core.errors import StateConflict
from apps.governance.models import ImageAsset, RuntimeAdapter
from apps.labtemplates.toolchains import TOOLCHAINS_BY_LANGUAGE
from apps.provisioning.stdio import StdioExecutor

from .models import TeachingEnvironment

ENVIRONMENT_LABEL = "edu.platform.environment"
TOOLCHAINS = tuple(TOOLCHAINS_BY_LANGUAGE)
PROBES = {
    "python": ("main.py", 'print("environment-ok")'),
    "c": ("main.c", '#include <stdio.h>\nint main(void) { puts("environment-ok"); }'),
    "cpp": ("main.cpp", '#include <iostream>\nint main() { std::cout << "environment-ok\\n"; }'),
    "java": (
        "Main.java",
        'class Main { public static void main(String[] a) { '
        'System.out.println("environment-ok"); } }',
    ),
    "go": ("main.go", 'package main\nimport "fmt"\nfunc main() { fmt.Println("environment-ok") }'),
}


def approved_resources() -> tuple[Any, Any]:
    return (
        RuntimeAdapter.objects.filter(driver="DOCKER_LOCAL", status="ENABLED"),
        ImageAsset.objects.filter(approval_status="APPROVED", scan_status="CLEAN")
        .exclude(
            digest__isnull=True,
        )
        .exclude(digest=""),
    )


def validate_environment(environment: TeachingEnvironment) -> None:
    adapter = environment.runtime_adapter
    if adapter.driver != "DOCKER_LOCAL" or adapter.status != "ENABLED":
        raise StateConflict(detail={"environment": "runtime_not_enabled"})
    if not environment.image.is_ready:
        raise StateConflict(detail={"environment": "image_not_approved"})
    if (
        adapter.capacity_cpu_millicores
        and environment.cpu_millicores > adapter.capacity_cpu_millicores
    ) or (adapter.capacity_memory_mb and environment.memory_mb > adapter.capacity_memory_mb):
        raise StateConflict(detail={"environment": "runtime_capacity_exceeded"})


def config_for(environment: TeachingEnvironment) -> dict[str, Any]:
    adapter = environment.runtime_adapter
    image = environment.image
    return {
        "environment_id": environment.public_id,
        "name": environment.name,
        "language": environment.language,
        "cpu_millicores": environment.cpu_millicores,
        "memory_mb": environment.memory_mb,
        "runtime_adapter_id": adapter.public_id,
        "runtime_adapter_driver": adapter.driver,
        "runtime_adapter_config_ref": adapter.config_ref,
        "image_id": image.public_id,
        "image_registry": image.registry,
        "image_repository": image.repository,
        "image_digest": image.digest,
    }


def _docker_host(config_ref: str) -> str:
    config = settings.RUNTIME_ADAPTER_CONFIGS.get(config_ref, {})
    return str(config.get("base_url", config.get("docker_host", settings.LOCAL_DOCKER_HOST)))


@contextmanager
def runtime_client(config_ref: str) -> Any:
    if settings.LOCAL_RUNTIME_MODE != "REAL":
        raise RuntimeError("A real Docker Local runtime is required")
    client = docker.DockerClient(base_url=_docker_host(config_ref), timeout=12)
    try:
        yield client
    finally:
        client.close()


def runtime_cache() -> Any:
    return caches["lab_runtime"]


def test_key(environment: TeachingEnvironment, request_id: str) -> str:
    return f"lab-environment:{environment.public_id}:test:{request_id}"


def usage_key(environment: TeachingEnvironment) -> str:
    return f"lab-environment:{environment.public_id}:v{environment.row_version}:usage"


def request_test(environment: TeachingEnvironment, snapshot: dict[str, Any] | None = None) -> str:
    if snapshot is None:
        validate_environment(environment)
    config = snapshot if snapshot is not None else config_for(environment)
    request_id = uuid4().hex
    key = test_key(environment, request_id)
    cache = runtime_cache()
    cache.set(key, {"status": "QUEUED"}, 900)
    try:
        run_environment_test.apply_async(args=[key, config], queue="q_provision")
    except Exception:
        cache.set(key, {"status": "FAILED", "reason": "worker_unavailable"}, 900)
    return request_id


@shared_task
def run_environment_test(key: str, config: dict[str, Any]) -> None:
    cache = runtime_cache()
    cache.set(key, {"status": "RUNNING"}, 900)
    result: dict[str, Any] = {"status": "FAILED", "reason": "runtime_unavailable"}
    try:
        language = config["language"]
        filename, code = PROBES[language]
        image_ref = (
            f"{config['image_registry'].rstrip('/')}/{config['image_repository']}"
            f"@{config['image_digest']}"
        ).removeprefix("docker.io/library/")
        with runtime_client(config["runtime_adapter_config_ref"]) as client:
            client.images.get(image_ref)
            executor = StdioExecutor(
                client,
                image_ref,
                owner=f"environment-test-{uuid4().hex}",
                cpu_millicores=config["cpu_millicores"],
                environment_id=config["environment_id"],
            )
            try:
                compilation, outputs = executor.execute(
                    language=language,
                    files={filename: code},
                    inputs=[""],
                    timeout_seconds=8,
                    memory_mb=config["memory_mb"],
                    compile_memory_mb=config["memory_mb"],
                )
                execution = compilation or outputs[0]
                passed = (
                    execution.status == "PASSED" and execution.stdout.strip() == "environment-ok"
                )
                result = {
                    "status": "PASSED" if passed else "FAILED",
                    "stdout": execution.stdout[:1000],
                    "stderr": execution.stderr[:1000],
                    "reason": "" if passed else execution.status,
                }
            finally:
                executor.close()
    except Exception:
        pass
    cache.set(key, {**result, "checked_at": timezone.now().isoformat()}, 900)


def request_usage(environment: TeachingEnvironment) -> dict[str, Any]:
    cache = runtime_cache()
    key = usage_key(environment)
    dispatch = key + ":dispatch"
    try:
        if cache.add(dispatch, True, 30):
            config = config_for(environment)
            config["previous_config_refs"] = list(
                environment.publications.filter(runtime_adapter_driver="DOCKER_LOCAL")
                .values_list("runtime_adapter_config_ref", flat=True)
                .distinct(),
            )
            sample_environment_usage.apply_async(
                args=[key, config],
                queue="q_provision",
            )
        return cache.get(key) or {"status": "PENDING"}
    except Exception:
        return {"status": "UNAVAILABLE"}


@shared_task
def sample_environment_usage(key: str, config: dict[str, Any]) -> None:
    count = memory = 0
    cpu = 0.0
    try:
        refs = [config["runtime_adapter_config_ref"], *config.get("previous_config_refs", [])]
        for config_ref in {_docker_host(ref): ref for ref in refs}.values():
            with runtime_client(config_ref) as client:
                containers = client.containers.list(
                    filters={"label": f"{ENVIRONMENT_LABEL}={config['environment_id']}"},
                )
                for container in containers:
                    data = container.stats(stream=False)
                    before, after = data["precpu_stats"], data["cpu_stats"]
                    system_delta = after["system_cpu_usage"] - before["system_cpu_usage"]
                    used_delta = (
                        after["cpu_usage"]["total_usage"] - before["cpu_usage"]["total_usage"]
                    )
                    online = after.get("online_cpus") or len(
                        after["cpu_usage"].get("percpu_usage", [])
                    )
                    if system_delta <= 0 or not online:
                        raise RuntimeError("Docker CPU sample unavailable")
                    cpu += max(0, used_delta) / system_delta * online * 1000
                    memory += data["memory_stats"]["usage"]
                    count += 1
        result = {
            "status": "AVAILABLE",
            "containers": count,
            "cpu_millicores": round(cpu),
            "memory_bytes": memory,
        }
    except Exception:
        result = {"status": "UNAVAILABLE"}
    runtime_cache().set(key, {**result, "sampled_at": timezone.now().isoformat()}, 45)

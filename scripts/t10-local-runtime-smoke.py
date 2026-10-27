from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_PACKAGE = ROOT / "backend" / "education_experiment_platform"
sys.path.insert(0, str(BACKEND_PACKAGE))
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "education_experiment_platform.settings.integration"
)

import django  # noqa: E402

django.setup()

from apps.provisioning.adapters import (  # noqa: E402, I001
    DockerLocalAdapter,
    RuntimeAdapterFailure,
)
from apps.provisioning.ports import RuntimeSpec  # noqa: E402


DIGEST_PATTERN = re.compile(r"@(?P<digest>sha256:[0-9a-f]{64})$")


def resolve_image(adapter: DockerLocalAdapter, reference: str) -> tuple[str, str]:
    inspected = adapter.client.inspect_image(reference)
    repo_digests = inspected.get("RepoDigests") or []
    for value in repo_digests:
        match = DIGEST_PATTERN.search(str(value))
        if match:
            repository, _, _ = str(value).rpartition("@")
            return repository, match.group("digest")
    raise RuntimeError(f"image {reference!r} has no immutable RepoDigests sha256 reference")


def build_spec(task_id: str, repository: str, digest: str, run_id: str) -> RuntimeSpec:
    return RuntimeSpec(
        task_id=task_id,
        course_id=f"t10-course-{run_id}",
        student_id=f"t10-student-{run_id}",
        runtime_type="CONTAINER",
        image_registry="local",
        image_repository=repository,
        image_digest=digest,
        resource_profile_id="t10-local-profile",
        cpu_millicores=1000,
        memory_mb=768,
        disk_gb=1,
        network_policy={"mode": "DENY_ALL"},
        workspace_capabilities={
            "webide": True,
            "notebook": False,
            "terminal": False,
            "preview": False,
        },
        ttl_seconds=300,
        workspace_port=8080,
        healthcheck_path="/healthz",
        trace_id=uuid.uuid4().hex,
    )


def execute(
    adapter: DockerLocalAdapter,
    runtime_spec: RuntimeSpec,
    *,
    judge_id: str,
    source: bytes,
    tests: dict[str, object],
    timeout: int = 3,
    memory_mb: int = 64,
) -> str:
    result = adapter.execute_judge(
        spec=runtime_spec,
        command=["python", "main.py"],
        source=source,
        tests=json.dumps(tests).encode(),
        timeout_seconds=timeout,
        memory_mb=memory_mb,
        cpu_millicores=250,
        network_mode="DENY_ALL",
        judge_id=judge_id,
    )
    return result.status


def run_p16_probe(adapter: DockerLocalAdapter, container_id: str) -> dict[str, object]:
    execution = adapter.client.exec_create(
        container_id,
        [
            "python",
            "-c",
            "import pathlib,sys; pathlib.Path('/tmp/p16-smoke.py').write_bytes("
            "sys.stdin.buffer.read())",
        ],
        user="10001:10001",
        stdin=True,
    )
    exec_id = execution["Id"] if isinstance(execution, dict) else execution
    stage_socket = adapter.client.exec_start(exec_id, detach=False, socket=True)
    probe_source = (ROOT / "runtime" / "algorithm-workspace" / "tests" / "smoke.py").read_bytes()
    stage_socket.sendall(probe_source)
    stage_socket.close()
    stage_result = adapter.client.exec_inspect(exec_id)
    deadline = time.monotonic() + 10
    while stage_result.get("ExitCode") is None and time.monotonic() < deadline:
        time.sleep(0.05)
        stage_result = adapter.client.exec_inspect(exec_id)
    if int(stage_result.get("ExitCode", 1)) != 0:
        raise RuntimeError("Docker exec could not stage the P16 probe")

    execution = adapter.client.exec_create(
        container_id, ["python", "/tmp/p16-smoke.py"], user="10001:10001"
    )
    exec_id = execution["Id"] if isinstance(execution, dict) else execution
    output = adapter.client.exec_start(exec_id, detach=False)
    result = adapter.client.exec_inspect(exec_id)
    exit_code = int(result.get("ExitCode", 1))
    text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
    if exit_code != 0:
        raise RuntimeError(f"P16 container probe failed with exit code {exit_code}: {text[-1000:]}")
    for line in reversed(text.splitlines()):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError("P16 container probe returned no JSON result")


def main() -> None:
    run_id = uuid.uuid4().hex[:12]
    network = os.environ.get("T10_RUNTIME_NETWORK", "edu-platform-p14_runtime")
    image_reference = os.environ.get("T10_RUNTIME_IMAGE", "edu-platform-algorithm-workspace:local")
    config_ref = f"runtime/t10-local-{run_id}"
    task_id = f"t10-local-smoke-{run_id}"
    adapter = DockerLocalAdapter(
        config={
            "image": image_reference,
            "runtime_network": network,
            "boot_timeout": 60,
            "poll_interval": 0.2,
            "pids_limit": int(os.environ.get("T10_PIDS_LIMIT", "128")),
        },
        config_ref=config_ref,
    )
    repository, digest = resolve_image(adapter, image_reference)
    runtime_spec = build_spec(task_id, repository, digest, run_id)
    created = None
    summary: dict[str, object] = {
        "run_id": run_id,
        "image_repository": repository,
        "image_digest": digest,
    }
    try:
        adapter.preflight(runtime_spec)
        adapter.prepare_image(runtime_spec)
        try:
            created = adapter.create(runtime_spec, f"{task_id}:create")
        except RuntimeAdapterFailure as error:
            if error.partial and error.result is not None:
                created = error.result
            raise
        replay = adapter.create(runtime_spec, f"{task_id}:create")
        assert replay.external_id == created.external_id
        assert adapter.status(created.external_id) == "READY"

        inspected = adapter.client.inspect_container(created.external_id)
        host_config = inspected["HostConfig"]
        labels = inspected["Config"]["Labels"]
        network_settings = inspected.get("NetworkSettings") or {}
        assert labels["edu.platform.managed"] == "true"
        assert host_config["ReadonlyRootfs"] is True
        assert "ALL" in host_config["CapDrop"]
        assert "no-new-privileges:true" in host_config["SecurityOpt"]
        assert host_config["Memory"] == runtime_spec.memory_mb * 1024 * 1024
        assert host_config["NanoCpus"] == runtime_spec.cpu_millicores * 1_000_000
        assert host_config["PidsLimit"] == int(os.environ.get("T10_PIDS_LIMIT", "128"))
        assert not network_settings.get("Ports")

        p16_result = run_p16_probe(adapter, created.external_id)
        assert p16_result.get("capabilities") == {
            "webide": True,
            "notebook": False,
            "terminal": False,
            "preview": False,
        }
        assert p16_result.get("health") == "passed"
        assert p16_result.get("http") == "passed"
        assert p16_result.get("websocket") == "passed"

        execution_status = {
            "correct": execute(
                adapter, runtime_spec, judge_id=f"{task_id}-correct",
                source=b"value = int(input())\nprint(value * 2)\n",
                tests={"cases": [{"input": "3\n", "expected": "6\n"}]},
            ),
            "wrong": execute(
                adapter, runtime_spec, judge_id=f"{task_id}-wrong",
                source=b"print(0)\n",
                tests={"cases": [{"input": "3\n", "expected": "6\n"}]},
            ),
            "timeout": execute(
                adapter, runtime_spec, judge_id=f"{task_id}-timeout",
                source=b"while True:\n    pass\n", tests={"cases": [{"input": ""}]}, timeout=1,
            ),
            "suite_timeout": execute(
                adapter, runtime_spec, judge_id=f"{task_id}-suite-timeout",
                source=b"import time\ntime.sleep(0.6)\nprint(1)\n",
                tests={"cases": [{"input": ""}, {"input": ""}]}, timeout=1,
            ),
            "resource_exceeded": execute(
                adapter, runtime_spec, judge_id=f"{task_id}-oom",
                source=(b"items = []\nwhile True:\n    items.append('x' * (4 * 1024 * 1024))\n"),
                tests={"cases": [{"input": ""}]}, timeout=8, memory_mb=48,
            ),
        }
        assert execution_status == {
            "correct": "PASSED", "wrong": "FAILED", "timeout": "TIMEOUT",
            "suite_timeout": "TIMEOUT", "resource_exceeded": "RESOURCE_EXCEEDED",
        }
        summary.update(
            {
                "workspace": "READY",
                "idempotent_create": True,
                "p16": p16_result,
                "execution": execution_status,
            }
        )
    finally:
        if created is not None:
            adapter.destroy(created.external_id, f"{task_id}:destroy")
            adapter.destroy(created.external_id, f"{task_id}:destroy")
        for resource in list(adapter.inventory_resources()):
            adapter.destroy_resource(resource.external_id, f"{task_id}:resource-destroy")
        remaining_workspaces = adapter.inventory()
        remaining_resources = adapter.inventory_resources()
        summary["cleanup"] = {
            "workspaces": len(remaining_workspaces),
            "resources": len(remaining_resources),
        }
        print(json.dumps(summary, sort_keys=True))
        if remaining_workspaces or remaining_resources:
            raise RuntimeError("managed runtime resources remain after smoke cleanup")


if __name__ == "__main__":
    main()

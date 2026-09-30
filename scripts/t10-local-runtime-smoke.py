from __future__ import annotations

import json
import os
import urllib.request

import django

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "education_experiment_platform.settings.integration"
)
django.setup()

from apps.provisioning.adapters import DockerLocalAdapter  # noqa: E402
from apps.provisioning.ports import RuntimeSpec  # noqa: E402


def spec() -> RuntimeSpec:
    return RuntimeSpec(
        task_id="t10-local-smoke",
        course_id="t10-course",
        student_id="t10-student",
        runtime_type="CONTAINER",
        image_registry="local",
        image_repository="edu-platform-algorithm-workspace",
        image_digest="sha256:" + "a" * 64,
        resource_profile_id="t10-local-profile",
        cpu_millicores=250,
        memory_mb=192,
        disk_gb=1,
        network_policy={"mode": "DENY_ALL"},
        workspace_capabilities={
            "webide": True,
            "terminal": True,
            "preview": True,
        },
        ttl_seconds=300,
        workspace_port=8080,
        healthcheck_path="/healthz",
        trace_id="10" * 16,
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


def main() -> None:
    network = os.environ.get("T10_RUNTIME_NETWORK", "edu-platform-p14_runtime")
    adapter = DockerLocalAdapter(
        config={
            "image": "edu-platform-algorithm-workspace:local",
            "runtime_network": network,
            "boot_timeout": 45,
            "poll_interval": 0.2,
        },
        config_ref="runtime/local-docker",
    )
    runtime_spec = spec()
    created = None
    summary: dict[str, object] = {}
    try:
        adapter.preflight(runtime_spec)
        adapter.prepare_image(runtime_spec)
        created = adapter.create(runtime_spec, "t10-local-smoke:create")
        replay = adapter.create(runtime_spec, "t10-local-smoke:create")
        assert replay.external_id == created.external_id
        assert adapter.status(created.external_id) == "READY"

        inspected = adapter.client.inspect_container(created.external_id)
        host_config = inspected["HostConfig"]
        labels = inspected["Config"]["Labels"]
        assert labels["edu.platform.managed"] == "true"
        assert host_config["ReadonlyRootfs"] is True
        assert "ALL" in host_config["CapDrop"]
        assert "no-new-privileges:true" in host_config["SecurityOpt"]
        assert host_config["Memory"] == runtime_spec.memory_mb * 1024 * 1024
        assert host_config["NanoCpus"] == runtime_spec.cpu_millicores * 1_000_000
        assert host_config["PidsLimit"] == 64

        endpoint = adapter.endpoint(created.external_id)
        http_status: dict[str, int] = {}
        for path in ("/healthz", "/webide/", "/terminal/", "/preview/"):
            with urllib.request.urlopen(endpoint + path, timeout=5) as response:
                http_status[path] = response.status
        assert set(http_status.values()) == {200}

        execution_status = {
            "correct": execute(
                adapter,
                runtime_spec,
                judge_id="t10-correct",
                source=b"value = int(input())\nprint(value * 2)\n",
                tests={"cases": [{"input": "3\n", "expected": "6\n"}]},
            ),
            "wrong": execute(
                adapter,
                runtime_spec,
                judge_id="t10-wrong",
                source=b"print(0)\n",
                tests={"cases": [{"input": "3\n", "expected": "6\n"}]},
            ),
            "timeout": execute(
                adapter,
                runtime_spec,
                judge_id="t10-timeout",
                source=b"while True:\n    pass\n",
                tests={"cases": [{"input": ""}]},
                timeout=1,
            ),
            "suite_timeout": execute(
                adapter,
                runtime_spec,
                judge_id="t10-suite-timeout",
                source=b"import time\ntime.sleep(0.6)\nprint(1)\n",
                tests={"cases": [{"input": ""}, {"input": ""}]},
                timeout=1,
            ),
            "resource_exceeded": execute(
                adapter,
                runtime_spec,
                judge_id="t10-oom",
                source=(
                    b"items = []\n"
                    b"while True:\n"
                    b"    items.append('x' * (4 * 1024 * 1024))\n"
                ),
                tests={"cases": [{"input": ""}]},
                timeout=8,
                memory_mb=48,
            ),
        }
        assert execution_status == {
            "correct": "PASSED",
            "wrong": "FAILED",
            "timeout": "TIMEOUT",
            "suite_timeout": "TIMEOUT",
            "resource_exceeded": "RESOURCE_EXCEEDED",
        }
        judge_residue = [
            item.external_id
            for item in adapter.inventory_resources()
            if item.metadata.get("kind") == "judge"
        ]
        assert judge_residue == []
        summary.update(
            {
                "workspace": "READY",
                "idempotent_create": True,
                "http": http_status,
                "execution": execution_status,
                "judge_residue": judge_residue,
                "security": {
                    "readonly_rootfs": True,
                    "cap_drop_all": True,
                    "no_new_privileges": True,
                    "pids_limit": 64,
                },
            }
        )
    finally:
        if created is not None:
            adapter.destroy(created.external_id, "t10-local-smoke:destroy")
            adapter.destroy(created.external_id, "t10-local-smoke:destroy")
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

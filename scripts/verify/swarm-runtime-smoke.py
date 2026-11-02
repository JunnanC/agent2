# Swarm 运行时适配器连通性探针；HTTP/WebSocket 断言仍针对参考工作区协议。
"""Run a bounded Docker Swarm adapter smoke test against the local Engine."""

from __future__ import annotations

import argparse
import os
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--network", default="experimental-platform-swarm-runtime")
    parser.add_argument("--task-id", default="swarm-smoke-task")
    parser.add_argument("--course-id", default="swarm-smoke-course")
    parser.add_argument("--student-id", default="swarm-smoke-student")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if not args.digest.startswith("sha256:"):
        parser.error("--digest must be a sha256 digest")

    backend = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
    sys.path.insert(0, os.path.abspath(backend))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "education_experiment_platform.settings.test")
    import django

    django.setup()
    import docker

    from apps.provisioning.adapters import DockerSwarmAdapter
    from apps.provisioning.ports import RuntimeSpec

    client = docker.from_env(version="auto", timeout=args.timeout).api
    adapter = DockerSwarmAdapter(
        client=client,
        config={
            "runtime_network": args.network,
            "skip_manager_pull": True,
            "boot_timeout": args.timeout,
            "poll_interval": 1,
        },
    )
    spec = RuntimeSpec(
        task_id=args.task_id,
        course_id=args.course_id,
        student_id=args.student_id,
        runtime_type="CONTAINER",
        image_registry=args.registry,
        image_repository=args.repository,
        image_digest=args.digest,
        resource_profile_id="swarm-smoke-profile",
        cpu_millicores=100,
        memory_mb=128,
        disk_gb=1,
        network_policy={"mode": "DENY_ALL"},
        workspace_capabilities={"webide": True, "notebook": True, "terminal": True, "preview": True},
        ttl_seconds=600,
        workspace_port=8080,
        healthcheck_path="/healthz",
        trace_id="swarm-runtime-smoke",
    )
    result = None
    try:
        adapter.preflight(spec)
        result = adapter.create(spec, "swarm-runtime-smoke")
        status = adapter.status(result.external_id)
        if status != "READY":
            raise RuntimeError(f"runtime did not become READY: {status}")
        task_rows = client.tasks(filters={"service": result.external_id})
        container_id = str(
            task_rows[0].get("Status", {}).get("ContainerStatus", {}).get("ContainerID", "")
        )
        if not container_id:
            raise RuntimeError("ready service has no container id")

        def exec_checked(command: list[str]) -> bytes:
            exec_id = client.exec_create(container_id, command)["Id"]
            output = client.exec_start(exec_id, demux=False)
            inspect = client.exec_inspect(exec_id)
            if int(inspect.get("ExitCode", 1)) != 0:
                raise RuntimeError(f"workspace contract command failed: {command[0]}")
            return output if isinstance(output, bytes) else b"".join(output)

        for capability in ("webide", "notebook", "terminal", "preview"):
            body = exec_checked(["curl", "-fsS", f"http://127.0.0.1:8080/{capability}/"])
            if capability.title().encode() not in body:
                raise RuntimeError(f"workspace capability response missing: {capability}")
        websocket_probe = (
            "import asyncio\n"
            "from websockets.asyncio.client import connect\n"
            "async def main():\n"
            "    async with connect('ws://127.0.0.1:8080/terminal/') as ws:\n"
            "        await ws.recv()\n"
            "        await ws.send('swarm-smoke')\n"
            "        assert await ws.recv() == 'swarm-smoke'\n"
            "asyncio.run(main())\n"
        )
        exec_checked(["python", "-c", websocket_probe])
        inventory = adapter.inventory()
        if not any(item.external_id == result.external_id for item in inventory):
            raise RuntimeError("created service missing from managed inventory")
        print(f"created external_id={result.external_id} status={status} http=4/4 websocket=ok")
    finally:
        if result is not None:
            adapter.destroy(result.external_id, "swarm-runtime-smoke-destroy")
            deadline = time.monotonic() + args.timeout
            while adapter.status(result.external_id) != "ABSENT":
                if time.monotonic() >= deadline:
                    raise RuntimeError("destroy was not confirmed before timeout")
                time.sleep(1)
    remaining = [item.external_id for item in adapter.inventory()]
    if remaining:
        raise RuntimeError(f"managed runtime inventory is not empty: {remaining}")
    print("destroyed status=ABSENT inventory=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

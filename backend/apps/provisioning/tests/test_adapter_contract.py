import io
import json
import tarfile
import time
from typing import Any
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.core.project_archive import bundle

from ..adapters import (
    DockerLocalAdapter,
    DockerLocalProtocolStub,
    RuntimeAdapterFailure,
    docker_local_protocol_stub,
    fake_runtime,
    reset_docker_local_protocol_stub,
    reset_fake_runtime,
    runtime_adapter_for,
    runtime_for_driver,
)
from ..ports import RuntimeSpec


def runtime_spec(**overrides: Any) -> RuntimeSpec:
    values: dict[str, Any] = {
        "task_id": "01TASKOPAQUE",
        "course_id": "01COURSEOPAQUE",
        "student_id": "01STUDENTOPAQUE",
        "runtime_type": "CONTAINER",
        "image_registry": "registry.example.edu",
        "image_repository": "labs/python",
        "image_digest": "sha256:" + "a" * 64,
        "resource_profile_id": "01PROFILE",
        "cpu_millicores": 500,
        "memory_mb": 256,
        "disk_gb": 2,
        "network_policy": {"mode": "DENY_ALL"},
        "workspace_capabilities": {"webide": True, "terminal": True},
        "ttl_seconds": 300,
        "workspace_port": 8080,
        "healthcheck_path": "/healthz",
        "trace_id": "a" * 32,
    }
    values.update(overrides)
    return RuntimeSpec(**values)


class RuntimeAdapterContractTests(SimpleTestCase):
    def setUp(self) -> None:
        reset_fake_runtime()
        reset_docker_local_protocol_stub()

    def tearDown(self) -> None:
        reset_fake_runtime()
        reset_docker_local_protocol_stub()

    def test_fake_and_docker_local_implement_the_same_protocol_surface(self) -> None:
        required_methods = (
            "preflight",
            "prepare_image",
            "attach_network",
            "create",
            "status",
            "endpoint",
            "snapshot",
            "destroy",
            "inventory",
            "health",
            "coordinate_capacity",
            "release_capacity",
            "destroy_judge",
            "inventory_resources",
            "destroy_resource",
        )
        for adapter in (fake_runtime(), docker_local_protocol_stub()):
            with self.subTest(adapter=type(adapter).__name__):
                self.assertTrue(
                    all(callable(getattr(adapter, name, None)) for name in required_methods)
                )

    def test_docker_local_stub_runs_the_six_stage_protocol_without_docker(self) -> None:
        adapter = docker_local_protocol_stub("runtime/local-algorithm")
        spec = runtime_spec()

        adapter.preflight(spec)
        adapter.prepare_image(spec)
        created = adapter.create(spec, "provisioning:job-1")
        adapter.attach_network(spec)
        self.assertEqual(adapter.status(created.external_id), "READY")
        self.assertEqual(adapter.endpoint(created.external_id), created.endpoint)

        replay = adapter.create(spec, "provisioning:job-1")
        self.assertEqual(replay, created)
        self.assertEqual(
            [stage for stage, _ in adapter.calls],
            [
                "QUOTA_CHECK",
                "IMAGE_PREPARE",
                "CREATE",
                "NETWORK_ATTACH",
                "BOOT_PROBE",
                "WORKSPACE_READY",
                "CREATE",
            ],
        )
        self.assertEqual(created.metadata["driver"], "DOCKER_LOCAL")
        self.assertTrue(created.metadata["protocol_stub"])
        self.assertEqual(adapter.inventory()[0].external_id, created.external_id)
        self.assertEqual(adapter.health()["driver"], "DOCKER_LOCAL")

        adapter.destroy(created.external_id, "destroy:job-1")
        self.assertEqual(adapter.status(created.external_id), "ABSENT")
        self.assertEqual(adapter.inventory(), [])

    def test_docker_local_stub_preserves_partial_create_compensation(self) -> None:
        adapter = docker_local_protocol_stub()
        adapter.failures["CREATE"] = "LOCAL_CREATE_UNCONFIRMED"
        adapter.partial_success.add("CREATE")

        with self.assertRaises(RuntimeAdapterFailure) as raised:
            adapter.create(runtime_spec(), "provisioning:job-2")

        self.assertEqual(raised.exception.code, "LOCAL_CREATE_UNCONFIRMED")
        self.assertTrue(raised.exception.partial)
        self.assertIsNotNone(raised.exception.result)
        result = raised.exception.result
        assert result is not None
        self.assertEqual(adapter.status(result.external_id), "READY")
        adapter.destroy(result.external_id, "destroy:job-2")
        self.assertEqual(adapter.status(result.external_id), "ABSENT")

    def test_driver_resolution_keeps_fake_isolated_from_local_stub(self) -> None:
        fake = runtime_for_driver("FAKE")
        local = runtime_for_driver("DOCKER_LOCAL", config_ref="runtime/local-algorithm")

        self.assertIs(fake, fake_runtime())
        self.assertIsInstance(local, DockerLocalProtocolStub)
        self.assertIsNot(local, fake)
        self.assertEqual(getattr(local, "config_ref", None), "runtime/local-algorithm")
        self.assertEqual(fake_runtime().calls, [])
        self.assertTrue(callable(getattr(local, "execute_judge", None)))

    @override_settings(RUNTIME_MODE="fake", RUNTIME_ADAPTER_CODE="runtime/fake")
    def test_fake_mode_resolves_with_capabilities(self) -> None:
        adapter = runtime_adapter_for("runtime/fake")

        self.assertIs(adapter, fake_runtime())
        self.assertEqual(
            adapter.capabilities(),
            {
                "image_build": True,
                "real_container": False,
                "resource_limits": True,
                "workspace_access": False,
            },
        )

    @override_settings(RUNTIME_MODE="fake", RUNTIME_ADAPTER_CODE="runtime/fake")
    def test_fake_mode_reports_workspace_access_as_unsupported(self) -> None:
        adapter = runtime_adapter_for("runtime/fake")

        self.assertFalse(adapter.capabilities()["workspace_access"])
        with self.assertRaises(RuntimeAdapterFailure) as raised:
            adapter.capture_workspace(
                external_id="fake-runtime:1",
                relative_path="main.py",
                max_bytes=1024,
            )

        self.assertEqual(raised.exception.code, "WORKSPACE_CAPTURE_UNSUPPORTED")

    @override_settings(
        RUNTIME_MODE="local",
        LOCAL_RUNTIME_MODE="REAL",
        RUNTIME_ADAPTER_CODE="runtime/local-docker",
        RUNTIME_ADAPTER_CONFIGS={"runtime/local-docker": {"runtime_network": "edu-runtime"}},
    )
    def test_local_mode_resolves_the_real_local_adapter(self) -> None:
        with patch(
            "apps.provisioning.adapters.DockerLocalAdapter._build_client",
            return_value=object(),
        ):
            adapter = runtime_adapter_for("runtime/local-docker")

        self.assertIsInstance(adapter, DockerLocalAdapter)
        self.assertEqual(adapter.capabilities()["real_container"], True)

    @override_settings(
        RUNTIME_MODE="swarm",
        RUNTIME_ADAPTER_CODE="runtime/swarm",
        RUNTIME_ADAPTER_CONFIGS={"runtime/swarm": {"runtime_network": "edu-runtime"}},
    )
    def test_swarm_mode_resolves_the_swarm_adapter(self) -> None:
        with patch(
            "apps.provisioning.adapters.DockerSwarmAdapter._build_client",
            return_value=object(),
        ):
            adapter = runtime_adapter_for("runtime/swarm")

        self.assertEqual(type(adapter).__name__, "DockerSwarmAdapter")
        self.assertEqual(
            adapter.capabilities(),
            {
                "image_build": True,
                "real_container": True,
                "resource_limits": True,
                "workspace_access": True,
            },
        )

    @override_settings(RUNTIME_MODE="unknown", RUNTIME_ADAPTER_CODE="runtime/unknown")
    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(RuntimeAdapterFailure) as raised:
            runtime_adapter_for("runtime/unknown")

        self.assertEqual(raised.exception.code, "RUNTIME_MODE_INVALID")
        self.assertFalse(raised.exception.retryable)

    @override_settings(
        RUNTIME_MODE="swarm", RUNTIME_ADAPTER_CODE="runtime/swarm", RUNTIME_ADAPTER_CONFIGS={}
    )
    def test_production_mode_requires_adapter_configuration(self) -> None:
        with self.assertRaises(RuntimeAdapterFailure) as raised:
            runtime_adapter_for("runtime/swarm")

        self.assertEqual(raised.exception.code, "RUNTIME_CONFIG_INVALID")
        self.assertFalse(raised.exception.retryable)

    def test_local_driver_requires_a_configuration_reference(self) -> None:
        with self.assertRaises(RuntimeAdapterFailure) as raised:
            runtime_for_driver("DOCKER_LOCAL")

        self.assertEqual(raised.exception.code, "RUNTIME_CONFIG_INVALID")
        self.assertFalse(raised.exception.retryable)

    def test_local_judge_and_volume_cleanup_are_idempotent_and_managed(self) -> None:
        adapter = docker_local_protocol_stub("runtime/local-algorithm")
        spec = runtime_spec(ttl_seconds=300)
        created = adapter.create(spec, "provisioning:job-cleanup")
        resources = adapter.inventory_resources()
        self.assertTrue(any(item.metadata.get("kind") == "volume" for item in resources))

        result = adapter.execute_judge(
            spec=spec,
            command=["python", "main.py"],
            source=b"print('ok')",
            tests=b"assert True",
            timeout_seconds=5,
            memory_mb=128,
            cpu_millicores=250,
            network_mode="DENY_ALL",
            judge_id="judge-cleanup-1",
        )
        self.assertEqual(result.status, "PASSED")
        self.assertTrue(
            any(item.external_id == "judge-cleanup-1" for item in adapter.inventory_resources())
        )
        adapter.destroy_judge("judge-cleanup-1", "judge-destroy:judge-cleanup-1")
        adapter.destroy_judge("judge-cleanup-1", "judge-destroy:judge-cleanup-1")
        self.assertFalse(
            any(item.external_id == "judge-cleanup-1" for item in adapter.inventory_resources())
        )
        adapter.destroy_resource(f"volume:{created.external_id}", "resource-destroy:volume-cleanup")
        self.assertFalse(
            any(item.metadata.get("kind") == "volume" for item in adapter.inventory_resources())
        )


class FakeDockerEngine:
    """Small APIClient-shaped fake for local adapter contract tests."""

    def __init__(self) -> None:
        self.networks_state: list[dict[str, Any]] = []
        self.volumes_state: dict[str, dict[str, Any]] = {}
        self.containers_state: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.archives: list[bytes] = []
        self.next_id = 1
        self.judge_status = 0
        self.judge_oom = False
        self.judge_logs = '{"status": "PASSED", "cases": 1}\n'

    def ping(self) -> bool:
        return True

    def inspect_image(self, image: str) -> dict[str, Any]:
        self.calls.append(("inspect_image", {"image": image}))
        return {"Id": "sha256:image"}

    def networks(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        return self.networks_state

    def create_network(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("create_network", kwargs))
        network = {"Id": "network-1", **kwargs}
        self.networks_state = [network]
        return network

    def create_endpoint_config(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_endpoint_config", kwargs))
        return kwargs

    def create_networking_config(self, value: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_networking_config", {"value": value}))
        return value

    def create_host_config(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_host_config", kwargs))
        return kwargs

    def create_volume(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_volume", kwargs))
        name = str(kwargs["name"])
        if name in self.volumes_state:
            raise RuntimeError("already exists")
        volume = {"Name": name, "Labels": dict(kwargs.get("labels") or {}), **kwargs}
        self.volumes_state[name] = volume
        return volume

    def inspect_volume(self, name: str) -> dict[str, Any]:
        if name not in self.volumes_state:
            raise RuntimeError("not found")
        return self.volumes_state[name]

    def update_volume(self, name: str, labels: dict[str, str]) -> None:
        self.calls.append(("update_volume", {"name": name, "labels": labels}))
        if name not in self.volumes_state:
            raise RuntimeError("not found")
        self.volumes_state[name]["Labels"] = dict(labels)

    def remove_volume(self, name: str, force: bool = False) -> None:
        del force
        self.volumes_state.pop(name, None)

    def create_container(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("create_container", kwargs))
        container_id = f"container-{self.next_id}"
        self.next_id += 1
        labels = dict(kwargs.get("labels") or {})
        is_judge = (kwargs.get("labels") or {}).get("edu.platform.kind") == "judge"
        mount = {
            "Name": next(iter(self.volumes_state), ""),
            "Destination": "/workspace",
        }
        state = {
            "Running": not is_judge,
            "Status": "running" if not is_judge else "created",
            "Health": {"Status": "healthy"},
            "OOMKilled": False,
        }
        item = {
            "Id": container_id,
            "Name": f"/{kwargs.get('name', container_id)}",
            "Labels": labels,
            "Config": {"Labels": labels},
            "Mounts": [mount] if not is_judge else [],
            "State": state,
            "_is_judge": is_judge,
            "_kwargs": kwargs,
        }
        self.containers_state[container_id] = item
        return {"Id": container_id}

    def start(self, container_id: str) -> None:
        self.containers_state[container_id]["State"].update({"Running": True, "Status": "running"})

    def inspect_container(self, container_id: str) -> dict[str, Any]:
        if container_id not in self.containers_state:
            raise RuntimeError("not found")
        item = self.containers_state[container_id]
        if item.get("_is_judge"):
            item["State"].update({"OOMKilled": self.judge_oom, "Status": "exited"})
        return item

    def containers(
        self, all: bool = False, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        del all
        values = list(self.containers_state.values())
        labels = (filters or {}).get("label", [])
        for expression in labels:
            key, _, expected = str(expression).partition("=")
            values = [item for item in values if str(item["Labels"].get(key, "")) == expected]
        return values

    def remove_container(self, container_id: str, force: bool = False, v: bool = False) -> None:
        del force, v
        self.containers_state.pop(container_id, None)

    def put_archive(self, container_id: str, path: str, data: bytes) -> bool:
        self.archives.append(data)
        self.calls.append((
            "put_archive",
            {"container_id": container_id, "path": path, "size": len(data)},
        ))
        return True

    def wait(self, container_id: str, timeout: int | None = None) -> dict[str, int]:
        del container_id, timeout
        return {"StatusCode": self.judge_status}

    def logs(self, container_id: str, stdout: bool = False, stderr: bool = False) -> bytes:
        del container_id
        if stdout:
            return self.judge_logs.encode()
        if stderr:
            return b""
        return b""


class DockerLocalAdapterTests(SimpleTestCase):
    def test_docker_client_construction_failure_uses_runtime_error_contract(self) -> None:
        with (
            patch("docker.APIClient", side_effect=OSError("docker socket missing")),
            self.assertRaises(RuntimeAdapterFailure) as raised,
        ):
            DockerLocalAdapter(config_ref="runtime/local-docker")

        self.assertEqual(raised.exception.code, "RUNTIME_CLIENT_UNAVAILABLE")

    @override_settings(WORKSPACE_VOLUME_RETENTION_SECONDS=600)
    def test_workspace_applies_managed_security_resources_and_is_idempotent(self) -> None:
        client = FakeDockerEngine()
        adapter = DockerLocalAdapter(
            client=client,
            config={
                "image": "experimental-platform-workspace:local",
                "runtime_network": "edu-runtime",
            },
        )
        spec = runtime_spec()

        created = adapter.create(spec, "provisioning:local-1")
        replay = adapter.create(spec, "provisioning:local-1")

        self.assertEqual(created.external_id, replay.external_id)
        host_config = next(kwargs for name, kwargs in client.calls if name == "create_host_config")
        self.assertEqual(host_config["mem_limit"], "256m")
        self.assertEqual(host_config["nano_cpus"], 500_000_000)
        self.assertEqual(host_config["pids_limit"], 256)
        self.assertTrue(host_config["read_only"])
        self.assertEqual(host_config["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", host_config["security_opt"])
        labels = client.containers_state[created.external_id]["Labels"]
        self.assertEqual(labels["edu.platform.managed"], "true")
        self.assertEqual(client.networks_state[0]["driver"], "bridge")
        container_config = client.containers_state[created.external_id]["_kwargs"]
        self.assertEqual(container_config["image"], "experimental-platform-workspace:local")
        self.assertEqual(
            container_config["healthcheck"]["Test"],
            ["CMD", "/usr/local/bin/workspace-router", "healthcheck"],
        )
        with tarfile.open(fileobj=io.BytesIO(client.archives[0]), mode="r") as archive:
            secret = archive.getmember("workspace_upstream_token")
        self.assertEqual((secret.uid, secret.gid, secret.mode), (10001, 10001, 0o600))

        adapter.destroy(created.external_id, "destroy:local-1")
        adapter.destroy(created.external_id, "destroy:local-1")
        self.assertEqual(client.containers_state, {})
        self.assertEqual(len(client.volumes_state), 1)
        workspace_volume = next(iter(client.volumes_state.values()))
        self.assertGreater(
            int(workspace_volume["Labels"]["edu.platform.expires_at"]),
            int(time.time()),
        )
        adapter.destroy_resource(workspace_volume["Name"], "resource-destroy:local-1")
        self.assertEqual(client.volumes_state, {})

    def test_workspace_uses_resource_limits_while_admission_values_are_requests(self) -> None:
        client = FakeDockerEngine()
        adapter = DockerLocalAdapter(
            client=client,
            config={
                "image": "experimental-platform-workspace:local",
                "runtime_network": "edu-runtime",
            },
        )
        spec = runtime_spec(
            cpu_millicores=500,
            memory_mb=256,
            cpu_limit_millicores=1500,
            memory_limit_mb=2048,
        )

        adapter.create(spec, "provisioning:local-limits")
        host_config = next(kwargs for name, kwargs in client.calls if name == "create_host_config")
        self.assertEqual(host_config["nano_cpus"], 1_500_000_000)
        self.assertEqual(host_config["mem_limit"], "2048m")

    def test_destroy_retains_creation_expiry_when_volume_updates_are_unavailable(self) -> None:
        client = FakeDockerEngine()
        client.__dict__["update_volume"] = None
        adapter = DockerLocalAdapter(client=client)
        created = adapter.create(runtime_spec(), "provisioning:local-no-volume-update")

        adapter.destroy(created.external_id, "destroy:local-no-volume-update")

        self.assertEqual(client.containers_state, {})
        self.assertEqual(len(client.volumes_state), 1)
        volume = next(iter(client.volumes_state.values()))
        self.assertGreater(int(volume["Labels"]["edu.platform.expires_at"]), int(time.time()))

    def test_judge_rejects_non_whitelisted_command_and_network(self) -> None:
        adapter = DockerLocalAdapter(client=FakeDockerEngine())
        spec = runtime_spec()
        with self.assertRaises(RuntimeAdapterFailure) as command_error:
            adapter.execute_judge(
                spec=spec,
                command=["sh", "-c", "id"],
                source=b"print('x')",
                tests=b"{}",
                timeout_seconds=2,
                memory_mb=64,
                cpu_millicores=100,
                network_mode="DENY_ALL",
                judge_id="judge-1",
            )
        self.assertEqual(command_error.exception.code, "RUNTIME_COMMAND_NOT_ALLOWED")

        for entrypoint in ("../main.py", "src/../../main.py", "/main.py", "src//main.py"):
            with self.subTest(entrypoint=entrypoint), self.assertRaises(RuntimeAdapterFailure):
                adapter.execute_judge(
                    spec=spec, command=["python", entrypoint], source=b"print(42)",
                    tests=b"{}", timeout_seconds=2, memory_mb=64, cpu_millicores=100,
                    network_mode="DENY_ALL", judge_id="judge-invalid-path",
                )

        with self.assertRaises(RuntimeAdapterFailure) as network_error:
            adapter.execute_judge(
                spec=spec,
                command=["python", "main.py"],
                source=b"print('x')",
                tests=b"{}",
                timeout_seconds=2,
                memory_mb=64,
                cpu_millicores=100,
                network_mode="ALLOWLIST",
                judge_id="judge-2",
            )
        self.assertEqual(network_error.exception.code, "RUNTIME_NETWORK_NOT_ALLOWED")

    def test_destroy_refuses_unmanaged_container(self) -> None:
        client = FakeDockerEngine()
        unmanaged = client.create_container(image="busybox", name="unmanaged", labels={})
        adapter = DockerLocalAdapter(client=client)

        with self.assertRaises(RuntimeAdapterFailure) as raised:
            adapter.destroy(unmanaged["Id"], "destroy:unmanaged")

        self.assertEqual(raised.exception.code, "RUNTIME_RESOURCE_NOT_MANAGED")
        self.assertIn(unmanaged["Id"], client.containers_state)

    def test_hidden_expected_values_are_not_staged_in_the_judge_volume(self) -> None:
        client = FakeDockerEngine()
        client.judge_logs = (
            '{"status":"PASSED","results":[{"status":"PASSED",'
            '"stdout":"42\\n","stderr":"","returncode":0}]}\n'
        )
        adapter = DockerLocalAdapter(client=client)

        result = adapter.execute_judge(
            spec=runtime_spec(),
            command=["python", "main.py"],
            source=b"print(42)",
            tests=b'{"cases":[{"input":"","expected":"hidden-value"}]}',
            timeout_seconds=2,
            memory_mb=64,
            cpu_millicores=100,
            network_mode="DENY_ALL",
            judge_id="judge-hidden",
        )

        self.assertEqual(result.status, "FAILED")
        self.assertEqual(len(client.archives), 1)
        with tarfile.open(fileobj=io.BytesIO(client.archives[0]), mode="r") as archive:
            names = archive.getnames()
            contents = b"".join(
                archive.extractfile(name).read()  # type: ignore[union-attr]
                for name in names
            )
        self.assertEqual(names, ["main.py", "runner.py"])
        self.assertNotIn(b"hidden-value", contents)

    def test_project_archive_stages_all_files_and_keeps_hidden_tests_out(self) -> None:
        client = FakeDockerEngine()
        adapter = DockerLocalAdapter(client=client)
        source = bundle({"src/main.py": b"print(42)", "lib.py": b"VALUE = 42"}, max_bytes=1024)
        adapter.execute_judge(
            spec=runtime_spec(), command=["python", "src/main.py"], source=source,
            tests=b'{"cases":[{"input":"","expected":"42"}]}', timeout_seconds=2,
            memory_mb=64, cpu_millicores=100, network_mode="DENY_ALL", judge_id="judge-project",
        )
        with tarfile.open(fileobj=io.BytesIO(client.archives[0]), mode="r") as archive:
            self.assertCountEqual(archive.getnames(), ["lib.py", "runner.py", "src/main.py"])

    def test_generic_cleanup_removes_stale_judge_and_stager(self) -> None:
        client = FakeDockerEngine()
        common = {
            "edu.platform.managed": "true",
            "edu.platform.judge": "judge-stale",
            "edu.platform.config_ref": "runtime/local-docker",
        }
        client.create_container(
            image="workspace",
            name="edu-judge-stale",
            labels={**common, "edu.platform.kind": "judge"},
        )
        client.create_container(
            image="workspace",
            name="edu-judge-stage-stale",
            labels={**common, "edu.platform.kind": "judge-stager"},
        )
        adapter = DockerLocalAdapter(client=client)

        adapter.destroy_resource("judge-stale", "cleanup:judge-stale")

        self.assertEqual(client.containers_state, {})

    def test_judge_marks_each_output_mismatch_as_failed(self) -> None:
        client = FakeDockerEngine()
        client.judge_logs = json.dumps({"status": "PASSED", "results": [
            {"status": "PASSED", "stdout": "0", "returncode": 0} for _ in range(4)
        ]}) + "\n"
        result = DockerLocalAdapter(client=client).execute_judge(
            spec=runtime_spec(), command=["python", "main.py"], source=b"print(0)",
            tests=json.dumps({"cases": [{"expected": value} for value in [5, 0, 1, 7]]}).encode(),
            timeout_seconds=2, memory_mb=64, cpu_millicores=100,
            network_mode="DENY_ALL", judge_id="judge-case-status",
        )
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(result.error_code, "RUNTIME_ALGORITHM_FAILED")
        self.assertEqual([item["status"] for item in result.test_report["results"]],
                         ["FAILED", "PASSED", "FAILED", "FAILED"])
        self.assertEqual(client.containers_state, {})

    def test_judge_distinguishes_compile_runtime_and_timeout_text(self) -> None:
        cases = [
            ({"status": "FAILED", "compile_stderr": "private helper error"},
             "FAILED", "RUNTIME_COMPILE_FAILED"),
            ({"status": "FAILED", "results": [{"status": "FAILED", "returncode": 7}]},
             "FAILED", "RUNTIME_EXECUTION_FAILED"),
            ({"status": "PASSED", "results": [
                {"status": "PASSED", "stdout": "TIMEOUT", "returncode": 0}
            ]}, "PASSED", ""),
        ]
        for report, status, error in cases:
            with self.subTest(error=error):
                client = FakeDockerEngine()
                client.judge_logs = json.dumps(report) + "\n"
                result = DockerLocalAdapter(client=client).execute_judge(
                    spec=runtime_spec(), command=["python", "main.py"], source=b"print('ok')",
                    tests=b"{}", timeout_seconds=2, memory_mb=64, cpu_millicores=100,
                    network_mode="DENY_ALL", judge_id="judge-error-stage",
                )
                self.assertEqual(result.status, status)
                self.assertEqual(result.error_code, error)
                self.assertEqual(client.containers_state, {})

    def test_judge_timeout_and_oom_are_reported_and_container_is_removed(self) -> None:
        client = FakeDockerEngine()
        adapter = DockerLocalAdapter(client=client)
        spec = runtime_spec()
        client.judge_status = 124
        client.judge_logs = '{"status": "TIMEOUT"}\n'
        timeout_result = adapter.execute_judge(
            spec=spec,
            command=["python", "main.py"],
            source=b"while True: pass",
            tests=b"{}",
            timeout_seconds=1,
            memory_mb=64,
            cpu_millicores=100,
            network_mode="DENY_ALL",
            judge_id="judge-timeout",
        )
        self.assertEqual(timeout_result.status, "TIMEOUT")
        self.assertEqual(client.containers_state, {})

        client.judge_status = 137
        client.judge_oom = True
        client.judge_logs = ""
        oom_result = adapter.execute_judge(
            spec=spec,
            command=["python", "main.py"],
            source=b"x = 'a' * 1024",
            tests=b"{}",
            timeout_seconds=1,
            memory_mb=64,
            cpu_millicores=100,
            network_mode="DENY_ALL",
            judge_id="judge-oom",
        )
        self.assertEqual(oom_result.status, "RESOURCE_EXCEEDED")
        self.assertEqual(client.containers_state, {})

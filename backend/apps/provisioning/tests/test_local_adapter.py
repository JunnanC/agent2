from typing import Any

from django.test import SimpleTestCase, override_settings

from ..adapters import DockerLocalAdapter, RuntimeAdapterFailure
from ..ports import RuntimeSpec


def runtime_spec(**overrides: object) -> RuntimeSpec:
    values: dict[str, Any] = {
        "task_id": "01TASKLOCAL",
        "course_id": "01COURSELOCAL",
        "student_id": "01STUDENTLOCAL",
        "runtime_type": "CONTAINER",
        "image_registry": "registry.example.edu",
        "image_repository": "labs/python",
        "image_digest": "sha256:" + "a" * 64,
        "resource_profile_id": "01PROFILELOCAL",
        "cpu_millicores": 500,
        "memory_mb": 256,
        "cpu_limit_millicores": 1500,
        "memory_limit_mb": 2048,
        "disk_gb": 2,
        "network_policy": {"mode": "DENY_ALL"},
        "workspace_capabilities": {"webide": True, "terminal": True},
        "ttl_seconds": 300,
        "workspace_port": 8080,
        "healthcheck_path": "/healthz",
        "trace_id": "a" * 32,
        "instance_public_id": "01INSTANCELOCAL",
    }
    values.update(overrides)
    return RuntimeSpec(**values)


class FakeLocalDockerClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.networks_state: list[dict[str, Any]] = []
        self.volumes_state: dict[str, dict[str, Any]] = {}
        self.containers_state: dict[str, dict[str, Any]] = {}
        self.next_id = 1

    def ping(self) -> bool:
        return True

    def info(self) -> dict[str, int]:
        return {"NCPU": 4, "MemTotal": 8 * 1024 * 1024 * 1024}

    def inspect_image(self, image: str) -> dict[str, str]:
        self.calls.append(("inspect_image", {"image": image}))
        return {"Id": "sha256:" + "b" * 64}

    def networks(self, *, names: list[str]) -> list[dict[str, Any]]:
        return [item for item in self.networks_state if item["Name"] in names]

    def create_network(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_network", kwargs))
        item = {"Id": "network-1", "Name": kwargs["name"], **kwargs}
        self.networks_state.append(item)
        return item

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
        self.volumes_state[name]["Labels"] = dict(labels)

    def remove_volume(self, name: str, force: bool = False) -> None:
        del force
        self.volumes_state.pop(name, None)

    def create_container(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("create_container", kwargs))
        container_id = f"container-{self.next_id}"
        self.next_id += 1
        labels = dict(kwargs.get("labels") or {})
        host_config = kwargs.get("host_config") or {}
        mounts = [
            {"Name": name, "Destination": bind["bind"]}
            for name, bind in (host_config.get("binds") or {}).items()
        ]
        item = {
            "Id": container_id,
            "Name": f"/{kwargs.get('name', container_id)}",
            "Labels": labels,
            "Config": {"Labels": labels},
            "Mounts": mounts,
            "State": {"Running": False, "Status": "created", "Health": {"Status": "healthy"}},
            "_kwargs": kwargs,
        }
        self.containers_state[container_id] = item
        return {"Id": container_id}

    def start(self, container_id: str) -> None:
        self.containers_state[container_id]["State"].update(
            {"Running": True, "Status": "running"}
        )

    def inspect_container(self, container_id: str) -> dict[str, Any]:
        if container_id not in self.containers_state:
            raise RuntimeError("not found")
        return self.containers_state[container_id]

    def containers(
        self, *, all: bool = False, filters: dict[str, list[str]] | None = None
    ) -> list[dict[str, Any]]:
        del all
        values = list(self.containers_state.values())
        for expression in (filters or {}).get("label", []):
            key, _, expected = str(expression).partition("=")
            values = [
                item
                for item in values
                if str(item["Labels"].get(key, "")) == expected
            ]
        return values

    def remove_container(self, container_id: str, force: bool = False, v: bool = False) -> None:
        del force, v
        self.containers_state.pop(container_id, None)

    def put_archive(self, container_id: str, path: str, data: bytes) -> bool:
        self.calls.append(
            (
                "put_archive",
                {"container_id": container_id, "path": path, "size": len(data)},
            )
        )
        return True


class DockerLocalAdapterTests(SimpleTestCase):
    def test_resource_names_are_readable_stable_and_distinct_after_truncation(self) -> None:
        adapter = self._adapter(FakeLocalDockerClient())
        spec = runtime_spec(task_id="01TASKLOCAL-LONG-TASK-IDENTIFIER")
        name = adapter._safe_name(spec.task_id)
        workspace = adapter._volume_name(spec, "provisioning:first")
        secret = adapter._secret_volume_name(spec, "provisioning:first")

        self.assertTrue(name.startswith("experimental-platform-lab-01tasklo-"))
        self.assertTrue(workspace.startswith("experimental-platform-workspace-01tasklo-"))
        self.assertTrue(secret.startswith("experimental-platform-secret-01tasklo-"))
        self.assertEqual(workspace, adapter._volume_name(spec, "provisioning:first"))
        self.assertNotEqual(workspace, adapter._volume_name(spec, "provisioning:second"))
        self.assertNotEqual(name, adapter._safe_name(spec.task_id + "-other"))
        for resource_name in (name, workspace, secret):
            self.assertLessEqual(len(resource_name), 63)
            self.assertRegex(resource_name, r"^[a-z0-9][a-z0-9-]+$")
            self.assertNotIn("provisionin", resource_name)

    def _adapter(self, client: FakeLocalDockerClient) -> DockerLocalAdapter:
        return DockerLocalAdapter(
            client=client,
            config={"runtime_network": "edu-runtime"},
            config_ref="runtime/local-test",
        )

    def test_local_registry_uses_the_docker_engine_repo_digest_reference(self) -> None:
        client = FakeLocalDockerClient()
        adapter = self._adapter(client)
        spec = runtime_spec(
            image_registry="local",
            image_repository="experimental-platform-workspace",
        )

        adapter.prepare_image(spec)

        self.assertEqual(
            client.calls[-1],
            ("inspect_image", {"image": "experimental-platform-workspace@" + spec.image_digest}),
        )

    @override_settings(WORKSPACE_VOLUME_RETENTION_SECONDS=600)
    def test_create_is_digest_pinned_limited_managed_and_idempotent(self) -> None:
        client = FakeLocalDockerClient()
        adapter = self._adapter(client)
        spec = runtime_spec()

        created = adapter.create(spec, "provisioning:local-1")
        replay = adapter.create(spec, "provisioning:local-1")

        self.assertEqual(created.external_id, replay.external_id)
        workspace_creates = [
            kwargs
            for name, kwargs in client.calls
            if name == "create_container"
            and str(kwargs["name"]).startswith("experimental-platform-lab-")
        ]
        self.assertEqual(len(workspace_creates), 1)
        self.assertEqual(workspace_creates[0]["image"], spec.image_ref)
        host_config = next(
            kwargs for name, kwargs in client.calls if name == "create_host_config"
        )
        self.assertEqual(host_config["nano_cpus"], 1_500_000_000)
        self.assertEqual(host_config["mem_limit"], "2048m")
        self.assertEqual(host_config["pids_limit"], 128)
        self.assertEqual(
            host_config["tmpfs"],
            {"/tmp": "rw,noexec,nosuid,size=128m,uid=10001,gid=10001"},
        )
        labels = client.containers_state[created.external_id]["Labels"]
        self.assertEqual(labels["edu.platform.managed"], "true")
        self.assertEqual(labels["edu.platform.kind"], "student-runtime")
        self.assertEqual(labels["edu.platform.config_ref"], "runtime/local-test")

        with self.assertRaises(RuntimeAdapterFailure) as conflict:
            adapter.create(
                runtime_spec(cpu_limit_millicores=2000), "provisioning:local-1"
            )
        self.assertEqual(conflict.exception.code, "RUNTIME_IDEMPOTENCY_CONFLICT")

    def test_invalid_limits_are_rejected_before_container_side_effects(self) -> None:
        client = FakeLocalDockerClient()
        adapter = self._adapter(client)

        with self.assertRaises(RuntimeAdapterFailure) as raised:
            adapter.create(
                runtime_spec(cpu_millicores=1500, cpu_limit_millicores=500),
                "provisioning:invalid-limits",
            )

        self.assertEqual(raised.exception.code, "RUNTIME_RESOURCE_LIMIT_INVALID")
        self.assertFalse(any(name == "create_volume" for name, _ in client.calls))

    def test_invalid_image_reference_is_rejected_before_container_side_effects(self) -> None:
        client = FakeLocalDockerClient()
        adapter = self._adapter(client)

        for invalid in (
            "registry.example.edu/labs/python:latest",
            "https://registry.example.edu",
            "registry.example.edu/ labs/python",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeAdapterFailure) as raised:
                adapter.create(
                    runtime_spec(image_registry=invalid),
                    f"provisioning:invalid-image:{invalid}",
                )
            self.assertEqual(raised.exception.code, "RUNTIME_IMAGE_REFERENCE_INVALID")
        self.assertFalse(any(name == "create_volume" for name, _ in client.calls))

    def test_inspect_failure_is_not_treated_as_absent(self) -> None:
        client = FakeLocalDockerClient()
        adapter = self._adapter(client)

        def fail_inspect(container_id: str) -> dict[str, Any]:
            del container_id
            raise RuntimeError("docker daemon unavailable")

        client.inspect_container = fail_inspect  # type: ignore[method-assign]
        with self.assertRaises(RuntimeAdapterFailure) as raised:
            adapter.status("container-unknown")
        self.assertEqual(raised.exception.code, "RUNTIME_CONTAINER_QUERY_FAILED")

    def test_secret_cleanup_can_be_retried_after_container_removal(self) -> None:
        client = FakeLocalDockerClient()
        adapter = self._adapter(client)
        created = adapter.create(runtime_spec(), "provisioning:local-secret-retry")
        secret_volume = next(
            name
            for name, item in client.volumes_state.items()
            if item["Labels"].get("edu.platform.kind") == "workspace-secret"
        )
        original_remove_volume = client.remove_volume
        failed_once = True

        def remove_volume(name: str, force: bool = False) -> None:
            nonlocal failed_once
            if name == secret_volume and failed_once:
                failed_once = False
                raise RuntimeError("volume busy")
            original_remove_volume(name, force=force)

        client.remove_volume = remove_volume  # type: ignore[method-assign]
        with self.assertRaises(RuntimeAdapterFailure):
            adapter.destroy(created.external_id, "destroy:local-secret-retry")
        self.assertNotIn(created.external_id, client.containers_state)
        self.assertIn(secret_volume, client.volumes_state)

        adapter.destroy(created.external_id, "destroy:local-secret-retry")
        self.assertNotIn(secret_volume, client.volumes_state)

    def test_destroy_is_managed_and_idempotent_but_rejects_foreign_resources(self) -> None:
        client = FakeLocalDockerClient()
        adapter = self._adapter(client)
        created = adapter.create(runtime_spec(), "provisioning:local-cleanup")
        workspace_volume = next(
            name
            for name, item in client.volumes_state.items()
            if item["Labels"].get("edu.platform.kind") == "volume"
        )

        adapter.destroy(created.external_id, "destroy:local-cleanup")
        adapter.destroy(created.external_id, "destroy:local-cleanup")

        self.assertNotIn(created.external_id, client.containers_state)
        self.assertIn(workspace_volume, client.volumes_state)
        adapter.destroy_resource(workspace_volume, "resource:local-cleanup")
        self.assertNotIn(workspace_volume, client.volumes_state)

        foreign = client.create_container(
            name="foreign-runtime",
            labels={
                "edu.platform.managed": "true",
                "edu.platform.kind": "student-runtime",
                "edu.platform.config_ref": "runtime/other",
            },
        )
        with self.assertRaises(RuntimeAdapterFailure) as raised:
            adapter.destroy(foreign["Id"], "destroy:foreign")
        self.assertEqual(raised.exception.code, "RUNTIME_RESOURCE_NOT_MANAGED")
        self.assertIn(foreign["Id"], client.containers_state)

    def test_inventory_is_scoped_to_this_adapter_configuration(self) -> None:
        client = FakeLocalDockerClient()
        adapter = self._adapter(client)
        adapter.create(runtime_spec(), "provisioning:local-inventory")
        client.create_container(
            name="other-runtime",
            labels={
                "edu.platform.managed": "true",
                "edu.platform.kind": "student-runtime",
                "edu.platform.config_ref": "runtime/other",
            },
        )

        inventory = adapter.inventory()

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0].metadata["config_ref"], "runtime/local-test")

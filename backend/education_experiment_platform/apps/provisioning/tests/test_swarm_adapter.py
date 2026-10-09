from typing import Any

from django.test import SimpleTestCase, override_settings

from ..adapters import (
    KIND_LABEL,
    MANAGED_LABEL,
    RUNTIME_KIND,
    DockerSwarmAdapter,
    RuntimeAdapterFailure,
)
from ..ports import RuntimeSpec


class FakeDockerClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.services_by_id: dict[str, dict[str, Any]] = {}
        self.network_values: list[dict[str, Any]] = []
        self.removed_services: list[str] = []
        self.removed_networks: list[str] = []
        self.pulled: list[str] = []
        self.built: list[dict[str, Any]] = []
        self.pushed: list[str] = []

    def ping(self) -> bool:
        return True

    def info(self) -> dict[str, Any]:
        return {"Swarm": {"LocalNodeState": "active"}}

    def pull(self, image_ref: str) -> None:
        self.pulled.append(image_ref)

    def build(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.built.append(kwargs)
        return [{"stream": "built"}]

    def push(self, image_ref: str, *, decode: bool = True) -> list[dict[str, Any]]:
        del decode
        self.pushed.append(image_ref)
        return [{"aux": {"Digest": "sha256:" + "b" * 64}}]

    def inspect_image(self, reference: str) -> dict[str, Any]:
        return {"RepoDigests": [f"{reference.split(':', 1)[0]}@sha256:{'b' * 64}"], "Id": ""}

    def networks(self, *, names: list[str]) -> list[dict[str, Any]]:
        return [item for item in self.network_values if item["Name"] in names]

    def create_network(self, **kwargs: Any) -> dict[str, str]:
        item = {"Id": "network-1", "Name": kwargs["name"], "Labels": kwargs["labels"]}
        self.network_values.append(item)
        return {"Id": item["Id"]}

    def remove_network(self, network_id: str) -> None:
        self.removed_networks.append(network_id)

    def services(self, *, filters: dict[str, list[str]]) -> list[dict[str, Any]]:
        labels = {
            value.split("=", 1)[0]: value.split("=", 1)[1]
            for value in filters.get("label", [])
        }
        return [
            service
            for service in self.services_by_id.values()
            if all(service["Spec"]["Labels"].get(key) == value for key, value in labels.items())
        ]

    def create_service(self, **kwargs: Any) -> dict[str, str]:
        self.created.append(kwargs)
        service_id = f"service-{len(self.created)}"
        self.services_by_id[service_id] = {
            "ID": service_id,
            "Spec": {"Name": kwargs["name"], "Labels": kwargs["labels"]},
        }
        return {"ID": service_id}

    def inspect_service(self, service_id: str) -> dict[str, Any]:
        if service_id not in self.services_by_id:
            raise RuntimeError("not found")
        return self.services_by_id[service_id]

    def tasks(self, *, filters: dict[str, str]) -> list[dict[str, Any]]:
        return (
            [{"Status": {"State": "running"}}]
            if filters["service"] in self.services_by_id
            else []
        )

    def remove_service(self, service_id: str) -> None:
        self.removed_services.append(service_id)
        self.services_by_id.pop(service_id, None)

    def nodes(self, *, filters: dict[str, list[str]]) -> list[dict[str, Any]]:
        del filters
        return [
            {
                "Description": {
                    "Resources": {"NanoCPUs": 4_000_000_000, "MemoryBytes": 8 * 1024**3}
                }
            }
        ]


class UnhealthyDockerClient(FakeDockerClient):
    def tasks(self, *, filters: dict[str, str]) -> list[dict[str, Any]]:
        return [
            {
                "Status": {
                    "State": "running",
                    "ContainerStatus": {"ContainerID": "container-1"},
                }
            }
        ]

    def inspect_container(self, container_id: str) -> dict[str, Any]:
        assert container_id == "container-1"
        return {"State": {"Health": {"Status": "unhealthy"}}}


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
        "memory_mb": 1024,
        "disk_gb": 10,
        "network_policy": {"mode": "DENY_ALL"},
        "workspace_capabilities": {"webide": True, "terminal": True},
        "ttl_seconds": 3600,
        "trace_id": "a" * 32,
    }
    values.update(overrides)
    return RuntimeSpec(**values)


@override_settings(SWARM_BOOT_TIMEOUT_SECONDS=0, SWARM_POLL_INTERVAL_SECONDS=0)
class DockerSwarmAdapterTests(SimpleTestCase):
    def setUp(self) -> None:
        self.client = FakeDockerClient()
        self.adapter = DockerSwarmAdapter(client=self.client, config={"boot_timeout": 0})

    def test_create_is_digest_pinned_restricted_and_idempotent(self) -> None:
        spec = runtime_spec()
        self.adapter.preflight(spec)
        self.adapter.prepare_image(spec)
        first = self.adapter.create(spec, "request-1")
        second = self.adapter.create(spec, "request-1")

        self.assertEqual(first.external_id, second.external_id)
        self.assertEqual(len(self.client.created), 1)
        request = self.client.created[0]
        task = request["task_template"]
        self.assertEqual(task["ContainerSpec"]["Image"], spec.image_ref)
        self.assertTrue(task["ContainerSpec"]["Privileges"]["NoNewPrivileges"])
        self.assertEqual(task["Placement"]["Constraints"], ["node.labels.edu.role.runtime == true"])
        self.assertEqual(task["Resources"]["Limits"]["NanoCPUs"], 500_000_000)
        self.assertNotIn("ports", request)
        self.assertNotIn("email", str(request).casefold())
        self.assertEqual(self.adapter.status(first.external_id), "READY")
        self.assertTrue(first.endpoint.startswith("http://tasks.edu-lab-"))

    def test_allowlist_without_approved_egress_network_fails_closed(self) -> None:
        with self.assertRaises(RuntimeAdapterFailure) as raised:
            self.adapter.create(
                runtime_spec(network_policy={"mode": "ALLOWLIST", "policy_ref": "course"}),
                "request-2",
            )
        self.assertEqual(raised.exception.code, "RUNTIME_EGRESS_POLICY_UNAVAILABLE")
        self.assertFalse(raised.exception.retryable)

    def test_destroy_rejects_unmanaged_service_and_cleans_managed_resources(self) -> None:
        spec = runtime_spec()
        result = self.adapter.create(spec, "request-3")
        self.adapter.destroy(result.external_id, "destroy-1")
        self.assertEqual(self.client.removed_services, [result.external_id])
        self.assertEqual(self.client.removed_networks, [])
        self.assertEqual(self.adapter.status(result.external_id), "ABSENT")

        self.client.services_by_id["foreign"] = {
            "ID": "foreign",
            "Spec": {"Name": "foreign", "Labels": {}},
        }
        with self.assertRaises(RuntimeAdapterFailure) as raised:
            self.adapter.destroy("foreign", "destroy-2")
        self.assertEqual(raised.exception.code, "RUNTIME_RESOURCE_NOT_MANAGED")

    def test_inventory_and_health_only_expose_managed_metadata(self) -> None:
        result = self.adapter.create(runtime_spec(), "request-4")
        inventory = self.adapter.inventory()
        health = self.adapter.health()

        self.assertEqual([item.external_id for item in inventory], [result.external_id])
        self.assertTrue(inventory[0].metadata["managed"])
        self.assertEqual(inventory[0].metadata["task_id"], "01TASKOPAQUE")
        self.assertEqual(health["status"], "HEALTHY")
        self.assertEqual(health["node_count"], 1)
        self.assertEqual(health["capacity_cpu_millicores"], 4000)

    def test_unhealthy_container_is_reported_as_a_stable_runtime_failure(self) -> None:
        client = UnhealthyDockerClient()
        client.services_by_id["service-unhealthy"] = {
            "ID": "service-unhealthy",
            "Spec": {
                "Name": "edu-lab-unhealthy",
                "Labels": {
                    MANAGED_LABEL: "true",
                    KIND_LABEL: RUNTIME_KIND,
                    "edu.platform.workspace_port": "8080",
                },
            },
        }
        adapter = DockerSwarmAdapter(client=client)
        with self.assertRaises(RuntimeAdapterFailure) as raised:
            adapter.status("service-unhealthy")
        self.assertEqual(raised.exception.code, "RUNTIME_HEALTH_FAILED")

    def test_invalid_numeric_config_is_rejected_as_a_stable_runtime_failure(self) -> None:
        adapter = DockerSwarmAdapter(client=self.client, config={"boot_timeout": object()})

        with self.assertRaises(RuntimeAdapterFailure) as raised:
            adapter.status("missing")

        self.assertEqual(raised.exception.code, "RUNTIME_CONFIG_INVALID")
        self.assertFalse(raised.exception.retryable)

    def test_build_context_pushes_registry_reference_before_returning_digest(self) -> None:
        result = self.adapter.build_image(
            registry="registry.example.edu",
            repository="labs/build",
            tag="v1",
            context={"archive": b"archive"},
            build_args={"MODE": "test"},
        )
        self.assertEqual(self.client.pushed, ["registry.example.edu/labs/build:v1"])
        self.assertEqual(result["digest"], "sha256:" + "b" * 64)

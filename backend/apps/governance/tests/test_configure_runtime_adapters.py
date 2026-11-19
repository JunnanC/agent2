from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.tests.helpers import create_user, grant_admin
from apps.governance.models import RuntimeAdapter


class ConfigureRuntimeAdaptersTests(TestCase):
    def setUp(self) -> None:
        admin = create_user(
            email="runtime-admin@example.edu",
            username="runtime-admin",
            display_name="Runtime Admin",
        )
        grant_admin(admin)

    def test_registers_local_docker_and_keeps_swarm_disabled(self) -> None:
        call_command("configure_runtime_adapters", stdout=StringIO())

        local = RuntimeAdapter.objects.get(code="DOCKER-LOCAL")
        swarm = RuntimeAdapter.objects.get(code="DOCKER-SWARM")
        self.assertEqual(local.driver, RuntimeAdapter.Driver.DOCKER_LOCAL)
        self.assertEqual(local.status, RuntimeAdapter.Status.ENABLED)
        self.assertEqual(swarm.driver, RuntimeAdapter.Driver.DOCKER_SWARM)
        self.assertEqual(swarm.status, RuntimeAdapter.Status.DISABLED)

    def test_rerun_is_idempotent_and_can_enable_swarm(self) -> None:
        call_command("configure_runtime_adapters", stdout=StringIO())
        call_command("configure_runtime_adapters", enable_swarm=True, stdout=StringIO())

        self.assertEqual(RuntimeAdapter.objects.count(), 2)
        swarm = RuntimeAdapter.objects.get(code="DOCKER-SWARM")
        self.assertEqual(swarm.status, RuntimeAdapter.Status.ENABLED)

    def test_reuses_existing_adapter_for_the_same_runtime(self) -> None:
        RuntimeAdapter.objects.create(
            code="EXISTING/LOCAL",
            name="旧名称",
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            config_ref="runtime/local-docker",
            status=RuntimeAdapter.Status.ENABLED,
            change_reason="test",
        )

        call_command("configure_runtime_adapters", stdout=StringIO())

        adopted = RuntimeAdapter.objects.get(code="EXISTING/LOCAL")
        self.assertEqual(adopted.name, "Docker")
        self.assertFalse(
            RuntimeAdapter.objects.filter(code="DOCKER-LOCAL").exists()
        )

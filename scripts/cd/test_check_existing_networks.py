import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "check_existing_networks", Path(__file__).with_name("check-existing-networks.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ExistingNetworkTests(unittest.TestCase):
    def test_legacy_networks_pass_without_optional_mesh(self):
        with patch.object(module.subprocess, "check_output", return_value="[]") as inspect:
            module.check_networks({"app": {"name": "edu-platform_app"}})
            inspect.assert_called_once_with(
                ["docker", "network", "inspect", "edu-platform_app"], text=True
            )

    def test_existing_attachable_swarm_mesh_passes(self):
        actual = [{"Driver": "overlay", "Scope": "swarm", "Attachable": True}]
        with patch.object(module.subprocess, "check_output", return_value=json.dumps(actual)):
            module.check_networks(
                {"runtime-mesh": {"name": "agent2_runtime_mesh", "external": True}}
            )

    def test_unexpected_network_names_still_fail_before_docker(self):
        for key, name in (("app", "new_app"), ("runtime-mesh", "unreviewed_mesh")):
            with self.subTest(key=key), patch.object(module.subprocess, "check_output") as inspect:
                with self.assertRaisesRegex(SystemExit, "must be explicitly mapped"):
                    module.check_networks({key: {"name": name, "external": True}})
                inspect.assert_not_called()

    def test_mesh_cannot_be_created_by_compose(self):
        with patch.object(module.subprocess, "check_output") as inspect:
            with self.assertRaisesRegex(SystemExit, "must be external"):
                module.check_networks({"runtime-mesh": {"name": "agent2_runtime_mesh"}})
            inspect.assert_not_called()

    def test_mesh_requires_overlay_scope_and_attachability(self):
        for change in ({"Driver": "bridge"}, {"Scope": "local"}, {"Attachable": False}):
            actual = {"Driver": "overlay", "Scope": "swarm", "Attachable": True, **change}
            with self.subTest(change=change), patch.object(
                module.subprocess, "check_output", return_value=json.dumps([actual])
            ):
                with self.assertRaisesRegex(SystemExit, "attachable Swarm overlay"):
                    module.check_networks(
                        {"runtime-mesh": {"name": "agent2_runtime_mesh", "external": True}}
                    )

    def test_missing_network_stops_preflight(self):
        with patch.object(
            module.subprocess, "check_output", side_effect=subprocess.CalledProcessError(1, "docker")
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                module.check_networks(
                    {"runtime-mesh": {"name": "agent2_runtime_mesh", "external": True}}
                )

"""Verify existing Compose networks, including the optional Swarm workspace mesh."""

import json
import subprocess
import sys


def check_networks(networks: dict) -> None:
    for key, network in networks.items():
        mesh = key == "runtime-mesh"
        expected = "agent2_runtime_mesh" if mesh else "edu-platform_" + key
        if network.get("name") != expected:
            raise SystemExit("Existing network must be explicitly mapped: " + expected)
        if mesh and not network.get("external"):
            raise SystemExit("Runtime mesh must be external: " + expected)
        output = subprocess.check_output(
            ["docker", "network", "inspect", expected], text=True
        )
        if mesh:
            actual = json.loads(output)[0]
            if (
                actual.get("Driver") != "overlay"
                or actual.get("Scope") != "swarm"
                or not actual.get("Attachable")
            ):
                raise SystemExit(
                    "Runtime mesh must be an attachable Swarm overlay: " + expected
                )


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as file:
        check_networks(json.load(file)["networks"])

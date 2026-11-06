"""Opt-in real Docker roundtrip; never starts a Compose stack."""

import hashlib
import os
import uuid

import pytest

from apps.core.project_archive import bundle, unpack
from apps.provisioning.adapters import DockerLocalAdapter


@pytest.mark.skipif(os.environ.get("IDE_REAL_DOCKER_TEST") != "1", reason="explicit Docker opt-in")
def test_real_project_roundtrip_is_writable_and_replaces_file_set() -> None:
    import docker

    client = docker.from_env()
    config_ref = "runtime/ide-project-test"
    name = "edu-ide-project-test-" + uuid.uuid4().hex[:12]
    volume = client.volumes.create(name=name)
    container = client.containers.run(
        os.environ.get("IDE_RUNTIME_IMAGE", "experimental-platform-workspace:local"),
        ["sleep", "180"], name=name, detach=True, read_only=True, network_mode="none",
        cap_drop=["ALL"], security_opt=["no-new-privileges:true"], pids_limit=128,
        mem_limit="768m", tmpfs={
            "/tmp": "rw,noexec,nosuid,nodev,size=64m,mode=1777,uid=0,gid=0",
        }, labels={"edu.platform.managed": "true", "edu.platform.kind": "student-runtime",
                   "edu.platform.config_ref": config_ref},
        volumes={volume.name: {"bind": "/workspace", "mode": "rw"}},
    )
    try:
        adapter = DockerLocalAdapter(client=client.api, config_ref=config_ref)
        files = {"Main.java": b"class Main {}\n", "src/Helper.java": b"class Helper {}\n"}
        for project in [files, {"main.py": b"print('reset')\n", "empty/": b""}, {}]:
            value = bundle(project, max_bytes=1024 * 1024)
            adapter.restore_workspace(
                external_id=container.id, relative_path=".", content=value,
                expected_digest=hashlib.sha256(value).hexdigest(),
            )
            result = container.exec_run(["python", "-I", "-c", (
                "from pathlib import Path; p=Path('/workspace/.cache'); p.mkdir(exist_ok=True); "
                "(p/'build').write_bytes(b'0'*(2*1024*1024))"
            )])
            assert result.exit_code == 0, result.output
            captured = adapter.capture_workspace(
                external_id=container.id, relative_path=".", max_bytes=1024 * 1024,
            )
            assert unpack(captured.content, max_bytes=1024 * 1024, require_manifest=True) == project
            assert captured.digest == hashlib.sha256(value).hexdigest()
        result = container.exec_run(["python", "-c", "open('/workspace/new.py','w').write('ok')"])
        assert result.exit_code == 0, result.output
    finally:
        container.remove(force=True, v=True)
        volume.remove()
        client.close()

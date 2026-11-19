"""Docker Local workspace. Only workers use this module to touch the Docker Engine."""

import base64
import json
import time
from contextlib import suppress
from typing import Any

from docker.errors import NotFound

from apps.provisioning.stdio import StdioExecutor, StdioResult, compile_plan, source_archive

WORKSPACE_KIND = "student-workspace"
EXECUTION_PATH = "/workspace/execution"
SOURCE_PATH = EXECUTION_PATH + "/source"
ARTIFACT_PATH = EXECUTION_PATH + "/artifacts"


class WorkspaceRuntime:
    def __init__(self, executor: StdioExecutor, workspace: Any) -> None:
        self.executor = executor
        self.workspace = workspace
        self.client = executor.client
        self.labels = {
            "edu.platform.managed": "true",
            "edu.platform.kind": WORKSPACE_KIND,
            "edu.platform.task": workspace.task.public_id,
            "edu.platform.expires_at": str(int(workspace.expires_at.timestamp())),
        }

    def ensure(self) -> Any:
        try:
            container = self.client.containers.get(self.workspace.container_name)
        except NotFound:
            volume = self.client.volumes.create(name=self.workspace.volume_name, labels=self.labels)
            container = self.client.containers.create(
                self.executor.image,
                name=self.workspace.container_name,
                entrypoint=["sleep", "infinity"],
                user="10001:10001",
                network_mode="none",
                read_only=True,
                init=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                mem_limit="512m",
                memswap_limit="512m",
                nano_cpus=500_000_000,
                pids_limit=128,
                tmpfs={
                    "/tmp": "rw,nosuid,nodev,noexec,size=128m,uid=10001,gid=10001",
                    "/build": "rw,nosuid,nodev,exec,size=128m,uid=10001,gid=10001",
                },
                volumes={volume.name: {"bind": "/workspace", "mode": "rw,nocopy"}},
                environment={
                    "HOME": "/tmp",
                    "GOCACHE": "/tmp/go-build",
                    "GOPATH": "/tmp/go",
                    "GOFLAGS": "-p=1",
                    "GOMAXPROCS": "1",
                    "GOPROXY": "off",
                    "GOTOOLCHAIN": "local",
                    "GO111MODULE": "off",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                labels=self.labels,
            )
        if container.status != "running":
            container.start()
        return container

    def remove(self) -> None:
        with suppress(NotFound):
            self.client.containers.get(self.workspace.container_name).remove(force=True)
        with suppress(NotFound):
            self.client.volumes.get(self.workspace.volume_name).remove()

    def sync(self, container: Any, drafts: list[Any]) -> None:
        # Docker stages root-owned files. The student UID cannot alter the durable volume.
        for draft in drafts:
            self._stage(
                container,
                "/workspace",
                {
                    f"{draft.question.public_id}/{draft.language}.json": json.dumps(
                        draft.files, ensure_ascii=False
                    ).encode(),
                },
            )

    @staticmethod
    def _stage(container: Any, directory: str, files: dict[str, bytes]) -> None:
        if not container.put_archive(directory, source_archive(files, owner=0)):
            raise RuntimeError("Workspace staging failed")

    @staticmethod
    def _reset_processes(container: Any) -> None:
        # Stop every descendant and discard tmpfs, retaining the container and durable volume.
        container.reload()
        if container.status == "running":
            container.kill()
        container.start()

    @staticmethod
    def _clear_execution(container: Any) -> None:
        # Fixed orchestration command. Student code always runs as UID 10001.
        if container.exec_run(["rm", "-rf", EXECUTION_PATH], user="0:0").exit_code:
            raise RuntimeError("Temporary workspace source cleanup failed")

    def execute(
        self,
        *,
        container: Any,
        language: str,
        files: dict[str, str],
        inputs: list[str],
        timeout_seconds: int,
        expires_at: float,
    ) -> tuple[StdioResult | None, list[StdioResult]]:
        compile_argv, run_argv = compile_plan(language, files)
        sources = {f"execution/source/{path}": value.encode() for path, value in files.items()}
        argv = [arg.replace("/source/", SOURCE_PATH + "/") for arg in compile_argv]
        self._reset_processes(container)
        try:
            self._clear_execution(container)
            self._stage(container, "/workspace", sources)
            if compile_argv:
                compilation = self.executor._exec(container, argv, 30, workdir=SOURCE_PATH)
                if compilation.status != "PASSED":
                    return compilation, []
                build_files = self.executor._artifacts(container)
                self._stage(
                    container,
                    "/workspace",
                    {
                        f"execution/artifacts/{path}": content
                        for path, content in build_files.items()
                    },
                )
                self._reset_processes(container)
            results: list[StdioResult] = []
            deadline = min(expires_at, time.time() + 900)
            command = [
                arg.replace("/source/", SOURCE_PATH + "/").replace("/build", ARTIFACT_PATH)
                for arg in run_argv
            ]
            wrapper = (
                "import base64,os,sys,tempfile; split=sys.argv.index('--',1); "
                "f=tempfile.TemporaryFile(); "
                "f.write(base64.b64decode(''.join(sys.argv[1:split]))); "
                "f.seek(0); os.dup2(f.fileno(),0); os.execvp(sys.argv[split+1],sys.argv[split+1:])"
            )
            for stdin in inputs:
                remaining = int(deadline - time.time())
                if remaining <= 0:
                    results.extend(
                        StdioResult("TIMEOUT") for _ in range(len(inputs) - len(results))
                    )
                    break
                encoded = base64.b64encode(stdin.encode()).decode("ascii")
                chunks = [encoded[i : i + 32768] for i in range(0, len(encoded), 32768)]
                results.append(
                    self.executor._exec(
                        container,
                        ["python", "-c", wrapper, *chunks, "--", *command],
                        min(timeout_seconds, remaining),
                        workdir=SOURCE_PATH,
                    )
                )
                self._reset_processes(container)
            return None, results
        finally:
            # A later job starts from clean tmpfs even after a worker or transport failure.
            self._reset_processes(container)
            self._clear_execution(container)

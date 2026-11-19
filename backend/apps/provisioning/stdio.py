"""Trusted orchestration for one-shot stdio programs; no test suite enters the sandbox."""

import io
import tarfile
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from docker.errors import NotFound

OUTPUT_LIMIT = 65536
SOURCE_LIMIT = 20 * 1024 * 1024
TOOLCHAIN_SMOKE = {
    "python": {"main.py": "print(input())"},
    "c": {"main.c": '#include <stdio.h>\nint main(){int n;scanf("%d",&n);printf("%d",n);}'},
    "cpp": {"main.cpp": '#include <iostream>\nint main(){int n;std::cin>>n;std::cout<<n;}'},
    "java": {"Main.java": (
        "import java.util.Scanner;public class Main{public static void main(String[]a){"
        "System.out.println(new Scanner(System.in).nextInt());}}"
    )},
    "go": {"main.go": (
        'package main\nimport "fmt"\nfunc main(){var n int;fmt.Scan(&n);fmt.Print(n)}'
    )},
}


@dataclass(frozen=True)
class StdioResult:
    status: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None


def compile_plan(language: str, files: Mapping[str, str]) -> tuple[list[str], list[str]]:
    paths = sorted(files)
    if language == "python":
        return [], ["python", "/source/main.py"]
    if language in {"c", "cpp"}:
        extensions = (".c",) if language == "c" else (".cpp", ".cc", ".cxx")
        sources = ["/source/" + path for path in paths if path.endswith(extensions)]
        return [
            "gcc" if language == "c" else "g++",
            "-std=c17" if language == "c" else "-std=c++20", "-O2",
            *sources, "-o", "/build/program",
        ], ["/build/program"]
    if language == "java":
        return [
            "javac", "-encoding", "UTF-8", "-J-Xmx512m", "-d", "/build", "--source-path", "/source",
            *["/source/" + path for path in paths if path.endswith(".java")],
        ], [
            "java", "-Dfile.encoding=UTF-8", "-Xmx256m", "-XX:ActiveProcessorCount=1",
            "-cp", "/build", "Main",
        ]
    if language == "go":
        return ["/usr/local/go/bin/go", "build", "-o", "/build/program", "."], ["/build/program"]
    raise ValueError("Unsupported assessment language")


def source_archive(files: Mapping[str, bytes], *, owner: int = 10001) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        parents = sorted({
            "/".join(path.split("/")[:i])
            for path in files for i in range(1, len(path.split("/")))
        })
        for directory in parents:
            item = tarfile.TarInfo(directory)
            item.type, item.mode = tarfile.DIRTYPE, 0o755 if owner == 0 else 0o555
            archive.addfile(item)
        for path, content in files.items():
            item = tarfile.TarInfo(path)
            item.uid = item.gid = owner
            item.mode, item.size = 0o555, len(content)
            archive.addfile(item, io.BytesIO(content))
    return output.getvalue()


class StdioExecutor:
    """Use the configured Docker Engine; callers handle quota admission and durable jobs."""

    def __init__(self, client: Any, image: str, *, owner: str) -> None:
        self.client, self.image = client, image
        self.owner = owner
        self.containers: list[Any] = []
        self.volumes: list[Any] = []
        self.labels = {
            "edu.platform.managed": "true", "edu.platform.kind": "assessment-stdio",
            "edu.platform.assessment": owner,
            "edu.platform.expires_at": str(int(time.time()) + 3600),
        }

    def _container(self, *, memory_mb: int, volumes: dict[str, Any]) -> Any:
        container = self.client.containers.create(
            self.image, entrypoint=["python", "-c", "import time; time.sleep(900)"],
            name="experimental-platform-stdio-" + uuid.uuid4().hex,
            user="10001:10001", network_mode="none", read_only=True,
            cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
            mem_limit=f"{memory_mb}m", memswap_limit=f"{memory_mb}m",
            nano_cpus=1_000_000_000, pids_limit=128,
            tmpfs={
                "/tmp": "rw,nosuid,nodev,size=128m,uid=10001,gid=10001",
                "/build": "rw,exec,nosuid,nodev,size=128m,uid=10001,gid=10001",
            },
            volumes=volumes, labels=self.labels, working_dir="/source",
            environment={
                "HOME": "/tmp", "GOCACHE": "/tmp/go-build", "GOPATH": "/tmp/go",
                "GOFLAGS": "-p=1", "GOMAXPROCS": "1", "GOPROXY": "off",
                "GOTOOLCHAIN": "local", "GO111MODULE": "off", "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        self.containers.append(container)
        container.start()
        return container

    def _volume(self, files: Mapping[str, bytes]) -> Any:
        volume = self.client.volumes.create(
            name="experimental-platform-stdio-data-" + uuid.uuid4().hex, labels=self.labels,
        )
        self.volumes.append(volume)
        stager = self._container(
            memory_mb=256, volumes={volume.name: {"bind": "/source", "mode": "rw"}},
        )
        if not stager.put_archive("/source", source_archive(files)):
            raise RuntimeError("Assessment source staging failed")
        stager.remove(force=True)
        self.containers.remove(stager)
        return volume

    def _exec(
        self, container: Any, argv: list[str], timeout: int, *, workdir: str = "/source",
    ) -> StdioResult:
        stdout, stderr = bytearray(), bytearray()
        done, exceeded = threading.Event(), threading.Event()
        failure: list[BaseException] = []
        execution = self.client.api.exec_create(
            container.id, argv, stdout=True, stderr=True, user="10001:10001", workdir=workdir,
        )["Id"]

        def collect() -> None:
            try:
                for out, err in self.client.api.exec_start(execution, stream=True, demux=True):
                    for chunk, target in ((out, stdout), (err, stderr)):
                        if chunk:
                            remaining = OUTPUT_LIMIT - len(target)
                            target.extend(chunk[:max(remaining, 0)])
                            if len(chunk) > remaining:
                                exceeded.set()
                    if exceeded.is_set():
                        break
            except BaseException as exc:
                failure.append(exc)
            finally:
                done.set()

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        while not done.wait(0.02):
            if exceeded.is_set() or time.monotonic() >= deadline:
                break
        timed_out = not done.is_set() and not exceeded.is_set()
        if exceeded.is_set() or timed_out:
            container.kill()
            reader.join(timeout=5)
            return StdioResult("OUTPUT_LIMIT" if exceeded.is_set() else "TIMEOUT")
        container.reload()
        if container.attrs["State"].get("OOMKilled"):
            return StdioResult("MEMORY_LIMIT")
        if failure:
            raise RuntimeError("Assessment output stream failed") from failure[0]
        state = self.client.api.exec_inspect(execution)
        if state["Running"]:
            raise RuntimeError("Assessment execution state is inconsistent")
        code = state["ExitCode"]
        return StdioResult(
            "PASSED" if code == 0 else "MEMORY_LIMIT" if code == 137 else "RUNTIME_ERROR",
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"), code,
        )

    def _artifacts(self, container: Any) -> dict[str, bytes]:
        archive_process = container.exec_run(["tar", "cf", "-", "-C", "/build", "."], stream=True)
        chunks = archive_process.output
        data = bytearray()
        for chunk in chunks:
            if len(data) + len(chunk) > SOURCE_LIMIT:
                raise RuntimeError("Compiled assessment artifacts exceed size limit")
            data.extend(chunk)
        result = {}
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for member in archive:
                if member.isdir():
                    continue
                name = member.name.removeprefix("./")
                if (
                    not member.isfile() or name.startswith("/")
                    or any(part in {"", ".", ".."} for part in name.split("/"))
                    or member.size > SOURCE_LIMIT
                ):
                    raise RuntimeError("Invalid compiler artifact")
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError("Missing compiler artifact")
                result[name] = source.read(SOURCE_LIMIT + 1)
        return result

    def execute(
        self, *, language: str, files: dict[str, str], inputs: list[str],
        timeout_seconds: int, memory_mb: int,
    ) -> tuple[StdioResult | None, list[StdioResult]]:
        """Compile once; each input receives a fresh sandbox and private current-input file."""
        from apps.labtemplates.questions import project_files

        project_files(files, allow_empty=False)
        compile_argv, run_argv = compile_plan(language, files)
        source = self._volume({path: text.encode() for path, text in files.items()})
        artifacts = None
        if compile_argv:
            compiler = self._container(
                memory_mb=1024, volumes={source.name: {"bind": "/source", "mode": "ro"}},
            )
            compilation = self._exec(compiler, compile_argv, 30)
            if compilation.status != "PASSED":
                return compilation, []
            artifact_files = self._artifacts(compiler)
            # Executable permissions are set by the daemon during staging, never by student code.
            compiler.remove(force=True)
            self.containers.remove(compiler)
            artifacts = self._volume(artifact_files)
        results: list[StdioResult] = []
        execution_deadline = time.monotonic() + 900
        for stdin in inputs:
            if time.monotonic() >= execution_deadline:
                results.extend(StdioResult("TIMEOUT") for _ in range(len(inputs) - len(results)))
                break
            if len(stdin.encode()) > 1048576:
                raise ValueError("Assessment input exceeds limit")
            current_input = self._volume({"stdin.txt": stdin.encode()})
            volumes = {
                source.name: {"bind": "/source", "mode": "ro"},
                current_input.name: {"bind": "/input", "mode": "ro"},
            }
            if artifacts:
                volumes[artifacts.name] = {"bind": "/compiled", "mode": "ro"}
            runner = self._container(memory_mb=memory_mb, volumes=volumes)
            command = [arg.replace("/build/", "/compiled/").replace("/build", "/compiled")
                       for arg in run_argv]
            # This wrapper contains no tests or expected outputs, only the current-input path.
            wrapper = (
                "import os,sys; f=os.open('/input/stdin.txt',os.O_RDONLY); "
                "os.dup2(f,0); os.close(f); os.execvp(sys.argv[1],sys.argv[1:])"
            )
            results.append(self._exec(runner, ["python", "-c", wrapper, *command], timeout_seconds))
            runner.remove(force=True)
            self.containers.remove(runner)
        return None, results

    def close(self) -> None:
        """Leave failed removals visible to the caller for durable cleanup/retry."""
        errors = []
        for container in self.containers[::-1]:
            try:
                container.remove(force=True)
            except NotFound:
                pass
            except Exception as exc:
                errors.append(exc)
                continue
            self.containers.remove(container)
        for volume in self.volumes[::-1]:
            try:
                volume.remove(force=True)
            except NotFound:
                pass
            except Exception as exc:
                errors.append(exc)
                continue
            self.volumes.remove(volume)
        if errors:
            raise RuntimeError("Assessment resource cleanup requires retry") from errors[0]


def normalized_text(value: str) -> str:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip(" \t") for line in lines]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def stdio_outputs_match(actual: str, expected: str) -> bool:
    return normalized_text(actual) == normalized_text(expected)

"""Opt-in five-language judge acceptance against an existing local image."""

import json
import os
import uuid

import pytest

from apps.core.project_archive import bundle
from apps.labtemplates.services import build_execution_plan
from apps.provisioning.adapters import DockerLocalAdapter
from apps.provisioning.ports import RuntimeSpec

pytestmark = pytest.mark.skipif(
    os.environ.get("IDE_REAL_DOCKER_TEST") != "1", reason="explicit Docker opt-in"
)

PROJECTS = {
    "python": {
        "entrypoint": "main.py",
        "success": "print(42)\n",
        "syntax": "def broken(:\n",
        "runtime": "raise SystemExit(7)\n",
        "timeout": "while True: pass\n",
        "multifile": {
            "main.py": "from helper import answer\nprint(answer())\n",
            "helper.py": "def answer(): return 42\n",
        },
    },
    "c": {
        "entrypoint": "main.c",
        "success": '#include <stdio.h>\nint main(void) { puts("42"); }\n',
        "syntax": "int main( {\n",
        "runtime": "int main(void) { return 7; }\n",
        "timeout": "int main(void) { for (;;) {} }\n",
        "multifile": {
            "main.c": '#include <stdio.h>\n#include "answer.h"\n'
            'int main(void) { printf("%d\\n", answer()); }\n',
            "answer.h": "static int answer(void) { return 42; }\n",
        },
    },
    "cpp": {
        "entrypoint": "main.cpp",
        "success": '#include <iostream>\nint main() { std::cout << "42\\n"; }\n',
        "syntax": "int main( {\n",
        "runtime": "int main() { return 7; }\n",
        "timeout": "int main() { for (;;) {} }\n",
        "multifile": {
            "main.cpp": '#include <iostream>\n#include "answer.hpp"\n'
            'int main() { std::cout << answer() << "\\n"; }\n',
            "answer.hpp": "inline int answer() { return 42; }\n",
        },
    },
    "java": {
        "entrypoint": "Main.java",
        "success": "class Main { public static void main(String[] args) {"
        "System.out.println(42); } }\n",
        "syntax": "class Main { invalid syntax }\n",
        "runtime": "class Main { public static void main(String[] args) {"
        "System.exit(7); } }\n",
        "timeout": "class Main { public static void main(String[] args) {"
        "while (true) {} } }\n",
        "multifile": {
            "Main.java": "import helper.Answer;\nclass Main {"
            "public static void main(String[] args) { System.out.println(Answer.value()); } }\n",
            "helper/Answer.java": "package helper;\npublic class Answer {"
            "public static int value() { return 42; } }\n",
        },
    },
    "go": {
        "entrypoint": "main.go",
        "success": 'package main\nimport "fmt"\nfunc main() { fmt.Println(42) }\n',
        "syntax": "package main\nfunc main( {\n",
        "runtime": 'package main\nimport "os"\nfunc main() { os.Exit(7) }\n',
        "timeout": "package main\nfunc main() { for {} }\n",
        "multifile": {
            "main.go": 'package main\nimport ("fmt"; "example.local/judge/helper")\n'
            "func main() { fmt.Println(helper.Answer()) }\n",
            "go.mod": "module example.local/judge\n\ngo 1.25\n",
            "helper/answer.go": "package helper\nfunc Answer() int { return 42 }\n",
        },
    },
}


@pytest.fixture(scope="module")
def real_judge():
    import docker

    client = docker.from_env()
    image = client.images.get(
        os.environ.get("IDE_RUNTIME_IMAGE", "experimental-platform-workspace:local")
    )
    adapter = DockerLocalAdapter(
        client=client.api, config={"image": image.id}, config_ref="runtime/judge-matrix-test"
    )
    try:
        yield client, adapter, image.id
    finally:
        client.close()


@pytest.mark.parametrize("language", PROJECTS)
@pytest.mark.parametrize("scenario", [
    "success", "multifile", "nested", "syntax", "runtime", "timeout",
])
def test_real_judge_language_matrix(real_judge, language, scenario):
    client, adapter, image_id = real_judge
    project = PROJECTS[language]
    entrypoint = project["entrypoint"]
    if scenario == "nested":
        entrypoint = f"src/{entrypoint}"
        files = {entrypoint: project["success"]}
    else:
        files = project["multifile"] if scenario == "multifile" else {entrypoint: project[scenario]}
    timeout = 25 if language == "go" else 15 if language != "python" else 2
    specification = {
        "schema_version": 2, "language": language, "entrypoint": entrypoint,
        "comparator": "token", "network_mode": "DENY_ALL", "tests_asset": "0" * 26,
        "timeout_seconds": timeout, "memory_mb": 768, "cpu_millicores": 1000,
    }
    judge_id = "matrix-" + uuid.uuid4().hex
    spec = RuntimeSpec(
        task_id=judge_id, course_id="judge-matrix", student_id="judge-matrix",
        runtime_type="CONTAINER", image_registry="local", image_repository="workspace",
        image_digest=image_id, resource_profile_id="judge-matrix", cpu_millicores=1000,
        memory_mb=768, disk_gb=1,
    )
    result = adapter.execute_judge(
        spec=spec, command=["python", entrypoint],
        source=bundle({path: value.encode() for path, value in files.items()}, max_bytes=65536),
        tests=json.dumps({"cases": [{"input": "", "expected": "42"}]}).encode(),
        timeout_seconds=timeout, memory_mb=768, cpu_millicores=1000,
        network_mode="DENY_ALL", judge_id=judge_id,
        execution_plan=build_execution_plan(specification),
    )
    expected = "PASSED" if scenario in {"success", "multifile", "nested"} else (
        "TIMEOUT" if scenario == "timeout" else "FAILED"
    )
    assert result.status == expected, result
    report = json.loads(result.stdout.splitlines()[-1])
    if scenario in {"success", "multifile", "nested"}:
        assert report["results"][0]["stdout"].strip() == "42"
    elif scenario == "syntax" and language != "python":
        assert report["compile_stderr"]
        assert report["cases"] == 0
    elif scenario == "runtime":
        assert report["results"][0]["returncode"] == 7
    elif scenario == "timeout":
        assert report["results"][0]["status"] == "TIMEOUT"
    else:
        assert "SyntaxError" in report["results"][0]["stderr"]
    filters = {"label": f"edu.platform.judge={judge_id}"}
    assert client.containers.list(all=True, filters=filters) == []
    assert client.volumes.list(filters=filters) == []

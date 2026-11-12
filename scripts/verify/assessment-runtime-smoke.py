"""Exercise the real stdio sandbox without touching application databases or existing labs."""

import argparse
import os
import sys
import time
from pathlib import Path

import docker

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "education_experiment_platform.settings.test")

import django

django.setup()

from apps.provisioning.stdio import StdioExecutor  # noqa: E402 - initialize standalone Django first

PROGRAMS = {
    "python": {"main.py": "from helper import add\na,b=map(int,input().split());print(add(a,b))",
               "helper.py": "def add(a,b): return a+b"},
    "c": {"main.c": '#include <stdio.h>\nint add(int,int);int main(){int a,b;scanf("%d%d",&a,&b);printf("%d\\n",add(a,b));}',
          "helper.c": "int add(int a,int b){return a+b;}"},
    "cpp": {"main.cpp": '#include <iostream>\nint add(int,int);int main(){int a,b;std::cin>>a>>b;std::cout<<add(a,b)<<"\\n";}',
            "helper.cpp": "int add(int a,int b){return a+b;}"},
    "java": {"Main.java": "import java.util.Scanner;public class Main{public static void main(String[] a){Scanner s=new Scanner(System.in);System.out.println(Helper.add(s.nextInt(),s.nextInt()));}}",
             "Helper.java": "class Helper{static int add(int a,int b){return a+b;}}"},
    "go": {"main.go": 'package main\nimport "fmt"\nfunc main(){var a,b int;fmt.Scan(&a,&b);fmt.Println(add(a,b))}',
           "helper.go": "package main\nfunc add(a,b int)int{return a+b}"},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="experimental-platform-workspace:local")
    args = parser.parse_args()
    client = docker.from_env()
    for language, files in PROGRAMS.items():
        started = time.monotonic()
        executor = StdioExecutor(client, args.image, owner="stdio-smoke")
        try:
            compilation, results = executor.execute(
                language=language, files=files, inputs=["3 5\n", "-2 9\n"],
                timeout_seconds=5, memory_mb=512 if language == "java" else 256,
            )
            assert compilation is None, (language, compilation)
            assert [result.status for result in results] == ["PASSED", "PASSED"], results
            assert [result.stdout.strip() for result in results] == ["8", "7"], results
            print(
                f"{language}: multi-file compile and isolated cases passed; "
                f"compile + 2 isolated cases = {time.monotonic() - started:.3f}s", flush=True,
            )
        finally:
            executor.close()
    scenarios = [
        ("timeout", "while True: pass", "TIMEOUT"),
        ("output-limit", "import os\nwhile True: os.write(1,b'x'*65536)", "OUTPUT_LIMIT"),
        ("network-isolation", "import socket\nsocket.create_connection(('1.1.1.1',443),timeout=1)", "RUNTIME_ERROR"),
        ("hidden-suite-isolation", "from pathlib import Path\nassert not Path('/judge/runner.py').exists()\nassert not Path('/var/run/docker.sock').exists()\nprint(input())", "PASSED"),
        ("fake-result", "print('{\"status\":\"PASSED\",\"score\":100}')", "PASSED"),
        ("memory-limit", "a=[]\nwhile True: a.append(bytearray(8*1024*1024))", "MEMORY_LIMIT"),
        ("unprivileged", "import os\nassert os.getuid()==10001\nprint(input())", "PASSED"),
    ]
    for label, program, status in scenarios:
        executor = StdioExecutor(client, args.image, owner="stdio-smoke-security")
        try:
            compilation, results = executor.execute(
                language="python", files={"main.py": program}, inputs=["current-case-only"],
                timeout_seconds=2, memory_mb=128,
            )
            assert compilation is None
            assert results[0].status == status, (label, results)
            if label == "fake-result":
                from apps.provisioning.stdio import stdio_outputs_match

                assert not stdio_outputs_match(results[0].stdout, "8")
            print(f"{label}: passed", flush=True)
        finally:
            executor.close()
    client.close()


if __name__ == "__main__":
    main()

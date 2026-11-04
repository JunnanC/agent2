"""Exercise breakpoints, stepping and variables with the real five-language tools."""

import json
import os
import re
import selectors
import socket
import subprocess
import tempfile
import time
from pathlib import Path


def run(command, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (command, result.stdout, result.stderr)
    return result.stdout


def wait_text(process, expected, timeout=30):
    data = b""
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while expected.encode() not in data:
            assert time.monotonic() < deadline, (expected, data.decode(errors="replace"))
            if selector.select(0.2):
                chunk = os.read(process.stdout.fileno(), 4096)
                assert chunk, (expected, data)
                data += chunk
        return data.decode(errors="replace")
    finally:
        selector.close()


class DAP:
    def __init__(self, port):
        deadline = time.monotonic() + 30
        while True:
            try:
                self.connection = socket.create_connection(("127.0.0.1", port), timeout=10)
                break
            except OSError:
                assert time.monotonic() < deadline, "debug adapter did not listen"
                time.sleep(0.1)
        self.file = self.connection.makefile("rb")
        self.sequence = 0
        self.pending = []

    def send(self, command, arguments=None):
        self.sequence += 1
        content = json.dumps({"seq": self.sequence, "type": "request", "command": command,
                              "arguments": arguments or {}}).encode()
        self.connection.sendall(f"Content-Length: {len(content)}\r\n\r\n".encode() + content)
        return self.sequence

    def wait(self, *, response=None, event=None):
        def matches(message):
            return (message.get("type") == "response" and message.get("request_seq") == response
                    if response is not None else message.get("event") == event)

        while True:
            for index, message in enumerate(self.pending):
                if matches(message):
                    self.pending.pop(index)
                    assert message.get("success", True), message
                    return message
            headers = {}
            while (line := self.file.readline()) != b"\r\n":
                assert line, "debug adapter closed unexpectedly"
                key, value = line.decode().split(":", 1)
                headers[key.lower()] = value.strip()
            self.pending.append(json.loads(self.file.read(int(headers["content-length"]))))

    def request(self, command, arguments=None):
        return self.wait(response=self.send(command, arguments))

    def check_variables_and_step(self):
        stopped = self.wait(event="stopped")
        thread = stopped["body"]["threadId"]
        frame = self.request("stackTrace", {"threadId": thread})["body"]["stackFrames"][0]
        scopes = self.request("scopes", {"frameId": frame["id"]})["body"]["scopes"]
        variables = []
        for scope in scopes:
            if scope.get("expensive"):
                continue
            variables += self.request("variables", {"variablesReference": scope["variablesReference"]})["body"]["variables"]
        assert any(v["name"] == "value" and v["value"] == "7" for v in variables), variables
        self.request("next", {"threadId": thread})
        self.wait(event="stopped")
        stepped = self.request("stackTrace", {"threadId": thread})["body"]["stackFrames"][0]
        value = self.request("evaluate", {"expression": "value", "frameId": stepped["id"]})
        assert value["body"]["result"] == "8", value
        self.request("disconnect", {"terminateDebuggee": True})

    def close(self):
        self.file.close()
        self.connection.close()


def main():
    with tempfile.TemporaryDirectory(dir="/workspace") as folder:
        root = Path(folder)
        cache = root / ".cache"
        cache.mkdir()
        (cache / "go-tmp").mkdir()
        os.environ.update({"GOCACHE": str(cache / "go-build"),
                           "GOTMPDIR": str(cache / "go-tmp"), "GOMAXPROCS": "2", "GOFLAGS": "-p=2"})
        for language, compiler, suffix in [("c", "gcc", "c"), ("cpp", "g++", "cpp")]:
            source = root / f"main.{suffix}"
            source.write_text("int helper(void);\nint main(void) {\n int value=helper();\n value++;\n return value;\n}\n")
            helper = root / f"helper.{suffix}"
            helper.write_text("int helper(void) { return 7; }\n")
            run([compiler, "-g", "-O0", str(source), str(helper), "-o", str(root / language)], folder)
            output = run(["gdb", "--batch", "-ex", f"break {source}:4", "-ex", "run",
                          "-ex", "print value", "-ex", "next", "-ex", "print value",
                          str(root / language)], folder)
            assert re.search(r"\$1 = 7", output) and re.search(r"\$2 = 8", output), output

        (root / "Main.java").write_text("public class Main {\n public static void main(String[] args) {\n  int value=Helper.value();\n  value++;\n  System.out.println(value);\n }\n}\n")
        (root / "Helper.java").write_text("class Helper { static int value() { return 7; } }\n")
        run(["javac", "-g", "Main.java", "Helper.java"], folder)
        jdb = subprocess.Popen(["jdb", "-classpath", folder, "Main"], cwd=folder,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            wait_text(jdb, "> ")
            jdb.stdin.write(b"stop at Main:4\n"); jdb.stdin.flush()
            wait_text(jdb, "> ")
            jdb.stdin.write(b"run\n"); jdb.stdin.flush()
            wait_text(jdb, "main[1]")
            jdb.stdin.write(b"locals\n"); jdb.stdin.flush()
            assert "value = 7" in wait_text(jdb, "main[1]")
            jdb.stdin.write(b"next\n"); jdb.stdin.flush()
            wait_text(jdb, "main[1]")
            jdb.stdin.write(b"locals\n"); jdb.stdin.flush()
            assert "value = 8" in wait_text(jdb, "main[1]")
        finally:
            jdb.terminate(); jdb.wait(timeout=10)

        (root / "helper.py").write_text("def initial():\n    return 7\n")
        python_source = root / "main.py"
        python_source.write_text("from helper import initial\nvalue=initial()\nvalue+=1\nprint(value)\n")
        for language, port in [("python", 45671), ("go", 45672)]:
            if language == "python":
                command = ["python", "-m", "debugpy", "--listen", f"127.0.0.1:{port}", "--wait-for-client", str(python_source)]
                source, line = python_source, 3
            else:
                source = root / "main.go"
                source.write_text("package main\nimport \"fmt\"\nfunc main() {\n value:=initial()\n value++\n fmt.Println(value)\n}\n")
                (root / "helper.go").write_text("package main\nfunc initial() int { return 7 }\n")
                run(["go", "build", "-gcflags=all=-N -l", "-o", str(root / "go-debug"), "main.go", "helper.go"], folder)
                command = ["dlv", "dap", f"--listen=127.0.0.1:{port}"]
                line = 5
            process = subprocess.Popen(command, cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            dap = None
            try:
                dap = DAP(port)
                dap.request("initialize", {"adapterID": language, "linesStartAt1": True, "columnsStartAt1": True, "pathFormat": "path"})
                launch = dap.send("attach" if language == "python" else "launch", {
                    "justMyCode": True, "mode": "exec", "program": str(root / "go-debug"), "cwd": folder,
                } if language == "go" else {"justMyCode": True})
                dap.wait(event="initialized")
                dap.request("setBreakpoints", {"source": {"path": str(source)}, "breakpoints": [{"line": line}]})
                dap.request("configurationDone")
                dap.wait(response=launch)
                dap.check_variables_and_step()
            finally:
                if dap: dap.close()
                if process.poll() is None: process.terminate()
                process.wait(timeout=10)
    print(json.dumps({language: {"breakpoint": True, "step": True, "variables": True}
                      for language in ["c", "cpp", "java", "python", "go"]}))


if __name__ == "__main__":
    main()

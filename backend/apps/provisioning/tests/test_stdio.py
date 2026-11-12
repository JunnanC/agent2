import io
import tarfile
from unittest.mock import Mock

import pytest
from docker.errors import NotFound

from apps.provisioning.stdio import (
    StdioExecutor,
    compile_plan,
    source_archive,
    stdio_outputs_match,
)


@pytest.mark.parametrize(("actual", "expected", "matches"), [
    ("1 2\r\n3 \t\r\n\r\n", "1 2\n3", True),
    ("1\r2", "1\n2\n", True), ("", "\n\n", True),
    ("1  2", "1 2", False), (" 1", "1", False),
    ("A", "a", False), ("1\n\n2", "1\n2", False),
    ("Enter a number: 1", "1", False), ("1.000001", "1", False),
])
def test_stdio_output_contract(actual: str, expected: str, matches: bool) -> None:
    assert stdio_outputs_match(actual, expected) is matches


def test_multifile_commands_are_fixed_argv_not_shell() -> None:
    compile_argv, run_argv = compile_plan("cpp", {"main.cpp": "", "helper.cpp": ""})
    assert "/source/main.cpp" in compile_argv
    assert "/source/helper.cpp" in compile_argv
    assert run_argv == ["/build/program"]
    assert compile_plan("python", {"main.py": ""}) == ([], ["python", "/source/main.py"])
    assert compile_plan("go", {"main.go": ""})[0][-1] == "."
    with pytest.raises(ValueError):
        compile_plan("shell", {})


def test_staged_files_have_no_write_permissions_and_no_embedded_test_runner() -> None:
    content = source_archive({"main.py": b"print(input())", "lib/helper.py": b""})
    with tarfile.open(fileobj=io.BytesIO(content)) as archive:
        assert {item.name for item in archive if item.isfile()} == {"main.py", "lib/helper.py"}
        assert all(item.mode & 0o222 == 0 for item in archive)


def test_cleanup_retries_only_failed_resources_and_tolerates_external_removal() -> None:
    executor = StdioExecutor(Mock(), "stdio-image", owner="cleanup-test")
    removed, failed, swept, volume = Mock(), Mock(), Mock(), Mock()
    failed.remove.side_effect = [RuntimeError("engine unavailable"), None]
    swept.remove.side_effect = NotFound("already swept")
    executor.containers = [removed, failed, swept]
    executor.volumes = [volume]
    with pytest.raises(RuntimeError, match="cleanup requires retry"):
        executor.close()
    assert executor.containers == [failed]
    assert executor.volumes == []
    executor.close()
    executor.close()
    assert executor.containers == []
    assert failed.remove.call_count == 2
    removed.remove.assert_called_once_with(force=True)
    swept.remove.assert_called_once_with(force=True)
    volume.remove.assert_called_once_with(force=True)

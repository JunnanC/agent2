import gzip
import io
import json
import tarfile
import zipfile

import pytest

from apps.core.project_archive import MANIFEST, ProjectArchiveError, bundle, unpack

LIMIT = 1024 * 1024


def test_roundtrip_is_deterministic_and_student_owned():
    files = {"Main.java": b"class Main {}", "model/Person.java": b"class Person {}", "empty/": b""}
    value = bundle(files, max_bytes=LIMIT)
    assert value == bundle(dict(reversed(list(files.items()))), max_bytes=LIMIT)
    assert unpack(value, max_bytes=LIMIT, require_manifest=True) == files
    with tarfile.open(fileobj=io.BytesIO(value)) as archive:
        assert all(item.uid == item.gid == 10001 for item in archive)
    assert unpack(bundle({}, max_bytes=LIMIT), max_bytes=LIMIT, require_manifest=True) == {}


@pytest.mark.parametrize("name", ["../x", "/x", "C:/x", "a/../b", "a\x01b"])
def test_unsafe_zip_paths_are_rejected(name):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name, b"payload")
    with pytest.raises(ProjectArchiveError):
        unpack(stream.getvalue(), max_bytes=LIMIT)


def test_manifest_must_match_and_runtime_root_is_stripped_once():
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, content in {
            "workspace/main.py": b"print(1)",
            "workspace/.edu-build/main": b"\x7fELFignored",
        }.items():
            item = tarfile.TarInfo(name)
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
    assert unpack(stream.getvalue(), max_bytes=LIMIT, docker_root=True, generated=True) == {
        "main.py": b"print(1)"
    }
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr(MANIFEST, json.dumps({"schema_version": 1, "files": []}))
        archive.writestr("main.py", "print(1)")
    with pytest.raises(ProjectArchiveError):
        unpack(bad.getvalue(), max_bytes=LIMIT, require_manifest=True)


def test_bombs_duplicates_links_and_file_directory_collisions_are_rejected():
    with pytest.raises(ProjectArchiveError):
        bundle({"a/": b"", "a/b": b"x"}, max_bytes=LIMIT)
    with pytest.raises(ProjectArchiveError):
        unpack(gzip.compress(b"0" * (LIMIT * 3)), max_bytes=LIMIT)
    for entries in [[("a", b"x"), ("a/b", b"y")], [("x", b"a"), ("x", b"b")]]:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            for name, content in entries:
                item = tarfile.TarInfo(name)
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
        with pytest.raises(ProjectArchiveError):
            unpack(stream.getvalue(), max_bytes=LIMIT)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        item = tarfile.TarInfo(".cache/link")
        item.type = tarfile.SYMTYPE
        item.linkname = "/etc/passwd"
        archive.addfile(item)
    with pytest.raises(ProjectArchiveError):
        unpack(stream.getvalue(), max_bytes=LIMIT, generated=True)

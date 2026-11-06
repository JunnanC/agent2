"""Bounded, deterministic text-project bundles shared by storage and runtimes."""

import gzip
import io
import json
import stat
import tarfile
import zipfile
from collections.abc import Callable

MANIFEST = ".edu-workspace.json"
MAX_FILES = 256
GENERATED_DIRS = {".git", ".vscode", "__pycache__", ".pytest_cache", ".cache", ".edu-build"}


class ProjectArchiveError(ValueError):
    pass


def validate_path(name: str, *, manifest: bool = False) -> str:
    if not isinstance(name, str) or not name or len(name) > 512:
        raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
    parts = name.split("/")
    if (
        "\\" in name
        or ":" in name
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
        or any(p in {"", ".", ".."} for p in parts)
        or (name == MANIFEST and not manifest)
    ):
        raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
    return name


def bundle(files: dict[str, bytes], *, max_bytes: int, manifest: bool = True) -> bytes:
    if len(files) > MAX_FILES or sum(map(len, files.values())) > max_bytes:
        raise ProjectArchiveError("WORKSPACE_FILE_TOO_LARGE")
    entries = dict(files)
    for name, content in files.items():
        if name.endswith("/") and (
            content or any(other.startswith(name) and other != name for other in files)
        ):
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
        validate_path(name.rstrip("/") if name.endswith("/") else name)
        if any(part.startswith(".") for part in name.split("/")):
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID") from exc
        if any(parent in files for parent in _parents(name)):
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
    if manifest:
        entries[MANIFEST] = json.dumps(
            {"schema_version": 1, "files": sorted(files)}, separators=(",", ":")
        ).encode()
    output = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        directories = sorted({p for name in entries for p in _parents(name)})
        regular = sorted(name for name in entries if not name.endswith("/"))
        for name in directories + regular:
            item = tarfile.TarInfo(name)
            item.uid = item.gid = 10001
            item.mode = 0o700 if name in directories else 0o600
            item.type = tarfile.DIRTYPE if name in directories else tarfile.REGTYPE
            item.size = 0 if name in directories else len(entries[name])
            archive.addfile(item, None if name in directories else io.BytesIO(entries[name]))
    value = output.getvalue()
    if len(value) > max_bytes:
        raise ProjectArchiveError("WORKSPACE_FILE_TOO_LARGE")
    return value


def _parents(name: str) -> list[str]:
    parts = name.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts))]


def unpack(
    value: bytes,
    *,
    max_bytes: int,
    docker_root: bool = False,
    generated: bool = False,
    require_manifest: bool = False,
) -> dict[str, bytes]:
    if len(value) > max_bytes + 1024 * 1024:
        raise ProjectArchiveError("WORKSPACE_FILE_TOO_LARGE")
    files: dict[str, bytes] = {}
    seen: dict[str, bool] = {}
    total = 0

    def add(
        name: str,
        size: int,
        directory: bool,
        regular: bool,
        read: Callable[[int], bytes] | None,
    ) -> None:
        nonlocal total
        name = name.rstrip("/") if directory else name
        if docker_root:
            if name == "workspace" and directory:
                return
            if not name.startswith("workspace/"):
                raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
            name = name[len("workspace/") :]
        validate_path(name, manifest=True)
        if not directory and not regular or name in seen:
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
        if any(seen.get(parent) is False for parent in _parents(name)):
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
        if not directory and any(other.startswith(name + "/") for other in seen):
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
        seen[name] = directory
        if len(seen) > MAX_FILES * 4 or size < 0 or size > max_bytes:
            raise ProjectArchiveError("WORKSPACE_FILE_TOO_LARGE")
        total += size
        if total > max_bytes:
            raise ProjectArchiveError("WORKSPACE_FILE_TOO_LARGE")
        if directory:
            return
        if read is None:
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
        content = read(size + 1)
        if len(content) != size:
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
        if generated and (
            any(p in GENERATED_DIRS for p in name.split("/"))
            or name.endswith((".class", ".o", ".pyc"))
            or content.startswith(b"\x7fELF")
        ):
            return
        if any(p.startswith(".") for p in name.split("/")) and name != MANIFEST:
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID") from exc
        if len(files) >= MAX_FILES + 1:
            raise ProjectArchiveError("WORKSPACE_FILE_TOO_LARGE")
        files[name] = content

    try:
        if value.startswith(b"PK"):
            with zipfile.ZipFile(io.BytesIO(value)) as zip_archive:
                members = zip_archive.infolist()
                if len(members) > MAX_FILES * 4:
                    raise ProjectArchiveError("WORKSPACE_FILE_TOO_LARGE")
                for zip_item in members:
                    if zip_item.orig_filename != zip_item.filename:
                        raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
                    mode = stat.S_IFMT(zip_item.external_attr >> 16)
                    if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
                        raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
                    with zip_archive.open(zip_item) as zip_source:
                        add(
                            zip_item.filename, zip_item.file_size, zip_item.is_dir(),
                            True, zip_source.read,
                        )
        else:
            # Bound decompression including TAR headers before tarfile parses PAX metadata.
            raw = value
            limit = max_bytes + MAX_FILES * 4096
            if value.startswith(b"\x1f\x8b"):
                with gzip.GzipFile(fileobj=io.BytesIO(value)) as compressed:
                    raw = compressed.read(limit + 1)
            if len(raw) > limit:
                raise ProjectArchiveError("WORKSPACE_FILE_TOO_LARGE")
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar_archive:
                for tar_item in tar_archive:
                    if not tar_item.isdir() and not tar_item.isreg():
                        raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
                    tar_source = tar_archive.extractfile(tar_item) if tar_item.isreg() else None
                    add(
                        tar_item.name,
                        tar_item.size,
                        tar_item.isdir(),
                        tar_item.isreg(),
                        tar_source.read if tar_source else None,
                    )
    except ProjectArchiveError:
        raise
    except (OSError, EOFError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise ProjectArchiveError("WORKSPACE_FILE_INVALID") from exc
    metadata = files.pop(MANIFEST, None)
    for name, directory in seen.items():
        if directory and not any(other.startswith(name + "/") for other in seen):
            if generated and any(p in GENERATED_DIRS for p in name.split("/")):
                continue
            if any(p.startswith(".") for p in name.split("/")):
                raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
            files[name + "/"] = b""
    if require_manifest and metadata is None:
        raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
    if metadata is not None:
        try:
            expected = {"schema_version": 1, "files": sorted(files)}
            parsed = json.loads(metadata)
            if parsed != expected or type(parsed.get("schema_version")) is not int:
                raise ProjectArchiveError("WORKSPACE_FILE_INVALID")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProjectArchiveError("WORKSPACE_FILE_INVALID") from exc
    if len(files) > MAX_FILES:
        raise ProjectArchiveError("WORKSPACE_FILE_TOO_LARGE")
    return files

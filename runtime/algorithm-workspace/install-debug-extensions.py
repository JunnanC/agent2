"""Install only the exact, hash-verified offline IDE debug extensions."""

import hashlib
import json
import zipfile
from pathlib import Path

lock = json.loads(Path("/opt/debug-extensions.lock.json").read_text())


def install():
    # Unpack verified VSIX files directly: the CLI otherwise fetches unpinned
    # extension-pack dependencies from the marketplace during installation.
    destination = Path("/opt/workspace-extensions")
    destination.mkdir(parents=True, exist_ok=True)
    installed = []
    for item in lock:
        filename = Path("/opt/debug-vsix") / (item["id"] + ".vsix")
        assert filename.stat().st_size == item["size"]
        assert hashlib.file_digest(filename.open("rb"), "sha256").hexdigest() == item["sha256"]
        with zipfile.ZipFile(filename) as archive:
            metadata = json.loads(archive.read("extension/package.json"))
            assert f"{metadata['publisher']}.{metadata['name']}".lower() == item["id"]
            assert metadata["version"] == item["version"]
            root = destination / f"{item['id']}-{item['version']}"
            root.mkdir()
            for member in archive.infolist():
                if not member.filename.startswith("extension/") or member.is_dir():
                    continue
                relative = Path(member.filename[len("extension/"):])
                assert not relative.is_absolute() and ".." not in relative.parts
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
                target.chmod((member.external_attr >> 16) & 0o777 or 0o644)
            installed.append({
                "identifier": {"id": item["id"]}, "version": item["version"],
                "location": {"$mid": 1, "fsPath": str(root), "path": str(root),
                             "external": root.as_uri(), "scheme": "file"},
                "relativeLocation": root.name, "metadata": {"pinned": True, "source": "vsix"},
            })
    (destination / "extensions.json").write_text(json.dumps(installed))


install()

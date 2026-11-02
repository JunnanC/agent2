# 清理浏览器验收产物中的敏感信息；由集成入口调用。
"""Remove browser credentials and signed URL material from retained Playwright artifacts."""

from __future__ import annotations

import argparse
import re
import tempfile
import zipfile
from pathlib import Path


REDACTIONS = (
    re.compile(
        rb'(?i)((?:\\?"|\b)(?:workspace_token|authorization|cookie|set-cookie|x-workspace-token)'
        rb'(?:\\?"|\b)\s*[:=]\s*(?:\\?")?)[^"\\\r\n,}]*'
    ),
    re.compile(
        rb'(?i)([?&](?:workspace_?token|signature|x-amz-(?:credential|signature|security-token))=)'
        rb'[^&"\s]*'
    ),
)


def redact(content: bytes) -> bytes:
    for pattern in REDACTIONS:
        content = pattern.sub(rb'\1[REDACTED]', content)
    return content


def redact_zip(path: Path) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".zip", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for entry in source.infolist():
                target.writestr(entry, redact(source.read(entry.filename)))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def redact_file(path: Path) -> None:
    content = path.read_bytes()
    updated = redact(content)
    if updated != content:
        path.write_bytes(updated)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_root", type=Path)
    args = parser.parse_args()
    root: Path = args.artifact_root.resolve()
    if not root.exists() or not root.is_dir():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".zip":
            redact_zip(path)
        elif path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            redact_file(path)


if __name__ == "__main__":
    main()

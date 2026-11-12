"""Explicit in-memory object storage for unit tests."""

from __future__ import annotations

import io
import threading
import uuid
from typing import Any, Final

from apps.core.object_storage import StoredObject

SHARED_OBJECTS: Final[dict[tuple[str, str, str], bytes]] = {}
STORAGE_LOCK: Final = threading.Lock()


class InMemoryObjectStorage:
    """Minimal object-storage stand-in for STUB environments.

    ``object_storage()`` constructs a new instance on every call, mirroring a
    real S3 backend — so the backing table must be shared per process.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.public = bool(kwargs.get("public", False))
        self.objects = SHARED_OBJECTS
        self._lock = threading.Lock()

    def _key(self, bucket: str, object_key: str, version_id: str) -> tuple[str, str, str]:
        return (bucket, object_key, version_id)

    def get_object(
        self, *, bucket: str, object_key: str, version_id: str = ""
    ) -> StoredObject:
        with self._lock:
            body = self._resolve(bucket, object_key, version_id)
        return StoredObject(
            body=io.BytesIO(body),
            content_length=len(body),
            content_type="application/octet-stream",
            version_id="demo-latest",
        )

    def _resolve(self, bucket: str, object_key: str, version_id: str) -> bytes:
        if version_id:
            body = self.objects.get(self._key(bucket, object_key, version_id))
            if body is None:
                raise LookupError(f"demo storage miss: {bucket}/{object_key}@{version_id}")
            return body
        for (b_key, o_key, v_key), asset in sorted(self.objects.items()):
            if b_key == bucket and o_key == object_key and v_key != "latest":
                return asset
        raise LookupError(f"demo storage miss: {bucket}/{object_key}")

    def open_object(
        self, *, bucket: str, object_key: str, version_id: str = ""
    ) -> StoredObject:
        return self.get_object(bucket=bucket, object_key=object_key, version_id=version_id)

    def head_object(
        self, *, bucket: str, object_key: str, version_id: str = ""
    ) -> StoredObject:
        stored = self.get_object(
            bucket=bucket, object_key=object_key, version_id=version_id
        )
        return StoredObject(
            body=None,
            content_length=stored.content_length,
            content_type=stored.content_type,
            version_id=stored.version_id,
        )

    def put_stream(
        self, *, bucket: str, object_key: str, stream: Any, media_type: str
    ) -> StoredObject:
        body = stream.read()
        version_id = f"demo-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self.objects[self._key(bucket, object_key, version_id)] = body
            self.objects[self._key(bucket, object_key, "latest")] = body
        return StoredObject(
            body=None,
            content_length=len(body),
            content_type=media_type,
            version_id=version_id,
        )

    def delete_object(
        self, *, bucket: str, object_key: str, version_id: str = ""
    ) -> None:
        with self._lock:
            keys = [
                key
                for key in self.objects
                if key[0] == bucket
                and key[1] == object_key
                and (not version_id or key[2] == version_id)
            ]
            for key in keys:
                del self.objects[key]

    def delete_objects(
        self, *, bucket: str, object_keys: list[str] | None = None
    ) -> list[str]:
        removed: list[str] = []
        with self._lock:
            keys = [key for key in list(self.objects) if key[0] == bucket]
            for key in keys:
                if object_keys is None or key[1] in object_keys:
                    del self.objects[key]
                    removed.append(key[1])
        return removed

    def list_objects(self, *, bucket: str) -> list[dict[str, object]]:
        with self._lock:
            return [
                {
                    "key": key[1],
                    "version_id": key[2],
                    "size": len(self.objects[key]),
                }
                for key in sorted(self.objects)
                if key[0] == bucket
            ]

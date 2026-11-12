import io
import uuid

from apps.core.object_storage import StoredObject


class MemoryStorage:
    def __init__(self, *, corrupt_reads: bool = False) -> None:
        self.objects: dict[tuple[str, str, str], bytes] = {}
        self.corrupt_reads = corrupt_reads

    def put_stream(
        self, *, bucket: str, object_key: str, stream: object, media_type: str
    ) -> StoredObject:
        payload = stream.read()  # type: ignore[attr-defined]
        version = uuid.uuid4().hex
        self.objects[(bucket, object_key, version)] = payload
        return StoredObject(None, len(payload), media_type, version)

    def open_object(self, *, bucket: str, object_key: str, version_id: str = "") -> StoredObject:
        payload = self.objects[(bucket, object_key, version_id)]
        if self.corrupt_reads and object_key.startswith("archives/"):
            payload = b"corrupt"
        return StoredObject(io.BytesIO(payload), len(payload), "application/zip", version_id)

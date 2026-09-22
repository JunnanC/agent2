from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.client import Config
from django.conf import settings


@dataclass(frozen=True)
class StoredObject:
    body: Any
    content_length: int
    content_type: str
    version_id: str


class S3ObjectStorage:
    def __init__(self, *, public: bool = False) -> None:
        endpoint = settings.MINIO_PUBLIC_ENDPOINT if public else settings.MINIO_INTERNAL_ENDPOINT
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.MINIO_APP_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_APP_SECRET_KEY,
            region_name=settings.MINIO_REGION,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def create_upload_post(
        self,
        *,
        bucket: str,
        object_key: str,
        media_type: str,
        size_bytes: int,
        expires_seconds: int,
    ) -> dict[str, Any]:
        value = self.client.generate_presigned_post(
            Bucket=bucket,
            Key=object_key,
            Fields={"Content-Type": media_type},
            Conditions=[
                {"Content-Type": media_type},
                ["content-length-range", size_bytes, size_bytes],
            ],
            ExpiresIn=expires_seconds,
        )
        value["expires_at"] = (datetime.now(UTC) + timedelta(seconds=expires_seconds)).isoformat()
        return value

    def open_object(self, *, bucket: str, object_key: str) -> StoredObject:
        response = self.client.get_object(Bucket=bucket, Key=object_key)
        return StoredObject(
            body=response["Body"],
            content_length=int(response.get("ContentLength", 0)),
            content_type=str(response.get("ContentType", "")),
            version_id=str(response.get("VersionId", "")),
        )

    def delete_object(self, *, bucket: str, object_key: str, version_id: str = "") -> None:
        kwargs: dict[str, str] = {"Bucket": bucket, "Key": object_key}
        if version_id:
            kwargs["VersionId"] = version_id
        self.client.delete_object(**kwargs)


def iter_chunks(stream: Any, *, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    while chunk := stream.read(chunk_size):
        yield chunk


def object_storage(*, public: bool = False) -> S3ObjectStorage:
    return S3ObjectStorage(public=public)

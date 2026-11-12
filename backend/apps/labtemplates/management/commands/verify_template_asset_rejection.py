import hashlib
import os

import boto3
from botocore.client import Config
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.identifiers import new_ulid
from apps.core.models import ObjectAsset

from ...assets import scan_and_attach_asset
from ...models import TemplateVersion


class Command(BaseCommand):
    help = "Upload an EICAR sample to MinIO and verify the real template rejection path."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError(
                "Template asset rejection verification is restricted to disposable environments"
            )
        version = (
            TemplateVersion.objects.filter(
                template__name="容器实验模板",
                status=TemplateVersion.Status.DRAFT,
            )
            .select_related("template")
            .first()
        )
        if version is None:
            raise CommandError("Run seed_templates_e2e before verifying asset rejection")

        payload = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        asset_id = new_ulid()
        object_key = f"template-assets/{version.public_id}/{asset_id}/eicar.txt"
        digest = hashlib.sha256(payload).hexdigest()
        client = boto3.client(
            "s3",
            endpoint_url=settings.MINIO_INTERNAL_ENDPOINT,
            aws_access_key_id=settings.MINIO_APP_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_APP_SECRET_KEY,
            region_name=settings.MINIO_REGION,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        client.put_object(
            Bucket=settings.MINIO_BUCKET,
            Key=object_key,
            Body=payload,
            ContentType="text/plain",
        )
        asset = ObjectAsset.objects.create(
            public_id=asset_id,
            bucket=settings.MINIO_BUCKET,
            object_key=object_key,
            digest_sha256=digest,
            size_bytes=len(payload),
            media_type="text/plain",
            original_name="eicar.txt",
            owner_type="TEMPLATE_VERSION",
            owner_ref=version.public_id,
            purpose="MANUAL",
        )
        changed = scan_and_attach_asset(
            asset_id=asset.public_id, trace_id="templates".ljust(32, "0")
        )
        if changed.scan_status != ObjectAsset.ScanStatus.INFECTED:
            raise CommandError(
                f"Expected INFECTED, received {changed.scan_status}:{changed.failure_code}"
            )
        if version.manual_asset_id is not None:
            raise CommandError("Rejected asset was attached to the draft template version")
        self.stdout.write(self.style.SUCCESS("template real MinIO/ClamAV EICAR rejection passed"))

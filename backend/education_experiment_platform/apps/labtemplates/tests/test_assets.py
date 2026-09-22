import hashlib
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase

from apps.core.antivirus import AntivirusResult
from apps.core.models import ObjectAsset
from apps.core.object_storage import StoredObject

from ..assets import create_asset_upload, scan_and_attach_asset
from ..errors import TemplateUploadInvalid
from ..models import TemplateVersion
from .helpers import context, create_template_version


class FakeStorage:
    def __init__(self, payload: bytes, media_type: str = "text/plain") -> None:
        self.payload = payload
        self.media_type = media_type
        self.deleted = False

    def create_upload_post(self, **_kwargs: object) -> dict[str, object]:
        return {"url": "http://object.test/upload", "fields": {}, "expires_at": "soon"}

    def open_object(self, **_kwargs: object) -> StoredObject:
        return StoredObject(
            body=BytesIO(self.payload),
            content_length=len(self.payload),
            content_type=self.media_type,
            version_id="object-v1",
        )

    def delete_object(self, **_kwargs: object) -> None:
        self.deleted = True


class ContentScanner:
    def scan(self, chunks: object) -> AntivirusResult:
        payload = b"".join(chunks)  # type: ignore[arg-type]
        if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in payload:
            return AntivirusResult(clean=False, signature="Eicar-Signature")
        return AntivirusResult(clean=True)


class TemplateAssetTests(TestCase):
    def _asset(
        self, payload: bytes, *, name: str = "manual.txt"
    ) -> tuple[ObjectAsset, FakeStorage]:
        owner, course, template, version = create_template_version(suffix=name.split(".")[0])
        storage = FakeStorage(payload)
        with patch("apps.labtemplates.assets.object_storage", return_value=storage):
            asset, _upload = create_asset_upload(
                course_id=course.public_id,
                template_id=template.public_id,
                version_id=version.public_id,
                actor=owner,
                expected_version=version.row_version,
                purpose="MANUAL",
                file_name=name,
                media_type="text/plain",
                size_bytes=len(payload),
                digest_sha256=hashlib.sha256(payload).hexdigest(),
                context=context(owner),
            )
        return asset, storage

    def test_clean_asset_is_attached_to_draft(self) -> None:
        payload = b"safe template manual\n"
        asset, storage = self._asset(payload, name="clean.txt")
        with (
            patch("apps.labtemplates.assets.object_storage", return_value=storage),
            patch("apps.labtemplates.assets.ClamAVScanner", return_value=ContentScanner()),
        ):
            changed = scan_and_attach_asset(asset_id=asset.public_id, trace_id="a" * 32)
        self.assertEqual(changed.scan_status, ObjectAsset.ScanStatus.CLEAN)
        version = TemplateVersion.objects.get(public_id=asset.owner_ref)
        self.assertEqual(version.manual_asset_id, asset.pk)

    def test_digest_mismatch_fails_and_deletes_object(self) -> None:
        declared = b"declared content"
        actual = b"tampered content"
        asset, _storage = self._asset(declared, name="digest.txt")
        storage = FakeStorage(actual)
        with patch("apps.labtemplates.assets.object_storage", return_value=storage):
            changed = scan_and_attach_asset(asset_id=asset.public_id, trace_id="d" * 32)
        self.assertEqual(changed.scan_status, ObjectAsset.ScanStatus.FAILED)
        self.assertEqual(changed.failure_code, "ASSET_VALIDATION_FAILED")
        self.assertTrue(storage.deleted)

    def test_eicar_is_marked_infected_and_never_attached(self) -> None:
        payload = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        asset, storage = self._asset(payload, name="eicar.txt")
        with (
            patch("apps.labtemplates.assets.object_storage", return_value=storage),
            patch("apps.labtemplates.assets.ClamAVScanner", return_value=ContentScanner()),
        ):
            changed = scan_and_attach_asset(asset_id=asset.public_id, trace_id="e" * 32)
        self.assertEqual(changed.scan_status, ObjectAsset.ScanStatus.INFECTED)
        version = TemplateVersion.objects.get(public_id=asset.owner_ref)
        self.assertIsNone(version.manual_asset_id)
        self.assertTrue(storage.deleted)

    def test_declaration_requires_matching_extension_mime_and_limit(self) -> None:
        owner, course, template, version = create_template_version(suffix="declaration")
        with self.assertRaises(TemplateUploadInvalid):
            create_asset_upload(
                course_id=course.public_id,
                template_id=template.public_id,
                version_id=version.public_id,
                actor=owner,
                expected_version=version.row_version,
                purpose="MANUAL",
                file_name="manual.exe",
                media_type="application/octet-stream",
                size_bytes=10,
                digest_sha256="a" * 64,
                context=context(owner),
            )

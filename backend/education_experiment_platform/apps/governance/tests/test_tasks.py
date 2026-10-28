from unittest.mock import patch

from django.test import TestCase

from apps.core.models import FailureRecord

from ..models import ImageAsset, RuntimeAdapter
from ..services import ActorContext, create_image
from ..tasks import reresolve_image_digest_task, resolve_image_digest_task
from .helpers import create_governance_admin


class ImageDigestResolutionTaskTests(TestCase):
    def setUp(self) -> None:
        self.admin = create_governance_admin(suffix="resolve-task-admin")
        self.context = ActorContext(self.admin.public_id, "PLATFORM", "t" * 32)

    def _fake_runtime(self) -> RuntimeAdapter:
        return RuntimeAdapter.objects.create(
            code="TASK-FAKE",
            name="Task fake runtime",
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            driver=RuntimeAdapter.Driver.FAKE,
            status=RuntimeAdapter.Status.ENABLED,
        )

    def _pending_image(self) -> ImageAsset:
        return create_image(
            actor=self.admin,
            registry="docker.io",
            repository="library/python",
            display_tag="3.13",
            digest="",
            risk_level="LOW",
            reason="task test",
            context=self.context,
        )

    def test_task_resolves_digest_and_writes_no_failure_record(self) -> None:
        self._fake_runtime()
        image = self._pending_image()
        result = resolve_image_digest_task.apply(args=[image.public_id, "r" * 32])
        self.assertTrue(result.successful())
        image.refresh_from_db()
        self.assertTrue((image.digest or "").startswith("sha256:"))
        self.assertFalse(
            FailureRecord.objects.filter(
                subject_type="IMAGE_ASSET", subject_ref=image.public_id
            ).exists()
        )

    def test_task_failure_after_retries_writes_failure_record(self) -> None:
        image = self._pending_image()
        self.assertFalse(
            RuntimeAdapter.objects.filter(
                status=RuntimeAdapter.Status.ENABLED,
                runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            ).exists()
        )
        resolve_image_digest_task.max_retries = 0
        try:
            result = resolve_image_digest_task.apply(args=[image.public_id, "f" * 32])
        finally:
            resolve_image_digest_task.max_retries = 2
        self.assertTrue(result.failed)
        self.assertTrue(
            FailureRecord.objects.filter(
                subject_type="IMAGE_ASSET",
                subject_ref=image.public_id,
                error_code="IMAGE_RESOLVE_FAILED",
            ).exists()
        )

    def test_task_worker_actor_context_not_required(self) -> None:
        self._fake_runtime()
        image = self._pending_image()
        result = resolve_image_digest_task.apply(args=[image.public_id])
        self.assertTrue(result.successful())
        self.assertTrue((image.digest or "") == "")
        image.refresh_from_db()
        self.assertTrue((image.digest or "").startswith("sha256:"))

    def test_reresolve_task_refreshes_drifted_digest_and_no_failure_record(self) -> None:
        self._fake_runtime()
        image = create_image(
            actor=self.admin,
            registry="docker.io",
            repository="library/python",
            display_tag="3.13",
            digest="sha256:" + "b" * 64,
            risk_level="LOW",
            reason="stale frozen digest",
            context=self.context,
        )
        with patch("apps.governance.services.runtime_for_driver") as factory:
            factory.return_value.resolve_image.return_value = {"digest": "sha256:" + "a" * 64}
            result = reresolve_image_digest_task.apply(args=[image.public_id, "r" * 32])
        self.assertTrue(result.successful())
        image.refresh_from_db()
        self.assertEqual(image.digest, "sha256:" + "a" * 64)
        self.assertEqual(image.approval_status, ImageAsset.ApprovalStatus.PENDING)
        self.assertFalse(
            FailureRecord.objects.filter(
                subject_type="IMAGE_ASSET", subject_ref=image.public_id
            ).exists()
        )

    def test_reresolve_task_failure_writes_failure_record(self) -> None:
        image = create_image(
            actor=self.admin,
            registry="docker.io",
            repository="library/python",
            display_tag="3.13",
            digest="sha256:" + "b" * 64,
            risk_level="LOW",
            reason="no runtime enabled",
            context=self.context,
        )
        reresolve_image_digest_task.max_retries = 0
        try:
            result = reresolve_image_digest_task.apply(args=[image.public_id, "f" * 32])
        finally:
            reresolve_image_digest_task.max_retries = 2
        self.assertTrue(result.failed)
        self.assertTrue(
            FailureRecord.objects.filter(
                subject_type="IMAGE_ASSET",
                subject_ref=image.public_id,
                error_code="IMAGE_RERESOLVE_FAILED",
            ).exists()
        )

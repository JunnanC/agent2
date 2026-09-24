import hashlib
import io
from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.tests.helpers import create_user, grant_admin
from apps.core.errors import DownloadScopeDenied, ImmutableRecordError, RowVersionConflict
from apps.core.models import CompensationTask, FileDownloadGrant
from apps.core.object_storage import StoredObject
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.experiments.services import publish_publication
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.governance.models import RuntimeAdapter
from apps.provisioning.adapters import reset_fake_runtime
from apps.provisioning.models import ProvisioningInstance
from apps.workspaces.models import WorkspaceSession

from ..models import ArchiveExportGrant, ArchiveJob, ArchiveManifest, ArchiveVerification
from ..services import (
    _build_package,
    authorize_archive_download,
    create_archive_export,
    execute_archive_job,
    force_safe_recycle,
    request_task_archive,
    retry_compensation_as_admin,
)


class MemoryStorage:
    def __init__(self, *, corrupt_reads: bool = False) -> None:
        self.objects: dict[tuple[str, str, str], bytes] = {}
        self.corrupt_reads = corrupt_reads

    def put_stream(
        self, *, bucket: str, object_key: str, stream: object, media_type: str
    ) -> StoredObject:
        payload = stream.read()  # type: ignore[attr-defined]
        version = "archive-version-1"
        self.objects[(bucket, object_key, version)] = payload
        return StoredObject(None, len(payload), media_type, version)

    def open_object(self, *, bucket: str, object_key: str, version_id: str = "") -> StoredObject:
        payload = self.objects[(bucket, object_key, version_id)]
        if self.corrupt_reads and object_key.startswith("archives/"):
            payload = b"corrupt"
        return StoredObject(io.BytesIO(payload), len(payload), "application/zip", version_id)


class P11ArchiveServiceTests(TestCase):
    password = "ValidPassword!234"

    def setUp(self) -> None:
        reset_fake_runtime()
        self.owner, self.course, self.template_version, self.rubric_version = create_domain(
            suffix="p11"
        )
        self.enrollment = create_enrollment(self.course, suffix="p11-student")
        self.admin = create_user(
            email="p11-admin@example.edu",
            username="p11-admin",
            display_name="P11 Admin",
            password=self.password,
        )
        grant_admin(self.admin)
        RuntimeAdapter.objects.filter(pk=self.template_version.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.FAKE,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        )
        self.template_version.runtime_adapter.refresh_from_db()
        publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="p11",
        )
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=publication.public_id,
            actor=self.owner,
            expected_version=publication.row_version,
            selected_ids=[],
            context=self.context(self.owner),
        )
        self.task = published.tasks.get(student=self.enrollment.student)
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            status=ExperimentTask.Status.IN_PROGRESS
        )
        self.task.refresh_from_db()
        self.instance = ProvisioningInstance.objects.create(
            task=self.task,
            course=self.course,
            runtime_adapter=self.template_version.runtime_adapter,
            image=self.template_version.image,
            resource_profile=self.template_version.resource_profile,
            runtime_type=self.template_version.runtime_type,
            status=ProvisioningInstance.Status.READY,
            external_id=f"fake-p11-{self.task.public_id}",
            created_trace_id="1" * 32,
        )
        self.session = WorkspaceSession.objects.create(
            task=self.task,
            student=self.task.student,
            instance=self.instance,
            course=self.course,
            jti=f"jti-{self.task.public_id}",
            token_hash=hashlib.sha256(self.task.public_id.encode()).hexdigest(),
            active_marker=f"active-{self.task.public_id}",
            capabilities={"snapshot": True},
            expires_at=timezone.now() + timezone.timedelta(minutes=10),
        )

    def tearDown(self) -> None:
        reset_fake_runtime()

    def context(self, actor: object, portal: str = "TEACHING") -> ActorContext:
        return ActorContext(actor.public_id, portal, "b" * 32)  # type: ignore[attr-defined]

    def client_for(self, *, identifier: str, portal: str) -> tuple[Client, str, dict[str, str]]:
        client = Client(enforce_csrf_checks=True)
        proxy = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}
        client.get("/api/v2/auth/csrf", HTTP_X_PORTAL=portal, **proxy)
        csrf = client.cookies["csrftoken"].value
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            response = client.post(
                "/api/v2/auth/login",
                {"identifier": identifier, "password": self.password},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL=portal,
                **proxy,
            )
        self.assertEqual(response.status_code, 200, response.content)
        return client, csrf, proxy

    def request(self, target: str = ExperimentTask.TerminalTarget.COMPLETED) -> ArchiveJob:
        with patch("apps.archives.tasks.run_archive_job.apply_async"):
            job = request_task_archive(
                task_id=self.task.public_id,
                terminal_target=target,
                trigger="TEST_TERMINAL",
                context=self.context(self.owner),
                actor=self.owner,
            )
        assert job is not None
        return job

    def test_verified_archive_recycles_all_runtime_state_and_completes(self) -> None:
        storage = MemoryStorage()
        job = self.request()
        with patch("apps.archives.services.object_storage", return_value=storage):
            finished = execute_archive_job(job_id=job.public_id, trace_id="c" * 32)
        self.assertEqual(finished.status, ArchiveJob.Status.PASSED)
        self.task.refresh_from_db()
        self.session.refresh_from_db()
        self.instance.refresh_from_db()
        self.assertEqual(self.task.status, ExperimentTask.Status.COMPLETED)
        self.assertEqual(self.session.status, WorkspaceSession.Status.REVOKED)
        self.assertEqual(self.instance.status, ProvisioningInstance.Status.DESTROYED)
        manifest = ArchiveManifest.objects.get(job=job)
        self.assertEqual(manifest.package_digest, manifest.package_asset.digest_sha256)
        self.assertEqual(
            ArchiveVerification.objects.get(job=job).result,
            ArchiveVerification.Result.PASSED,
        )

    def test_deterministic_package_and_failed_verification_force_safe_recycle(self) -> None:
        first, first_entries, first_digest, first_size = _build_package(self.task)
        second, second_entries, second_digest, second_size = _build_package(self.task)
        try:
            self.assertEqual(first.read(), second.read())
            self.assertEqual(first_entries, second_entries)
            self.assertEqual((first_digest, first_size), (second_digest, second_size))
        finally:
            first.close()
            second.close()

        storage = MemoryStorage(corrupt_reads=True)
        job = self.request(ExperimentTask.TerminalTarget.EXPIRED)
        with patch("apps.archives.services.object_storage", return_value=storage):
            failed = execute_archive_job(job_id=job.public_id, trace_id="d" * 32)
        self.assertEqual(failed.status, ArchiveJob.Status.FAILED)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, ExperimentTask.Status.FAILED)
        self.assertFalse(ArchiveManifest.objects.filter(job=job).exists())
        verification = ArchiveVerification.objects.get(job=job)
        self.assertEqual(verification.result, ArchiveVerification.Result.FAILED)

        ArchiveJob.objects.filter(pk=job.pk).update(
            safe_recycle_at=timezone.now() - timezone.timedelta(seconds=1)
        )
        force_safe_recycle(job_id=job.public_id, trace_id="e" * 32)
        self.task.refresh_from_db()
        self.session.refresh_from_db()
        self.instance.refresh_from_db()
        self.assertEqual(self.task.status, ExperimentTask.Status.FAILED)
        self.assertEqual(self.task.terminal_target, ExperimentTask.TerminalTarget.EXPIRED)
        self.assertEqual(self.session.status, WorkspaceSession.Status.REVOKED)
        self.assertEqual(self.instance.status, ProvisioningInstance.Status.DESTROYED)

    def test_export_is_scoped_short_lived_and_append_only(self) -> None:
        storage = MemoryStorage()
        job = self.request()
        with patch("apps.archives.services.object_storage", return_value=storage):
            finished = execute_archive_job(job_id=job.public_id)
        grant, token = create_archive_export(
            course_id=self.course.public_id,
            archive_id=job.public_id,
            actor=self.owner,
            expected_version=finished.row_version,
            token="fixed-token",
            context=self.context(self.owner),
        )
        self.assertEqual(token, "fixed-token")
        self.assertEqual(grant.max_downloads, 1)
        self.assertLessEqual(
            grant.expires_at,
            timezone.now() + timezone.timedelta(seconds=301),
        )
        export = ArchiveExportGrant.objects.get(download_grant=grant)
        self.assertEqual(export.requested_by, self.owner)
        self.assertEqual(export.approved_by, self.owner)
        with self.assertRaises(ImmutableRecordError):
            export.save()
        other = create_enrollment(self.course, suffix="p11-other").student
        with self.assertRaises(DownloadScopeDenied):
            authorize_archive_download(
                ArchiveManifest.objects.get(job=job).package_asset,
                other,
                "USER",
            )

    def test_replayed_manifest_records_runtime_cleanup_failure(self) -> None:
        storage = MemoryStorage()
        job = self.request()
        with patch("apps.archives.services.object_storage", return_value=storage):
            execute_archive_job(job_id=job.public_id)
        with patch(
            "apps.archives.services._finish_task_cleanup",
            side_effect=RuntimeError("runtime unavailable"),
        ):
            replayed = execute_archive_job(job_id=job.public_id)
        self.assertEqual(replayed.status, ArchiveJob.Status.PASSED)
        self.assertEqual(replayed.failure_record.error_code, "RUNTIME_CLEANUP_FAILED")
        self.assertEqual(replayed.compensation_task.task_type, "RETRY_RUNTIME_DESTROY")

    def test_manual_dead_compensation_retry_requires_current_etag(self) -> None:
        item = CompensationTask.objects.create(
            task_type="RETRY_ARCHIVE_JOB",
            subject_type="ARCHIVE_JOB",
            subject_ref="missing",
            status=CompensationTask.Status.DEAD,
            attempt_count=3,
            max_attempts=3,
            payload_masked={},
            trace_id="f" * 32,
        )
        with self.assertRaises(RowVersionConflict):
            retry_compensation_as_admin(
                compensation_id=item.public_id,
                actor=self.owner,
                expected_version=item.row_version + 1,
                reason="manual recovery",
                context=self.context(self.owner, "PLATFORM"),
            )
        with patch("apps.core.tasks.run_compensations.apply_async"):
            changed = retry_compensation_as_admin(
                compensation_id=item.public_id,
                actor=self.owner,
                expected_version=item.row_version,
                reason="manual recovery",
                context=self.context(self.owner, "PLATFORM"),
            )
        self.assertEqual(changed.status, CompensationTask.Status.RETRY)
        self.assertEqual(changed.max_attempts, 4)
        self.assertEqual(FileDownloadGrant.objects.count(), 0)

    def test_user_and_teacher_archive_api_scope_and_idempotent_export(self) -> None:
        storage = MemoryStorage()
        job = self.request()
        with patch("apps.archives.services.object_storage", return_value=storage):
            execute_archive_job(job_id=job.public_id)

        user, _csrf, proxy = self.client_for(identifier=self.task.student.username, portal="USER")
        response = user.get(
            f"/api/v2/tasks/{self.task.public_id}/archive",
            HTTP_X_PORTAL="USER",
            **proxy,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["status"], ArchiveJob.Status.PASSED)

        outsider = create_user(
            email="p11-outsider@example.edu",
            username="p11-outsider",
            display_name="P11 Outsider",
            password=self.password,
        )
        other, _csrf, other_proxy = self.client_for(identifier=outsider.username, portal="USER")
        denied = other.get(
            f"/api/v2/tasks/{self.task.public_id}/archive",
            HTTP_X_PORTAL="USER",
            **other_proxy,
        )
        self.assertEqual(denied.status_code, 404, denied.content)

        teacher, csrf, teacher_proxy = self.client_for(
            identifier=self.owner.username, portal="TEACHING"
        )
        detail = teacher.get(
            f"/api/v2/teaching/courses/{self.course.public_id}/archives/{job.public_id}",
            HTTP_X_PORTAL="TEACHING",
            **teacher_proxy,
        )
        self.assertEqual(detail.status_code, 200, detail.content)
        url = f"/api/v2/teaching/courses/{self.course.public_id}/archives/{job.public_id}/exports"
        headers = {
            "HTTP_X_PORTAL": "TEACHING",
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_IDEMPOTENCY_KEY": "p11-export-api",
            "HTTP_IF_MATCH": detail["ETag"],
            **teacher_proxy,
        }
        first = teacher.post(url, {}, content_type="application/json", **headers)
        replay = teacher.post(url, {}, content_type="application/json", **headers)
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(replay.status_code, 201, replay.content)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(first.json(), replay.json())
        self.assertEqual(ArchiveExportGrant.objects.count(), 1)

    def test_admin_compensation_api_requires_recent_auth_reason_idempotency_and_etag(self) -> None:
        item = CompensationTask.objects.create(
            task_type="RETRY_ARCHIVE_JOB",
            subject_type="ARCHIVE_JOB",
            subject_ref="missing",
            status=CompensationTask.Status.DEAD,
            attempt_count=2,
            max_attempts=2,
            payload_masked={},
            trace_id="9" * 32,
        )
        admin, csrf, proxy = self.client_for(identifier=self.admin.username, portal="PLATFORM")
        headers = {
            "HTTP_X_PORTAL": "PLATFORM",
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_IDEMPOTENCY_KEY": "p11-compensation-api",
            "HTTP_IF_MATCH": f'"{item.row_version}"',
            **proxy,
        }
        response = admin.post(
            "/api/v2/platform/compensations",
            {"compensation_id": item.public_id, "reason": "operator approved retry"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 202, response.content)
        replay = admin.post(
            "/api/v2/platform/compensations",
            {"compensation_id": item.public_id, "reason": "operator approved retry"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(replay.status_code, 202, replay.content)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")

    def test_admin_instance_destroy_api_is_recent_authenticated_and_idempotent(self) -> None:
        admin, csrf, proxy = self.client_for(identifier=self.admin.username, portal="PLATFORM")
        url = f"/api/v2/platform/instances/{self.instance.public_id}/destroy"
        headers = {
            "HTTP_X_PORTAL": "PLATFORM",
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_IDEMPOTENCY_KEY": "p11-instance-destroy-api",
            "HTTP_IF_MATCH": f'"{self.instance.row_version}"',
            **proxy,
        }
        with (
            patch("apps.archives.tasks.destroy_instance_by_admin.apply_async") as enqueue,
            patch("apps.core.tasks.relay_outbox.apply_async"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            first = admin.post(
                url,
                {"reason": "operator confirmed orphan cleanup"},
                content_type="application/json",
                **headers,
            )
            replay = admin.post(
                url,
                {"reason": "operator confirmed orphan cleanup"},
                content_type="application/json",
                **headers,
            )
        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(replay.status_code, 202, replay.content)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(first.json(), replay.json())
        enqueue.assert_called_once()

from django.test import TestCase

from apps.accounts.models import User
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.experiments.services import publish_publication
from apps.experiments.tests.helpers import context as experiment_context
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.governance.models import Quota, RuntimeAdapter

from ..adapters import fake_runtime, reset_fake_runtime
from ..errors import ProvisioningStateConflict
from ..models import ProvisioningInstance, ProvisioningJob, ProvisioningStageEvent
from ..selectors import job_for_user
from ..services import (
    cancel_queued_provisioning,
    compensate_provisioning,
    execute_provisioning_job,
    retry_provisioning,
    start_provisioning,
)


class ProvisioningServiceTests(TestCase):
    def setUp(self) -> None:
        reset_fake_runtime()
        self.owner, self.course, self.template_version, self.rubric_version = create_domain(
            suffix="p07"
        )
        self.adapter = self.template_version.runtime_adapter
        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            driver=RuntimeAdapter.Driver.FAKE,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        )
        self.adapter.refresh_from_db()
        self.enrollment = create_enrollment(self.course, suffix="p07-student")
        self.publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="p07",
        )
        self.platform_quota = Quota.objects.create(
            scope_type=Quota.ScopeType.PLATFORM,
            scope_key="PLATFORM",
            max_concurrent_instances=10,
            max_concurrent_starts=10,
            max_cpu_millicores=20000,
            max_memory_mb=40000,
            max_disk_gb=200,
            change_reason="P07 test quota",
        )
        Quota.objects.create(
            scope_type=Quota.ScopeType.COURSE,
            scope_key=f"COURSE:{self.course.public_id}",
            course=self.course,
            max_concurrent_instances=10,
            max_concurrent_starts=10,
            max_cpu_millicores=20000,
            max_memory_mb=40000,
            max_disk_gb=200,
            change_reason="P07 test quota",
        )
        Quota.objects.create(
            scope_type=Quota.ScopeType.USER,
            scope_key=f"USER:{self.enrollment.student.public_id}",
            user=self.enrollment.student,
            max_concurrent_instances=10,
            max_concurrent_starts=10,
            max_cpu_millicores=20000,
            max_memory_mb=40000,
            max_disk_gb=200,
            change_reason="P07 test quota",
        )
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=experiment_context(self.owner),
        )
        self.task = published.tasks.get(student=self.enrollment.student)
        self.context = ActorContext(
            self.task.student.public_id,
            "USER",
            "p07" * 8,
        )

    def tearDown(self) -> None:
        reset_fake_runtime()

    def _start(self) -> ProvisioningJob:
        _, job = start_provisioning(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        return job

    def _new_task(self, suffix: str) -> tuple[ExperimentTask, User]:
        enrollment = create_enrollment(self.course, suffix=suffix)
        publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix=suffix,
        )
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=publication.public_id,
            actor=self.owner,
            expected_version=publication.row_version,
            selected_ids=[],
            context=experiment_context(self.owner),
        )
        return published.tasks.get(student=enrollment.student), enrollment.student

    def test_success_writes_append_only_start_and_pass_events_for_all_stages(self) -> None:
        job = self._start()
        finished = execute_provisioning_job(job_id=job.public_id)

        self.assertEqual(finished.status, ProvisioningJob.Status.PASSED)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, self.task.Status.READY)
        events = list(
            ProvisioningStageEvent.objects.filter(job=finished).order_by("created_at", "pk")
        )
        self.assertEqual(len(events), len(ProvisioningJob.Stage.values) * 2)
        for stage in ProvisioningJob.Stage.values:
            stage_events = [event for event in events if event.stage == stage]
            self.assertEqual([event.status for event in stage_events], ["STARTED", "PASSED"])
        instance = ProvisioningInstance.objects.get(task=self.task)
        self.assertEqual(instance.status, ProvisioningInstance.Status.READY)
        self.assertTrue(instance.external_id)

    def test_each_fake_failure_records_failed_stage_and_retryable_failure(self) -> None:
        for index, stage in enumerate(ProvisioningJob.Stage.values):
            with self.subTest(stage=stage):
                reset_fake_runtime()
                task, student = self._new_task(f"p07-failure-{index}")
                fake_runtime().failures[stage] = f"FAKE_{stage}_FAILED"
                _, job = start_provisioning(
                    task_id=task.public_id,
                    actor=student,
                    expected_version=task.row_version,
                    context=ActorContext(student.public_id, "USER", f"f{index}" * 32),
                )
                finished = execute_provisioning_job(job_id=job.public_id)
                self.assertEqual(finished.status, ProvisioningJob.Status.FAILED)
                self.assertTrue(finished.retryable)
                failed_event = ProvisioningStageEvent.objects.get(
                    job=finished,
                    stage=stage,
                    status=ProvisioningStageEvent.Status.FAILED,
                )
                self.assertEqual(failed_event.error_code, f"FAKE_{stage}_FAILED")

    def test_partial_create_failure_requires_compensation_before_retry(self) -> None:
        fake_runtime().failures[ProvisioningJob.Stage.CREATE] = "FAKE_CREATE_FAILED"
        fake_runtime().partial_success.add(ProvisioningJob.Stage.CREATE)
        job = self._start()
        failed = execute_provisioning_job(job_id=job.public_id)
        self.assertEqual(failed.status, ProvisioningJob.Status.FAILED)
        failed.refresh_from_db()
        instance = ProvisioningInstance.objects.get(task=self.task)
        self.assertTrue(instance.external_id)
        self.assertIsNotNone(failed.compensation_task_id)

        self.task.refresh_from_db()
        with self.assertRaises(ProvisioningStateConflict):
            retry_provisioning(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_version=self.task.row_version,
                context=self.context,
            )

        compensation = failed.compensation_task
        compensate_provisioning(compensation)
        compensation.refresh_from_db()
        instance.refresh_from_db()
        self.assertEqual(instance.status, ProvisioningInstance.Status.DESTROYED)
        self.assertIsNone(instance.external_id)

        self.task.refresh_from_db()
        _, retry_job = retry_provisioning(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        self.assertEqual(retry_job.attempt_no, 2)
        self.assertEqual(
            job_for_user(actor=self.task.student, task_id=self.task.public_id).attempt_no,
            2,
        )

    def test_queued_cancel_releases_reservation_and_does_not_call_runtime(self) -> None:
        job = self._start()
        self.task.refresh_from_db()
        _, cancelled = cancel_queued_provisioning(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        self.assertEqual(cancelled.status, ProvisioningJob.Status.CANCELLED)
        self.assertEqual(cancelled.reservation.status, "RELEASED")
        self.assertEqual(fake_runtime().calls, [])
        self.assertFalse(ProvisioningStageEvent.objects.filter(job=job).exists())
        self.assertEqual(
            ProvisioningInstance.objects.get(task=self.task).status,
            ProvisioningInstance.Status.DESTROYED,
        )

    def test_worker_replay_is_idempotent(self) -> None:
        job = self._start()
        first = execute_provisioning_job(job_id=job.public_id)
        calls = list(fake_runtime().calls)
        second = execute_provisioning_job(job_id=job.public_id)
        self.assertEqual(first.public_id, second.public_id)
        self.assertEqual(second.status, ProvisioningJob.Status.PASSED)
        self.assertEqual(calls, fake_runtime().calls)

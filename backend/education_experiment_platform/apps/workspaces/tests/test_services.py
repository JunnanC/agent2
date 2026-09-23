import json

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.courses.models import Enrollment
from apps.courses.services import ActorContext
from apps.experiments.models import TaskPublication
from apps.experiments.services import allowed_actions, publish_publication
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.governance.models import Quota, RuntimeAdapter
from apps.provisioning.adapters import reset_fake_runtime
from apps.provisioning.services import execute_provisioning_job, start_provisioning

from ..errors import WorkspaceSessionInvalid, WorkspaceSessionRevoked
from ..models import WorkspaceSession
from ..permissions import require_workspace_session
from ..services import enter_task, renew_session, revoke_session


class WorkspaceSessionServiceTests(TestCase):
    def setUp(self) -> None:
        reset_fake_runtime()
        self.teacher, self.course, template_version, rubric_version = create_domain(suffix="p08")
        RuntimeAdapter.objects.filter(pk=template_version.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.FAKE,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        )
        self.student_enrollment = create_enrollment(self.course, suffix="p08-student")
        self.publication = create_draft_publication(
            owner=self.teacher,
            course=self.course,
            template_version=template_version,
            rubric_version=rubric_version,
            suffix="p08",
        )
        values = {
            "max_concurrent_instances": 10,
            "max_concurrent_starts": 10,
            "max_cpu_millicores": 20_000,
            "max_memory_mb": 40_000,
            "max_disk_gb": 200,
        }
        Quota.objects.create(scope_type=Quota.ScopeType.PLATFORM, scope_key="PLATFORM", **values)
        Quota.objects.create(
            scope_type=Quota.ScopeType.COURSE,
            scope_key=f"COURSE:{self.course.public_id}",
            course=self.course,
            **values,
        )
        Quota.objects.create(
            scope_type=Quota.ScopeType.USER,
            scope_key=f"USER:{self.student_enrollment.student.public_id}",
            user=self.student_enrollment.student,
            **values,
        )
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.teacher,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=ActorContext(self.teacher.public_id, "TEACHING", "p08" * 8),
        )
        self.task = published.tasks.get(student=self.student_enrollment.student)
        _, job = start_provisioning(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=ActorContext(self.task.student.public_id, "USER", "s" * 32),
        )
        execute_provisioning_job(job_id=job.public_id)
        self.task.refresh_from_db()
        self.context = ActorContext(self.task.student.public_id, "USER", "w" * 32)

    def tearDown(self) -> None:
        reset_fake_runtime()

    def test_ready_task_exposes_enter_and_issue_is_scoped(self) -> None:
        self.assertEqual(
            allowed_actions(self.task, actor=self.task.student),
            ["ENTER", "REQUEST_EXTENSION"],
        )
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        self.assertEqual(session.status, WorkspaceSession.Status.ACTIVE)
        self.assertNotEqual(session.token_hash, token)
        self.assertNotIn(token, session.token_hash)
        require_workspace_session(session=session, token=token, task_id=self.task.public_id)

    def test_renew_rotates_token_and_old_token_is_invalid(self) -> None:
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        renewed, new_token = renew_session(
            session=session, token=token, actor=self.task.student, context=self.context
        )
        self.assertNotEqual(token, new_token)
        with self.assertRaises(WorkspaceSessionInvalid):
            require_workspace_session(session=renewed, token=token, task_id=self.task.public_id)
        require_workspace_session(session=renewed, token=new_token, task_id=self.task.public_id)

    def test_revoke_is_idempotent_at_row_level_and_invalidates_ticket(self) -> None:
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        revoked = revoke_session(
            session=session,
            token=token,
            actor=self.task.student,
            expected_version=session.row_version,
            context=self.context,
        )
        self.assertEqual(revoked.status, WorkspaceSession.Status.REVOKED)
        with self.assertRaises(WorkspaceSessionRevoked):
            require_workspace_session(session=revoked, token=token, task_id=self.task.public_id)

    def test_ticket_is_invalidated_when_its_live_scope_is_revoked(self) -> None:
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )

        for model, pk, changes in (
            (
                Enrollment,
                self.student_enrollment.pk,
                {"status": Enrollment.Status.DROPPED, "ended_at": timezone.now()},
            ),
            (
                User,
                self.task.student_id,
                {"account_status": User.AccountStatus.DISABLED, "is_active": False},
            ),
            (
                TaskPublication,
                self.publication.pk,
                {"status": TaskPublication.Status.WITHDRAWN},
            ),
        ):
            original = {name: getattr(model.objects.get(pk=pk), name) for name in changes}
            model.objects.filter(pk=pk).update(**changes)
            session = WorkspaceSession.objects.select_related(
                "student", "task__enrollment", "task__publication", "instance"
            ).get(pk=session.pk)
            with self.assertRaises(WorkspaceSessionRevoked):
                require_workspace_session(
                    session=session,
                    token=token,
                    task_id=self.task.public_id,
                )
            model.objects.filter(pk=pk).update(**original)

    def test_gateway_records_only_whitelisted_operation_and_returns_unified_errors(self) -> None:
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        client = Client()
        response = client.post(
            f"/workspace/{session.public_id}/operations",
            data=json.dumps({"operation": "RUN_CHECK", "arguments": {"secret": "redact-me"}}),
            content_type="application/json",
            HTTP_X_PORTAL="USER",
            HTTP_X_WORKSPACE_TOKEN=token,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["event_type"], "operation.run_check")
        self.assertNotIn("redact-me", response.content.decode())

        denied = client.post(
            f"/workspace/{session.public_id}/operations",
            data=json.dumps({"operation": "SHELL"}),
            content_type="application/json",
            HTTP_X_PORTAL="USER",
            HTTP_X_WORKSPACE_TOKEN=token,
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], "WORKSPACE_OPERATION_DENIED")

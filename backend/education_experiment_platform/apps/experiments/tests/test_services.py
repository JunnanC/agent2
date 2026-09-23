from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.models import OutboxEvent
from apps.courses.models import Chapter, Course, Enrollment
from apps.courses.tests.helpers import create_draft_course, create_teacher

from ..errors import (
    PublicationPrerequisiteBlocked,
    PublicationValidationError,
    TaskExtensionConflict,
    TaskStateConflict,
)
from ..models import (
    ExperimentTask,
    PublicationAudience,
    TaskExtensionDecision,
    TaskPublication,
    TaskStateTransition,
)
from ..services import (
    allowed_actions,
    assign_late_enrollment_task,
    decide_extension,
    execute_publication_assignment,
    prerequisite_blockers_for_publication,
    publish_publication,
    request_extension,
    start_task,
    transition_task,
    update_publication,
    withdraw_publication,
)
from .helpers import context, create_domain, create_draft_publication, create_enrollment


class ExperimentServiceTests(TestCase):
    def setUp(self) -> None:
        self.owner, self.course, self.template_version, self.rubric_version = create_domain()
        self.enrollment = create_enrollment(self.course)
        self.publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
        )

    def _publish(self) -> TaskPublication:
        publication, status = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=context(self.owner),
        )
        self.assertEqual(status, 201)
        return publication

    def test_sync_publish_freezes_all_active_audience_and_assigns_once(self) -> None:
        published = self._publish()
        audience = PublicationAudience.objects.get(publication=published)
        self.assertEqual(audience.snapshot_enrollment_ids, [self.enrollment.public_id])
        self.assertEqual(ExperimentTask.objects.filter(publication=published).count(), 1)
        self.assertEqual(TaskStateTransition.objects.filter(task__publication=published).count(), 1)
        self.assertTrue(OutboxEvent.objects.filter(event_type="experiment.task_assigned").exists())

    @override_settings(P06_PUBLICATION_SYNC_LIMIT=1)
    @patch("apps.experiments.tasks.assign_publication_tasks.delay")
    def test_async_boundary_uses_frozen_snapshot_and_worker_replay_is_idempotent(
        self, delay: object
    ) -> None:
        published, status = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=context(self.owner),
        )
        self.assertEqual(status, 202)
        self.assertEqual(published.status, TaskPublication.Status.PUBLISHING)
        Enrollment.objects.filter(pk=self.enrollment.pk).update(status=Enrollment.Status.DROPPED)
        completed = execute_publication_assignment(
            publication_id=published.public_id,
            context=context(self.owner, "WORKER"),
        )
        self.assertEqual(completed.status, TaskPublication.Status.PUBLISHED)
        self.assertEqual(ExperimentTask.objects.filter(publication=published).count(), 1)
        execute_publication_assignment(
            publication_id=published.public_id,
            context=context(self.owner, "WORKER"),
        )
        self.assertEqual(ExperimentTask.objects.filter(publication=published).count(), 1)

    def test_selected_audience_rejects_cross_course_or_inactive_enrollment(self) -> None:
        publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="selected",
            audience_mode=TaskPublication.AudienceMode.SELECTED,
        )
        other_owner = create_teacher(suffix="p06-other-owner")
        other_course = create_draft_course(other_owner, code="P06-OTHER")
        Course.objects.filter(pk=other_course.pk).update(status=Course.Status.PUBLISHED)
        other_course.refresh_from_db()
        other = create_enrollment(other_course, suffix="other-student")
        with self.assertRaises(PublicationValidationError):
            publish_publication(
                course_id=self.course.public_id,
                publication_id=publication.public_id,
                actor=self.owner,
                expected_version=publication.row_version,
                selected_ids=[other.public_id],
                context=context(self.owner),
            )
        self.assertIsNotNone(other_owner)

    def test_start_checks_prerequisite_and_terminal_state(self) -> None:
        chapter = Chapter.objects.create(course=self.course, title="Required", position=1)
        blocked = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="blocked",
            prerequisites=[{"kind": "CHAPTER", "chapter_id": chapter.public_id}],
        )
        blocked, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=blocked.public_id,
            actor=self.owner,
            expected_version=blocked.row_version,
            selected_ids=[],
            context=context(self.owner),
        )
        task = ExperimentTask.objects.get(publication=blocked)
        blockers = prerequisite_blockers_for_publication(
            publication=blocked, student=self.enrollment.student
        )
        self.assertEqual(blockers[0]["reason"], "CHAPTER_COMPLETION_FACT_UNAVAILABLE")
        with self.assertRaises(PublicationPrerequisiteBlocked):
            start_task(
                task_id=task.public_id,
                actor=self.enrollment.student,
                expected_version=task.row_version,
                context=context(self.enrollment.student, "USER"),
            )
        ExperimentTask.objects.filter(pk=task.pk).update(status=ExperimentTask.Status.COMPLETED)
        task.refresh_from_db()
        with self.assertRaises(TaskStateConflict):
            start_task(
                task_id=task.public_id,
                actor=self.enrollment.student,
                expected_version=task.row_version,
                context=context(self.enrollment.student, "USER"),
            )

    def test_failed_transition_records_stage_and_allows_only_declared_retry(self) -> None:
        published = self._publish()
        task = ExperimentTask.objects.get(publication=published)
        task = transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.PROVISIONING,
            actor=task.student,
            expected_version=task.row_version,
            trigger="START",
            reason="start",
            context=context(task.student, "USER"),
        )
        task = transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.FAILED,
            actor=None,
            expected_version=task.row_version,
            trigger="PROVISION",
            reason="runtime unavailable",
            detail={"retryable": True, "error_code": "RUNTIME_UNAVAILABLE"},
            context=context(self.owner, "WORKER"),
        )
        self.assertEqual(task.current_failure["previous_status"], "PROVISIONING")
        self.assertEqual(allowed_actions(task, actor=task.student), ["RETRY", "REQUEST_EXTENSION"])
        with self.assertRaises(TaskStateConflict):
            transition_task(
                task_id=task.public_id,
                to_status=ExperimentTask.Status.READY,
                actor=None,
                expected_version=task.row_version,
                trigger="RETRY",
                reason="invalid retry target",
                context=context(self.owner, "WORKER"),
            )
        retried = transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.PROVISIONING,
            actor=None,
            expected_version=task.row_version,
            trigger="RETRY",
            reason="retry",
            context=context(self.owner, "WORKER"),
        )
        self.assertEqual(retried.status, ExperimentTask.Status.PROVISIONING)

    def test_extension_decision_is_single_and_does_not_change_publication_window(self) -> None:
        published = self._publish()
        task = ExperimentTask.objects.get(publication=published)
        original_window = published.window_end
        extension = request_extension(
            task_id=task.public_id,
            actor=task.student,
            data={
                "requested_deadline": original_window + timezone.timedelta(days=1),
                "reason": "medical leave",
            },
            context=context(task.student, "USER"),
        )
        decided = decide_extension(
            course_id=self.course.public_id,
            request_id=extension.public_id,
            actor=self.owner,
            decision=TaskExtensionDecision.Decision.APPROVE,
            reason="approved",
            expected_version=extension.row_version,
            context=context(self.owner),
        )
        with self.assertRaises(TaskExtensionConflict):
            decide_extension(
                course_id=self.course.public_id,
                request_id=extension.public_id,
                actor=self.owner,
                decision=TaskExtensionDecision.Decision.REJECT,
                reason="late second decision",
                expected_version=extension.row_version,
                context=context(self.owner),
            )
        published.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(published.window_end, original_window)
        self.assertEqual(task.effective_deadline, decided.requested_deadline)
        self.assertEqual(TaskExtensionDecision.objects.filter(request=extension).count(), 1)

    def test_cross_course_late_enrollment_never_creates_task(self) -> None:
        published = self._publish()
        other_owner = create_teacher(suffix="p06-late-owner")
        other_course = create_draft_course(other_owner, code="P06-LATE-OTHER")
        Course.objects.filter(pk=other_course.pk).update(status=Course.Status.PUBLISHED)
        other_course.refresh_from_db()
        other = create_enrollment(other_course, suffix="late-other-student")
        result = assign_late_enrollment_task(
            enrollment_id=other.public_id,
            publication_id=published.public_id,
            context=context(self.owner, "WORKER"),
        )
        self.assertIsNone(result)

    def test_withdraw_preserves_completed_task(self) -> None:
        published = self._publish()
        task = ExperimentTask.objects.get(publication=published)
        ExperimentTask.objects.filter(pk=task.pk).update(status=ExperimentTask.Status.COMPLETED)
        withdrawn = withdraw_publication(
            course_id=self.course.public_id,
            publication_id=published.public_id,
            actor=self.owner,
            expected_version=published.row_version,
            context=context(self.owner),
        )
        task.refresh_from_db()
        self.assertEqual(withdrawn.status, TaskPublication.Status.WITHDRAWN)
        self.assertEqual(task.status, ExperimentTask.Status.COMPLETED)
        self.assertIsNone(task.terminal_target)

    def test_invalid_patch_reference_is_controlled_and_scope_is_hidden(self) -> None:
        with self.assertRaises(PublicationValidationError):
            update_publication(
                course_id=self.course.public_id,
                publication_id=self.publication.public_id,
                actor=self.owner,
                expected_version=self.publication.row_version,
                data={"template_version_id": "missing"},
                context=context(self.owner),
            )
        stranger = create_enrollment(self.course, suffix="stranger").student
        with self.assertRaises(ResourceNotFound):
            start_task(
                task_id="missing",
                actor=stranger,
                expected_version=1,
                context=context(stranger, "USER"),
            )
        with self.assertRaises(RowVersionConflict):
            update_publication(
                course_id=self.course.public_id,
                publication_id=self.publication.public_id,
                actor=self.owner,
                expected_version=99,
                data={"title": "stale"},
                context=context(self.owner),
            )

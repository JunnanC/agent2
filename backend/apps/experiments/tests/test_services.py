from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.models import OutboxEvent
from apps.courses.models import Course, Enrollment
from apps.courses.tests.helpers import create_draft_course, create_teacher
from apps.labtemplates.models import ExperimentImage, TemplateChapter, TemplateTask

from ..errors import (
    PublicationValidationError,
    TaskExtensionConflict,
    TaskStateConflict,
)
from ..models import (
    ExperimentTask,
    PublicationAudience,
    PublicationChapter,
    PublicationTask,
    TaskExtensionDecision,
    TaskPublication,
    TaskStateTransition,
)
from ..services import (
    allowed_actions,
    assign_late_enrollment_task,
    decide_extension,
    execute_publication_assignment,
    precheck_template_version,
    publish_publication,
    request_extension,
    student_learning_history,
    teaching_progress,
    transition_task,
    update_publication,
    withdraw_publication,
)
from .helpers import context, create_domain, create_draft_publication, create_enrollment


class ExperimentServiceTests(TestCase):
    def setUp(self) -> None:
        self.owner, self.course, self.template_version, self.rubric_version = create_domain()
        ExperimentImage.objects.create(
            template_version=self.template_version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry=self.template_version.image.registry,
            repository=self.template_version.image.repository,
            requested_tag=self.template_version.image.display_tag or "stable",
            resolved_digest=self.template_version.image.digest,
            image_asset=self.template_version.image,
            status=ExperimentImage.Status.READY,
            scan_status=ExperimentImage.ScanStatus.CLEAN,
            trace_id="publications-test".ljust(32, "0"),
            created_by=self.owner,
        )
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

    def test_student_history_and_course_progress_include_student_experiment_rows(self) -> None:
        publication = self._publish()
        task = ExperimentTask.objects.get(publication=publication, student=self.enrollment.student)

        history = student_learning_history(actor=self.enrollment.student)
        course = next(
            course
            for year in history["years"]
            for term in year["terms"]
            for course in term["courses"]
            if course["course_id"] == self.course.public_id
        )
        self.assertGreaterEqual(len(history["years"]), 4)
        self.assertEqual(course["experiments"][0]["task_id"], task.public_id)
        self.assertEqual(course["experiments"][0]["status"], task.status)

        progress = teaching_progress(course_id=self.course.public_id, actor=self.owner)
        experiment = next(
            item
            for item in progress["experiments"]
            if item["publication_id"] == publication.public_id
        )
        self.assertEqual(experiment["students"][0]["student_id"], self.enrollment.student.public_id)
        self.assertEqual(experiment["students"][0]["task_id"], task.public_id)

    def test_sync_publish_freezes_all_active_audience_and_assigns_once(self) -> None:
        published = self._publish()
        audience = PublicationAudience.objects.get(publication=published)
        self.assertEqual(audience.snapshot_enrollment_ids, [self.enrollment.public_id])
        self.assertEqual(ExperimentTask.objects.filter(publication=published).count(), 1)
        self.assertEqual(TaskStateTransition.objects.filter(task__publication=published).count(), 1)
        self.assertTrue(OutboxEvent.objects.filter(event_type="experiment.task_assigned").exists())

    def test_publish_copies_ordered_immutable_chapter_and_task_snapshots(self) -> None:
        published = self._publish()
        chapter = PublicationChapter.objects.get(publication=published)
        task = PublicationTask.objects.get(publication_chapter=chapter)
        source_chapter = published.template_version.chapters.first()
        source_task = source_chapter.tasks.first()
        self.assertEqual(chapter.source_chapter_id, source_chapter.public_id)
        self.assertEqual(task.source_task_id, source_task.public_id)
        self.assertEqual(task.image_digest, published.image_digest)
        self.assertEqual(task.resource_profile_snapshot, {})
        self.assertEqual(task.execution_snapshot["tests_digest"], "")
        self.assertTrue(published.template_digest)
        self.assertTrue(published.publication_digest)

        TemplateChapter.objects.filter(pk=published.template_version.chapters.first().pk).update(
            title="Changed after publication"
        )
        TemplateTask.objects.filter(
            pk=published.template_version.chapters.first().tasks.first().pk
        ).update(title="Changed task after publication")
        chapter.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(chapter.title, "Introduction")
        self.assertEqual(task.title, "First task")

    def test_selected_audience_order_does_not_change_publication_digest(self) -> None:
        first_student = self.enrollment
        second_student = create_enrollment(self.course, suffix="publications-selected-second")
        first = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            audience_mode=TaskPublication.AudienceMode.SELECTED,
        )
        second = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            audience_mode=TaskPublication.AudienceMode.SELECTED,
        )
        fixed_start = timezone.now() - timezone.timedelta(minutes=5)
        fixed_end = fixed_start + timezone.timedelta(days=2)
        fixed_deadline = fixed_start + timezone.timedelta(days=1)
        TaskPublication.objects.filter(pk__in=[first.pk, second.pk]).update(
            window_start=fixed_start,
            window_end=fixed_end,
            assignment_deadline=fixed_deadline,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        first_published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=first.public_id,
            actor=self.owner,
            expected_version=first.row_version,
            selected_ids=[first_student.public_id, second_student.public_id],
            context=context(self.owner),
        )
        second_published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=second.public_id,
            actor=self.owner,
            expected_version=second.row_version,
            selected_ids=[second_student.public_id, first_student.public_id],
            context=context(self.owner),
        )
        self.assertEqual(first_published.publication_digest, second_published.publication_digest)

    def test_published_template_without_questions_is_rejected(self) -> None:
        TemplateTask.objects.filter(chapter__template_version=self.template_version).update(active=False)
        with self.assertRaises(PublicationValidationError):
            precheck_template_version(template_version=self.template_version)

    @override_settings(PUBLICATION_SYNC_LIMIT=1)
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

    def test_publish_rejects_invalid_audience_without_side_effects(self) -> None:
        publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="selected",
            audience_mode=TaskPublication.AudienceMode.SELECTED,
        )
        other_owner = create_teacher(suffix="publications-other-owner")
        other_course = create_draft_course(other_owner, code="publications-OTHER")
        Course.objects.filter(pk=other_course.pk).update(status=Course.Status.PUBLISHED)
        other_course.refresh_from_db()
        other = create_enrollment(other_course, suffix="other-student")
        inactive = create_enrollment(self.course, suffix="inactive-student")
        Enrollment.objects.filter(pk=inactive.pk).update(status=Enrollment.Status.DROPPED)

        invalid_selections: tuple[tuple[list[str], str], ...] = (
            ([], "指定学生模式至少选择一名在读学生"),
            (
                [self.enrollment.public_id, self.enrollment.public_id],
                "指定学生列表不能包含重复记录",
            ),
            ([other.public_id], "指定学生包含不存在、非在读或其他课程的选课记录"),
            ([inactive.public_id], "指定学生包含不存在、非在读或其他课程的选课记录"),
        )
        for selected_ids, message in invalid_selections:
            with (
                self.subTest(selected_ids=selected_ids),
                self.assertRaises(PublicationValidationError) as raised,
            ):
                publish_publication(
                    course_id=self.course.public_id,
                    publication_id=publication.public_id,
                    actor=self.owner,
                    expected_version=publication.row_version,
                    selected_ids=selected_ids,
                    context=context(self.owner),
                )
            self.assertEqual(raised.exception.detail["selected_enrollment_ids"], message)

        with self.assertRaises(PublicationValidationError) as raised:
            publish_publication(
                course_id=self.course.public_id,
                publication_id=self.publication.public_id,
                actor=self.owner,
                expected_version=self.publication.row_version,
                selected_ids=[self.enrollment.public_id],
                context=context(self.owner),
            )
        self.assertEqual(
            raised.exception.detail["selected_enrollment_ids"],
            "全部在读学生模式不能指定单独受众",
        )

        publication.refresh_from_db()
        self.publication.refresh_from_db()
        self.assertEqual(publication.status, TaskPublication.Status.DRAFT)
        self.assertEqual(self.publication.status, TaskPublication.Status.DRAFT)
        self.assertFalse(PublicationAudience.objects.filter(publication=publication).exists())
        self.assertFalse(PublicationAudience.objects.filter(publication=self.publication).exists())
        self.assertFalse(ExperimentTask.objects.filter(publication=publication).exists())
        self.assertFalse(ExperimentTask.objects.filter(publication=self.publication).exists())
        self.assertIsNotNone(other_owner)

    def test_failed_transition_records_stage_and_allows_only_declared_retry(self) -> None:
        published = self._publish()
        task = ExperimentTask.objects.get(publication=published)
        task = transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.IN_PROGRESS,
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
        self.assertEqual(task.current_failure["previous_status"], "IN_PROGRESS")
        self.assertEqual(allowed_actions(task, actor=task.student), ["REQUEST_EXTENSION"])
        with self.assertRaises(TaskStateConflict):
            transition_task(
                task_id=task.public_id,
                to_status=ExperimentTask.Status.APPROVED,
                actor=None,
                expected_version=task.row_version,
                trigger="RETRY",
                reason="invalid retry target",
                context=context(self.owner, "WORKER"),
            )
        retried = transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.IN_PROGRESS,
            actor=None,
            expected_version=task.row_version,
            trigger="RETRY",
            reason="retry",
            context=context(self.owner, "WORKER"),
        )
        self.assertEqual(retried.status, ExperimentTask.Status.IN_PROGRESS)

    def test_allowed_actions_no_longer_offer_retired_workspace_entry(self) -> None:
        task = self._publish().tasks.get()
        for status in ("ASSIGNED", "IN_PROGRESS", "REPORT_DRAFT"):
            ExperimentTask.objects.filter(pk=task.pk).update(status=status)
            task.refresh_from_db()
            self.assertEqual(allowed_actions(task, actor=task.student), ["REQUEST_EXTENSION"])

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
        other_owner = create_teacher(suffix="publications-late-owner")
        other_course = create_draft_course(other_owner, code="publications-LATE-OTHER")
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
            from ..assessment import assessment_data
            assessment_data(actor=stranger, task_id="missing")
        with self.assertRaises(RowVersionConflict):
            update_publication(
                course_id=self.course.public_id,
                publication_id=self.publication.public_id,
                actor=self.owner,
                expected_version=99,
                data={"title": "stale"},
                context=context(self.owner),
            )

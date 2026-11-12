from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.models import OutboxEvent
from apps.courses.models import Chapter, Course, Enrollment
from apps.courses.tests.helpers import create_draft_course, create_teacher
from apps.governance.models import RuntimeAdapter
from apps.labtemplates.models import ExperimentImage, TemplateChapter, TemplateTask, TemplateVersion
from apps.provisioning.errors import ProvisioningConfigurationError

from ..errors import (
    PublicationPrerequisiteBlocked,
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
    prerequisite_blockers_for_publication,
    publish_publication,
    request_extension,
    start_task,
    start_task_runtime,
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

    def test_student_runtime_entry_rejects_mutable_runtime_overrides(self) -> None:
        published = self._publish()
        task = ExperimentTask.objects.get(publication=published)

        with self.assertRaises(ProvisioningConfigurationError):
            start_task_runtime(
                task_id=task.public_id,
                actor=task.student,
                context=context(task.student, portal="USER"),
                payload={"image": "mutable:latest", "cpu_millicores": 100},
            )

    def test_publish_freezes_template_execution_and_runtime_inputs(self) -> None:
        published = self._publish()
        task = ExperimentTask.objects.get(publication=published)
        original = {
            "template_spec_digest": task.template_spec_digest,
            "execution_spec": task.execution_spec,
            "runtime_adapter_id": task.runtime_adapter_id,
            "runtime_adapter_driver": task.runtime_adapter_driver,
            "runtime_adapter_config_ref": task.runtime_adapter_config_ref,
            "image_id": task.image_id,
            "image_digest": task.image_digest,
            "resource_profile_id": task.resource_profile_id,
            "resource_profile_snapshot": task.resource_profile_snapshot,
        }
        replacement = RuntimeAdapter.objects.create(
            code="runtime-publications-replacement",
            name="Replacement runtime",
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
            config_ref="runtime/replacement",
        )
        self.template_version.refresh_from_db()
        TemplateVersion.objects.filter(pk=self.template_version.pk).update(
            spec_digest="f" * 64,
            execution_spec={"language": "python", "entrypoint": "changed.py"},
            runtime_adapter=replacement,
        )

        task.refresh_from_db()
        publication_snapshot = TaskPublication.objects.get(pk=published.pk)
        self.assertEqual(task.template_spec_digest, original["template_spec_digest"])
        self.assertEqual(task.execution_spec, original["execution_spec"])
        self.assertEqual(task.runtime_adapter_id, original["runtime_adapter_id"])
        self.assertEqual(task.runtime_adapter_driver, original["runtime_adapter_driver"])
        self.assertEqual(task.runtime_adapter_config_ref, original["runtime_adapter_config_ref"])
        self.assertEqual(task.image_id, original["image_id"])
        self.assertEqual(task.image_digest, original["image_digest"])
        self.assertEqual(task.resource_profile_id, original["resource_profile_id"])
        self.assertEqual(task.resource_profile_snapshot, original["resource_profile_snapshot"])
        self.assertEqual(
            publication_snapshot.template_spec_digest, original["template_spec_digest"]
        )
        self.assertEqual(publication_snapshot.runtime_adapter_id, original["runtime_adapter_id"])

    def test_publish_copies_ordered_immutable_chapter_and_task_snapshots(self) -> None:
        published = self._publish()
        chapter = PublicationChapter.objects.get(publication=published)
        task = PublicationTask.objects.get(publication_chapter=chapter)
        source_chapter = published.template_version.chapters.first()
        source_task = source_chapter.tasks.first()
        self.assertEqual(chapter.source_chapter_id, source_chapter.public_id)
        self.assertEqual(task.source_task_id, source_task.public_id)
        self.assertEqual(task.image_digest, published.image_digest)
        self.assertEqual(task.resource_profile_snapshot["cpu_request_millicores"], 2000)
        self.assertEqual(task.execution_snapshot["execution_spec"]["entrypoint"], "main.py")
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

    def test_precheck_rejects_draft_chapter_and_task_rows(self) -> None:
        chapter = TemplateChapter.objects.get(template_version=self.template_version)
        TemplateChapter.objects.filter(pk=chapter.pk).update(status=TemplateChapter.Status.DRAFT)
        with self.assertRaises(PublicationValidationError) as chapter_error:
            precheck_template_version(template_version=self.template_version)
        self.assertEqual(
            chapter_error.exception.detail["chapters"]["not_published"],
            [chapter.public_id],
        )

        TemplateChapter.objects.filter(pk=chapter.pk).update(status=TemplateChapter.Status.PUBLISHED)
        task = TemplateTask.objects.get(chapter=chapter)
        TemplateTask.objects.filter(pk=task.pk).update(status=TemplateTask.Status.DRAFT)
        with self.assertRaises(PublicationValidationError) as task_error:
            precheck_template_version(template_version=self.template_version)
        self.assertEqual(
            task_error.exception.detail["chapter_tasks"][chapter.public_id]["not_published"],
            [task.public_id],
        )

    def test_precheck_merges_task_execution_override_and_rejects_invalid_spec(self) -> None:
        task = TemplateTask.objects.get(chapter__template_version=self.template_version)
        TemplateTask.objects.filter(pk=task.pk).update(
            execution_spec={"entrypoint": "task.py"}
        )
        content = precheck_template_version(template_version=self.template_version)
        normalized = content["chapters"][0]["tasks"][0]["execution_snapshot"]["execution_spec"]
        self.assertEqual(normalized["entrypoint"], "task.py")
        self.assertEqual(normalized["language"], self.template_version.execution_spec["language"])
        self.assertEqual(
            normalized["tests_asset"], self.template_version.execution_spec["tests_asset"]
        )

        TemplateTask.objects.filter(pk=task.pk).update(execution_spec={"entrypoint": "bad.txt"})
        with self.assertRaises(PublicationValidationError) as error:
            precheck_template_version(template_version=self.template_version)
        self.assertIn(task.public_id, error.exception.detail["execution_spec"])

    def test_template_digest_changes_when_runtime_adapter_config_changes(self) -> None:
        before = precheck_template_version(template_version=self.template_version)
        RuntimeAdapter.objects.filter(pk=self.template_version.runtime_adapter_id).update(
            config_ref="runtime/changed-config"
        )
        self.template_version.refresh_from_db()
        after = precheck_template_version(template_version=self.template_version)
        self.assertNotEqual(before["template_digest"], after["template_digest"])

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

    def test_precheck_rejects_missing_content_or_unready_image(self) -> None:
        version = TemplateVersion.objects.create(
            template=self.template_version.template,
            version_no=99,
            status=TemplateVersion.Status.PUBLISHED,
            runtime_type=self.template_version.runtime_type,
            runtime_adapter=self.template_version.runtime_adapter,
            image=self.template_version.image,
            resource_profile=self.template_version.resource_profile,
            execution_spec=self.template_version.execution_spec,
            spec_digest="d" * 64,
            created_by=self.owner,
            published_by=self.owner,
            published_at=timezone.now(),
        )
        image = self.template_version.image
        ExperimentImage.objects.create(
            template_version=version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry=image.registry,
            repository=image.repository,
            requested_tag=image.display_tag or "stable",
            resolved_digest=image.digest,
            image_asset=image,
            status=ExperimentImage.Status.READY,
            scan_status=ExperimentImage.ScanStatus.CLEAN,
            trace_id="publications-missing".ljust(32, "0"),
            created_by=self.owner,
        )
        with self.assertRaises(PublicationValidationError) as task_error:
            precheck_template_version(template_version=version)
        self.assertIn("chapters", task_error.exception.detail)

        chapter = TemplateChapter.objects.create(
            template_version=version,
            title="Missing task chapter",
            sort_order=1,
            status=TemplateChapter.Status.PUBLISHED,
            resource_profile=version.resource_profile,
        )
        with self.assertRaises(PublicationValidationError) as task_error:
            precheck_template_version(template_version=version)
        self.assertIn("chapter_tasks", task_error.exception.detail)

        TemplateTask.objects.create(
            chapter=chapter,
            title="Restored task",
            task_type="PRACTICE",
            sort_order=1,
            status=TemplateTask.Status.PUBLISHED,
            resource_profile=version.resource_profile,
        )
        ExperimentImage.objects.filter(template_version=version).update(
            status=ExperimentImage.Status.FAILED
        )
        with self.assertRaises(PublicationValidationError) as image_error:
            precheck_template_version(template_version=version)
        self.assertEqual(image_error.exception.detail["image"], "READY_REQUIRED")

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
        self.assertEqual(allowed_actions(task, actor=task.student), ["REQUEST_EXTENSION"])
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

    def test_allowed_actions_no_longer_offer_retired_workspace_entry(self) -> None:
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
            to_status=ExperimentTask.Status.READY,
            actor=None,
            expected_version=task.row_version,
            trigger="PROVISION",
            reason="workspace ready",
            context=context(self.owner, "WORKER"),
        )
        self.assertEqual(allowed_actions(task, actor=task.student), ["REQUEST_EXTENSION"])
        task = transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.IN_PROGRESS,
            actor=task.student,
            expected_version=task.row_version,
            trigger="ENTER_WORKSPACE",
            reason="entered workspace",
            context=context(task.student, "USER"),
        )
        self.assertEqual(allowed_actions(task, actor=task.student), ["REQUEST_EXTENSION"])
        ExperimentTask.objects.filter(pk=task.pk).update(
            status=ExperimentTask.Status.REPORT_DRAFT
        )
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

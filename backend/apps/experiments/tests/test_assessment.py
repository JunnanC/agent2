from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone

from apps.core.errors import ResourceNotFound, RowVersionConflict, StateConflict
from apps.labtemplates.models import TemplateTask

from ..assessment import assessment_data, read_draft, save_draft, submit_choices
from ..models import AssessmentSection, PublicationTask, QuestionGrade, SectionSubmission
from ..services import publish_publication
from .helpers import context, create_domain, create_draft_publication, create_enrollment


class AssessmentTests(TestCase):
    def setUp(self) -> None:
        self.owner, self.course, version, rubric = create_domain(suffix="assessment")
        self.enrollment = create_enrollment(self.course)
        self.student = self.enrollment.student
        self.public = {"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]}
        self.marking = {"correct_option_ids": ["b"], "explanation": "secret explanation"}
        TemplateTask.objects.filter(chapter__template_version=version).update(
            task_type="SINGLE_CHOICE", question_spec=self.public, marking_spec=self.marking,
            max_score=Decimal("5"),
        )
        from apps.labtemplates.models import TemplateVersion
        from apps.labtemplates.services import compute_spec_digest

        TemplateVersion.objects.filter(pk=version.pk).update(spec_digest=compute_spec_digest(version))
        version.refresh_from_db()
        publication = create_draft_publication(
            owner=self.owner, course=self.course, template_version=version, rubric_version=rubric,
        )
        with patch("apps.experiments.tasks.assign_publication_tasks.apply_async"):
            publication, _ = publish_publication(
                course_id=self.course.public_id, publication_id=publication.public_id,
                actor=self.owner, expected_version=publication.row_version,
                selected_ids=[], context=context(self.owner),
            )
        self.publication = publication
        self.task = publication.tasks.get(student=self.student)
        self.question = PublicationTask.objects.get(publication_chapter__publication=publication)

    def draft(self) -> dict[str, Any]:
        return read_draft(
            actor=self.student, task_id=self.task.public_id, question_id=self.question.public_id,
        )

    def save(self, answers: list[str], version: int) -> dict[str, Any]:
        return save_draft(
            actor=self.student, task_id=self.task.public_id, question_id=self.question.public_id,
            expected_version=version, data={"selected_option_ids": answers},
        )

    def submit(self, version: int) -> SectionSubmission:
        return submit_choices(
            actor=self.student, task_id=self.task.public_id,
            versions={self.question.public_id: version}, trace_id="a" * 32,
        )

    def test_frozen_content_and_no_answer_leak_before_deadline(self) -> None:
        data = assessment_data(actor=self.student, task_id=self.task.public_id)
        assert data["questions"][0]["options"] == self.public["options"]
        assert "secret explanation" not in str(data)
        assert "correct_option_ids" not in str(data)
        TemplateTask.objects.filter(public_id=self.question.source_task_id).update(
            marking_spec={"correct_option_ids": ["a"]},
        )
        self.question.refresh_from_db()
        assert self.question.marking_spec == self.marking

    def test_drafts_are_versioned_and_submission_is_immutable(self) -> None:
        draft = self.draft()
        updated = self.save(["b"], draft["row_version"])
        with self.assertRaises(RowVersionConflict):
            self.save(["a"], draft["row_version"])
        first = self.submit(updated["row_version"])
        assert first.answers.get().grade.score == Decimal("5")
        assert assessment_data(actor=self.student, task_id=self.task.public_id)["sections"][0][
            "score"
        ] is None
        updated = self.save([], updated["row_version"])
        second = self.submit(updated["row_version"])
        assert second.version_no == 2
        assert second.answers.get().grade.score == 0
        assert first.answers.get().selected_option_ids == ["b"]
        assert AssessmentSection.objects.get(task=self.task).current_submission == second

    def test_whole_section_rolls_back_on_incomplete_or_stale_versions(self) -> None:
        draft = self.draft()
        with self.assertRaises(StateConflict):
            submit_choices(
                actor=self.student, task_id=self.task.public_id, versions={}, trace_id="b",
            )
        self.save(["b"], draft["row_version"])
        with self.assertRaises(RowVersionConflict):
            self.submit(draft["row_version"])
        assert not SectionSubmission.objects.exists()
        assert not QuestionGrade.objects.exists()

    def test_deadline_reveals_answers_but_rejects_new_writes(self) -> None:
        draft = self.draft()
        now = self.publication.window_end + timezone.timedelta(seconds=1)
        with patch("apps.experiments.assessment.timezone.now", return_value=now):
            data = assessment_data(actor=self.student, task_id=self.task.public_id)
            assert data["questions"][0]["correct_option_ids"] == ["b"]
            assert data["sections"][0]["score"] == "0"
            with self.assertRaises(StateConflict):
                self.save(["b"], draft["row_version"])
            with self.assertRaises(StateConflict):
                self.submit(draft["row_version"])

    def test_other_student_cannot_read_draft(self) -> None:
        other = create_enrollment(self.course, suffix="other").student
        with self.assertRaises(ResourceNotFound):
            read_draft(
                actor=other, task_id=self.task.public_id, question_id=self.question.public_id,
            )

    def test_revoked_enrollment_cannot_read_answers(self) -> None:
        type(self.enrollment).objects.filter(pk=self.enrollment.pk).update(status="REMOVED")
        with self.assertRaises(ResourceNotFound):
            self.draft()

    def test_multiselect_is_exact_set_and_empty_answers_score_zero(self) -> None:
        # Published rows are append-only; create a separate multi-select snapshot.
        question = PublicationTask.objects.create(
            publication_chapter=self.question.publication_chapter, source_task_id="B" * 26,
            title="Multiple", task_type="MULTIPLE_CHOICE", sort_order=2, image_digest="",
            question_spec=self.public,
            marking_spec={"correct_option_ids": ["a", "b"]}, max_score=3,
        )
        one = self.draft()
        two = read_draft(
            actor=self.student, task_id=self.task.public_id, question_id=question.public_id,
        )
        saved = save_draft(
            actor=self.student, task_id=self.task.public_id, question_id=question.public_id,
            expected_version=two["row_version"], data={"selected_option_ids": ["a"]},
        )
        versions = {
            self.question.public_id: one["row_version"], question.public_id: saved["row_version"],
        }
        submission = submit_choices(
            actor=self.student, task_id=self.task.public_id, versions=versions, trace_id="a" * 32,
        )
        assert all(answer.grade.score == 0 for answer in submission.answers.all())
        saved = save_draft(
            actor=self.student, task_id=self.task.public_id, question_id=question.public_id,
            expected_version=saved["row_version"], data={"selected_option_ids": ["b", "a"]},
        )
        versions[question.public_id] = saved["row_version"]
        submission = submit_choices(
            actor=self.student, task_id=self.task.public_id, versions=versions, trace_id="a" * 32,
        )
        assert submission.answers.get(question=question).grade.score == Decimal("3")

    def test_multilanguage_code_drafts_are_independent_and_container_free(self) -> None:
        question = PublicationTask.objects.create(
            publication_chapter=self.question.publication_chapter, source_task_id="C" * 26,
            title="Code", task_type="PROGRAMMING", sort_order=2, image_digest="",
            question_spec={
                "allowed_languages": ["python", "cpp"], "samples": [], "limits": {},
                "starter_files": {"python": {"main.py": ""}, "cpp": {"main.cpp": ""}},
            },
        )
        for language, files in (("python", {"main.py": "print(1)"}), ("cpp", {"main.cpp": ""})):
            draft = read_draft(
                actor=self.student, task_id=self.task.public_id, question_id=question.public_id,
                language=language,
            )
            save_draft(
                actor=self.student, task_id=self.task.public_id, question_id=question.public_id,
                expected_version=draft["row_version"], language=language, data={"files": files},
            )
        draft = read_draft(
            actor=self.student, task_id=self.task.public_id, question_id=question.public_id,
            language="python",
        )
        assert draft["files"] == {"main.py": "print(1)"}
        assert not hasattr(self.task, "workspace_sessions")
        data = assessment_data(actor=self.student, task_id=self.task.public_id)
        assert data["questions"][1]["selected_language"] == "cpp"

    def test_api_csrf_versions_and_idempotent_submission(self) -> None:
        client = Client(enforce_csrf_checks=True)
        headers = {
            "HTTP_X_PORTAL": "USER", "HTTP_X_PROXY_CONTEXT": "ingress-v1",
            "REMOTE_ADDR": "127.0.0.1",
        }
        response = client.get(f"/api/v2/tasks/{self.task.public_id}/assessment", **headers)
        assert response.status_code == 401
        client.get("/api/v2/auth/csrf", **headers)
        csrf = client.cookies["csrftoken"].value
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            response = client.post(
                "/api/v2/auth/login",
                {"identifier": self.student.email, "password": "ValidPassword!234"},
                content_type="application/json", HTTP_X_CSRFTOKEN=csrf, **headers,
            )
        assert response.status_code == 200, response.content
        headers["HTTP_X_CSRFTOKEN"] = client.cookies["csrftoken"].value
        endpoint = f"/api/v2/tasks/{self.task.public_id}/questions/{self.question.public_id}/draft"
        draft = client.get(endpoint, **headers)
        payload = {"selected_option_ids": ["b"]}
        response = client.put(endpoint, payload, content_type="application/json", **headers)
        assert response.status_code == 428
        response = client.put(
            endpoint, payload, content_type="application/json", HTTP_IF_MATCH=draft["ETag"],
            **headers,
        )
        assert response.status_code == 200, response.content
        version = response.json()["data"]["row_version"]
        endpoint = f"/api/v2/tasks/{self.task.public_id}/sections/choice/submissions"
        for _ in range(2):
            response = client.post(
                endpoint, {"versions": {self.question.public_id: version}},
                content_type="application/json", HTTP_IDEMPOTENCY_KEY="choice-submit-1", **headers,
            )
            assert response.status_code == 201, response.content
        assert response["X-Idempotent-Replayed"] == "true"
        assert SectionSubmission.objects.count() == 1

    def test_code_serializer_preserves_whitespace_and_empty_files(self) -> None:
        from ..assessment_views import DraftWriteSerializer

        files = {"main.py": "  print(1)  \n\n", "empty.txt": ""}
        serializer = DraftWriteSerializer(data={"files": files})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["files"] == files

    def test_drafts_are_not_accessible_before_opening(self) -> None:
        before_open = self.publication.window_start - timezone.timedelta(seconds=1)
        with patch("apps.experiments.assessment.timezone.now", return_value=before_open):
            with self.assertRaises(StateConflict):
                self.draft()
            with self.assertRaises(StateConflict):
                assessment_data(actor=self.student, task_id=self.task.public_id)

    def test_choice_only_template_prechecks_and_publishes_without_runtime_or_rubric(self) -> None:
        from apps.labtemplates.models import TemplateChapter
        from apps.labtemplates.serializers import version_data
        from apps.labtemplates.services import (
            create_task,
            create_version,
            execute_precheck,
            publish_version,
            request_precheck,
        )

        from ..services import create_publication

        template = self.publication.template_version.template
        version = create_version(
            course_id=self.course.public_id, template_id=template.public_id,
            actor=self.owner, data={}, context=context(self.owner),
        )
        chapter = TemplateChapter.objects.create(
            template_version=version, title="Choices", sort_order=1,
        )
        create_task(
            course_id=self.course.public_id, chapter_id=chapter.public_id,
            actor=self.owner, expected_version=version.row_version,
            data={
                "title": "Choice", "task_type": "SINGLE_CHOICE",
                "question_spec": self.public, "marking_spec": self.marking, "max_score": "5",
            }, context=context(self.owner),
        )
        version.refresh_from_db()
        run = request_precheck(
            course_id=self.course.public_id, version_id=version.public_id,
            actor=self.owner, expected_version=version.row_version, context=context(self.owner),
        )
        with patch("apps.core.tasks.relay_outbox.apply_async"):
            run = execute_precheck(run_id=run.public_id)
        assert run.status == "PASSED", run.error_detail_masked
        version.refresh_from_db()
        publish_version(
            course_id=self.course.public_id, version_id=version.public_id,
            actor=self.owner, expected_version=version.row_version, context=context(self.owner),
        )
        version.refresh_from_db()
        assert version_data(version)["runtime_adapter_id"] is None
        publication = create_publication(
            course_id=self.course.public_id, actor=self.owner,
            data={
                "template_version_id": version.public_id, "title": "Choices only",
                "audience_mode": "ALL_ACTIVE", "window_start": self.publication.window_start,
                "window_end": self.publication.window_end, "report_required": False,
                "review_mode": "MANUAL",
            }, context=context(self.owner),
        )
        publication, _ = publish_publication(
            course_id=self.course.public_id, publication_id=publication.public_id,
            actor=self.owner, expected_version=publication.row_version,
            selected_ids=[], context=context(self.owner),
        )
        task = publication.tasks.get(student=self.student)
        assert task.runtime_adapter_id is None
        assert task.image_id is None
        assert not hasattr(task, "workspace_sessions")
        assert assessment_data(actor=self.student, task_id=task.public_id)["questions"][0][
            "task_type"
        ] == "SINGLE_CHOICE"

    def test_programming_submission_freezes_all_sources_and_one_report(self) -> None:
        from apps.core.tests.storage import InMemoryObjectStorage
        from apps.reports.models import ReportVersion

        from ..assessment import report_draft, submit_programming

        question = PublicationTask.objects.create(
            publication_chapter=self.question.publication_chapter, source_task_id="D" * 26,
            title="Code", task_type="PROGRAMMING", sort_order=2, image_digest="",
            question_spec={
                "allowed_languages": ["python"], "starter_files": {"python": {"main.py": ""}},
                "samples": [], "limits": {},
            }, max_score=10,
        )
        draft = read_draft(
            actor=self.student, task_id=self.task.public_id,
            question_id=question.public_id, language="python",
        )
        saved = save_draft(
            actor=self.student, task_id=self.task.public_id, question_id=question.public_id,
            language="python", expected_version=draft["row_version"],
            data={"files": {"main.py": "print(input())\n", "helper.py": ""}},
        )
        report = report_draft(actor=self.student, task_id=self.task.public_id)
        with self.assertRaises(StateConflict):
            submit_programming(
                actor=self.student, task_id=self.task.public_id,
                versions={question.public_id: {"language": "python", "row_version": 2}},
                report_version=report["row_version"], trace_id="c" * 32,
            )
        report = report_draft(
            actor=self.student, task_id=self.task.public_id,
            expected_version=report["row_version"], body_markdown="My report\n",
        )
        with (
            patch(
                "apps.workspaces.code_snapshots.object_storage",
                return_value=InMemoryObjectStorage(),
            ),
            patch("apps.workspaces.code_snapshots.ClamAVScanner") as scanner,
        ):
            scanner.return_value.scan.return_value = SimpleNamespace(clean=True)
            submission = submit_programming(
                actor=self.student, task_id=self.task.public_id,
                versions={question.public_id: {
                    "language": "python", "row_version": saved["row_version"],
                }}, report_version=report["row_version"], trace_id="c" * 32,
            )
        answer = submission.answers.get()
        assert answer.code_snapshot.question_id == question.pk
        assert not hasattr(answer.code_snapshot, "session_id")
        assert answer.grade.status == "PENDING"
        assert answer.grade.score is None
        assert submission.report_version.body_markdown == "My report\n"
        assert not hasattr(submission.report_version, "workspace_snapshot_id")
        report_draft(
            actor=self.student, task_id=self.task.public_id,
            expected_version=report["row_version"], body_markdown="New draft",
        )
        fixed = ReportVersion.objects.get(pk=submission.report_version_id)
        assert fixed.body_markdown == "My report\n"
        from ..assessment import review_programming, section_result
        from ..models import AssessmentSection, QuestionGrade

        QuestionGrade.objects.filter(answer=answer).update(status="COMPLETED", score=10)
        section = AssessmentSection.objects.get(task=self.task, kind="PROGRAMMING")
        reviewed = review_programming(
            actor=self.owner, course_id=self.course.public_id, task_id=self.task.public_id,
            submission_version=1, expected_version=section.row_version,
            scores={}, feedback="Reviewed", trace_id="d" * 32,
        )
        assert reviewed["score"] == "10.00"
        section.refresh_from_db()
        hidden = section_result(section, student=True)
        assert hidden["score"] is None
        assert hidden["questions"] == []
        assert "Reviewed" not in str(hidden)
        with patch("apps.experiments.assessment.timezone.now", return_value=(
            self.publication.window_end + timezone.timedelta(seconds=1)
        )):
            visible = section_result(section, student=True)
            assert visible["score"] == "10.00"
            assert "private_result" not in str(visible)
        review_programming(
            actor=self.owner, course_id=self.course.public_id, task_id=self.task.public_id,
            submission_version=1, expected_version=section.row_version, scores={},
            feedback="Revise", return_until=timezone.now() + timezone.timedelta(days=3),
            trace_id="e" * 32,
        )
        section.refresh_from_db()
        assert section.status == "RETURNED"
        assert section_result(section, student=False)["score"] is None
        with self.assertRaises(StateConflict):
            review_programming(
                actor=self.owner, course_id=self.course.public_id, task_id=self.task.public_id,
                submission_version=1, expected_version=section.row_version, scores={},
                feedback="", trace_id="f" * 32,
            )

    def test_choice_review_exposes_selected_and_correct_options(self) -> None:
        from ..assessment import choice_review_data

        draft = self.draft()
        updated = self.save(["b"], draft["row_version"])
        self.submit(updated["row_version"])
        section = AssessmentSection.objects.get(task=self.task, kind="CHOICE")
        rows = choice_review_data(section)
        assert len(rows) == 1
        assert rows[0]["selected_option_ids"] == ["b"]
        assert rows[0]["correct_option_ids"] == ["b"]
        assert rows[0]["options"] == self.public["options"]
        assert Decimal(rows[0]["score"]) == Decimal("5")

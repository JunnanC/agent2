from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.courses.models import CourseCopyJob
from apps.courses.tests.helpers import create_draft_course
from apps.governance.models import QuotaReservation
from apps.labtemplates.models import TemplateTask
from apps.labtemplates.services import copy_templates


class AssessmentAcceptanceTests(TestCase):
    def setUp(self) -> None:
        from .test_assessment import AssessmentTests

        AssessmentTests.setUp(self)

    def test_course_copy_preserves_active_questions_and_reowns_hidden_tests(self) -> None:
        from .helpers import context

        source_version = self.publication.template_version
        chapter = source_version.chapters.get()
        TemplateTask.objects.create(
            chapter=chapter, title="program", task_type="PROGRAMMING", sort_order=2,
            max_score=10, question_spec={"allowed_languages": ["python"]},
            marking_spec={"tests_asset_id": "original"},
        )
        TemplateTask.objects.create(
            chapter=chapter, title="deleted", task_type="SINGLE_CHOICE", sort_order=3, active=False,
        )
        target = create_draft_course(self.owner, code="ASSESSMENT-COPY")
        job = CourseCopyJob.objects.create(source_course=self.course, created_by=self.owner)
        with patch("apps.labtemplates.assessment_assets.clone_marking_spec") as clone:
            clone.side_effect = lambda question, version: (
                {"tests_asset_id": "copied"} if question.task_type == "PROGRAMMING"
                else dict(question.marking_spec)
            )
            copy_templates(job, self.course, target, self.owner, context(self.owner))
        version = target.lab_templates.get().versions.get()
        questions = list(version.chapters.get().tasks.order_by("sort_order"))
        assert [q.title for q in questions] == ["First task", "program"]
        assert all(q.status == "DRAFT" for q in questions)
        assert questions[0].question_spec == self.public
        assert questions[1].marking_spec["tests_asset_id"] == "copied"
        assert clone.call_args_list[1].args[1] == version
        assert source_version.chapters.get().tasks.get(title="program").marking_spec == {
            "tests_asset_id": "original",
        }

    def test_expired_admission_releases_even_if_docker_resources_already_disappeared(self) -> None:
        from ..assessment_workers import cleanup_assessment_resources

        expired = QuotaReservation.objects.create(
            reservation_key="expired-assessment", reservation_type="STANDARD",
            subject_type="ASSESSMENT", subject_ref=self.task.public_id,
            reserved_at=timezone.now() - timezone.timedelta(hours=2),
            expires_at=timezone.now() - timezone.timedelta(minutes=1), trace_id="test",
        )
        QuotaReservation.objects.create(
            reservation_key="active-assessment", reservation_type="STANDARD",
            subject_type="ASSESSMENT", subject_ref="another-task",
            reserved_at=timezone.now(), expires_at=timezone.now() + timezone.timedelta(hours=1),
            trace_id="test",
        )
        from apps.provisioning.models import RuntimeCapacityReservation

        already_expired = QuotaReservation.objects.create(
            reservation_key="expired-capacity", reservation_type="STANDARD", status="EXPIRED",
            subject_type="ASSESSMENT", subject_ref="expired-capacity-task",
            reserved_at=timezone.now() - timezone.timedelta(hours=2),
            expires_at=timezone.now() - timezone.timedelta(minutes=1), trace_id="test",
        )
        RuntimeCapacityReservation.objects.create(
            reservation=already_expired,
            runtime_adapter=self.publication.template_version.runtime_adapter,
            cpu_millicores=1000, memory_mb=1024,
        )
        with (
            patch("apps.experiments.assessment_workers.docker.DockerClient") as docker,
            patch("apps.experiments.assessment_workers._release") as release,
        ):
            docker.return_value.containers.list.return_value = []
            docker.return_value.volumes.list.return_value = []
            assert cleanup_assessment_resources() == 0
            assert {call.args[0].pk for call in release.call_args_list} == {
                expired.pk, already_expired.pk,
            }

    def test_late_grade_cannot_reopen_a_cancelled_or_archived_task(self) -> None:
        from ..assessment import sync_assessment_status
        from ..models import ExperimentTask

        for status in ("ARCHIVING", "COMPLETED", "CANCELLED", "EXPIRED"):
            ExperimentTask.objects.filter(pk=self.task.pk).update(status=status)
            self.task.refresh_from_db()
            sync_assessment_status(self.task)
            self.task.refresh_from_db()
            assert self.task.status == status

    def test_storage_failure_cannot_create_partial_programming_submission(self) -> None:
        from ..assessment import read_draft, submit_programming
        from ..models import AssessmentSection, PublicationTask, SectionSubmission

        question = PublicationTask.objects.create(
            publication_chapter=self.question.publication_chapter, source_task_id="D" * 26,
            title="Code", task_type="PROGRAMMING", sort_order=2, image_digest="",
            question_spec={"allowed_languages": ["python"],
                           "starter_files": {"python": {"main.py": "print(1)"}}},
        )
        draft = read_draft(
            actor=self.student, task_id=self.task.public_id,
            question_id=question.public_id, language="python",
        )
        type(self.publication).objects.filter(pk=self.publication.pk).update(report_required=False)
        with (
            patch(
                "apps.workspaces.code_snapshots.create_code_snapshot",
                side_effect=OSError("offline"),
            ),
            self.assertRaises(OSError),
        ):
            submit_programming(
                actor=self.student, task_id=self.task.public_id,
                versions={question.public_id: {"language": "python", "row_version": 1}},
                report_version=None, trace_id="test",
            )
        assert not AssessmentSection.objects.filter(task=self.task, kind="PROGRAMMING").exists()
        assert not SectionSubmission.objects.filter(section__task=self.task).exists()
        assert draft["files"] == {"main.py": "print(1)"}

    def test_ai_suggestion_reads_report_only_and_never_writes_a_grade(self) -> None:
        from rest_framework.test import APIRequestFactory, force_authenticate

        from apps.agents.rubric_agent import RubricAssessment
        from apps.core.concurrency import compare_and_swap
        from apps.reports.models import ReportDraft, ReportVersion
        from apps.reviews.models import RubricCriterion

        from ..assessment_review_views import AssessmentReportSuggestionView
        from ..models import AssessmentSection, QuestionGrade, ReportGrade, SectionSubmission

        criterion = RubricCriterion.objects.create(
            rubric_version=self.publication.rubric_version, title="Report", position=1,
            position_key="report", max_score=100, weight_basis_points=10000,
        )
        draft = ReportDraft.objects.create(task=self.task, student=self.student)
        report = ReportVersion.objects.create(
            task=self.task, draft=draft, student=self.student, version_no=1,
            body_markdown="immutable report", body_digest="a" * 64, snapshot_digest="b" * 64,
            submitted_by=self.student, submitted_at=timezone.now(), trace_id="test",
        )
        section = AssessmentSection.objects.create(task=self.task, kind="PROGRAMMING")
        submission = SectionSubmission.objects.create(
            section=section, version_no=1, report_version=report, publication_digest="c" * 64,
            submitted_at=timezone.now(), trace_id="test",
        )
        compare_and_swap(
            AssessmentSection, pk=section.pk, expected_version=1,
            changes={"current_submission": submission, "status": "SUBMITTED"},
        )
        ReportGrade.objects.create(submission=submission)
        request = APIRequestFactory().post(
            "/report-suggestion", {"submission_version": 1}, format="json",
        )
        request.portal, request.idempotency_key = "TEACHING", "ai-request"
        force_authenticate(request, user=self.owner)
        answer = RubricAssessment.model_validate({"criteria": [{
            "criterion_id": criterion.public_id, "score": "9",
            "rationale": "reason", "evidence": "report",
        }]})
        with patch("apps.agents.rubric_agent.assess_submission", return_value=answer) as model:
            response = AssessmentReportSuggestionView.as_view()(
                request, course_id=self.course.public_id, task_id=self.task.public_id,
            )
        assert response.status_code == 200, response.data
        assert model.call_args.kwargs["report"] == "immutable report"
        assert set(model.call_args.kwargs) == {"report", "rubric"}
        assert ReportGrade.objects.get(submission=submission).score is None
        assert not QuestionGrade.objects.exists()

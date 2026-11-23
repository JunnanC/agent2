from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zipfile import ZipFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import timezone

from apps.agents.lab_agent import WordReview
from apps.core.models import ObjectAsset
from apps.experiments.grades import task_grades
from apps.experiments.models import TaskPublication, TeachingEnvironment
from apps.governance.models import RuntimeAdapter
from apps.reports.assessment_review import review_word_report
from apps.reports.models import ReportSubmission
from apps.reports.word_review import WORD, document_paragraphs

from .helpers import create_domain, create_enrollment


def word_file() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/></Types>'
            ),
        )
        archive.writestr(
            "word/document.xml",
            (
                f'<w:document xmlns:w="{WORD}"><w:body><w:p><w:r><w:rPr>'
                '<w:sz w:val="20"/></w:rPr><w:t>Report evidence</w:t></w:r></w:p>'
                "<w:sectPr/></w:body></w:document>"
            ),
        )
    return output.getvalue()


class TestDirectExperiment(TestCase):
    def _login(self, portal: str, email: str) -> tuple[Client, dict[str, str]]:
        from .test_workspace_assessment import WorkspaceAssessmentTests

        return WorkspaceAssessmentTests._login(self, portal, email)

    def setUp(self) -> None:
        self.owner, self.course, self.version, _rubric = create_domain(suffix="direct-experiment")
        self.enrollment = create_enrollment(self.course)
        self.student = self.enrollment.student
        type(self.enrollment).objects.filter(pk=self.enrollment.pk).update(
            activated_at=timezone.now() - timedelta(minutes=10),
        )
        self.teacher, self.teacher_headers = self._login("TEACHING", self.owner.email)
        self.student_client, self.student_headers = self._login("USER", self.student.email)
        self.course_url = f"/api/v2/teaching/courses/{self.course.public_id}"

    def make_publication(self, *, program: bool = False) -> TaskPublication:
        now = timezone.now()
        env_id = ""
        if program:
            adapter = RuntimeAdapter.objects.create(
                code="direct-local",
                name="Local Docker",
                runtime_type="CONTAINER",
                driver="DOCKER_LOCAL",
                status="ENABLED",
                config_ref="local",
                capacity_cpu_millicores=4000,
                capacity_memory_mb=4096,
            )
            response = self.teacher.post(
                self.course_url + "/lab-environments",
                {
                    "name": "Python",
                    "language": "python",
                    "image_id": self.version.image.public_id,
                    "runtime_adapter_id": adapter.public_id,
                    "memory_mb": 768,
                    "cpu_millicores": 650,
                },
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="create-environment",
                **self.teacher_headers,
            )
            assert response.status_code == 201, response.content
            env_id = response.json()["data"]["public_id"]

        question = (
            {
                "task_type": "PROGRAMMING",
                "title": "Echo",
                "starter_code": "print(input())",
                "samples": [{"input": "open", "output": "open"}],
                "hidden_cases": [{"input": "private fixture", "output": "private fixture"}],
            }
            if program
            else {
                "task_type": "SINGLE_CHOICE",
                "title": "Select A",
                "explanation": "Release explanation",
                "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                "correct_option_ids": ["a"],
            }
        )
        response = self.teacher.post(
            self.course_url + "/experiment-designs",
            {
                "title": "Direct experiment",
                "guidance": "Read the instructions",
                "report_requirements": "" if program else "Use 12 pt body text",
                "environment_id": env_id,
                "window_start": (now - timedelta(minutes=5)).isoformat(),
                "window_end": (now + timedelta(hours=1)).isoformat(),
                "questions": [question],
                "part_maxima": {
                    "CHOICE": "0" if program else "30",
                    "PROGRAMMING": "75" if program else "0",
                    "REPORT": "0" if program else "70",
                },
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="create-direct",
            **self.teacher_headers,
        )
        assert response.status_code == 201, response.content
        draft = response.json()["data"]
        response = self.teacher.post(
            self.course_url + f"/experiments/{draft['public_id']}/publish",
            {"selected_enrollment_ids": []},
            content_type="application/json",
            HTTP_IF_MATCH=f'"{draft["row_version"]}"',
            HTTP_IDEMPOTENCY_KEY="publish-direct",
            **self.teacher_headers,
        )
        assert response.status_code == 201, response.content
        return TaskPublication.objects.get(public_id=draft["public_id"])

    def test_runtime_configuration_is_frozen_and_hidden_examples_are_not_in_student_data(
        self,
    ) -> None:
        publication = self.make_publication(program=True)
        task = publication.tasks.get()
        environment = TeachingEnvironment.objects.get(pk=publication.environment_id)
        TeachingEnvironment.objects.filter(pk=environment.pk).update(cpu_millicores=1300)
        assert task.resource_profile_snapshot["cpu_millicores"] == 650
        assert task.resource_profile_snapshot["memory_mb"] == 768
        data = self.student_client.get(
            f"/api/v2/tasks/{task.public_id}/assessment",
            **self.student_headers,
        )
        assert data.status_code == 200
        assert b"private fixture" not in data.content
        assert data.json()["data"]["questions"][0]["samples"] == [
            {"input": "open", "output": "open"}
        ]

    def test_word_review_release_and_read_only_scores(self) -> None:
        publication = self.make_publication()
        task = publication.tasks.get()
        path = f"/api/v2/tasks/{task.public_id}"
        teaching = self.course_url + f"/experiments/{publication.public_id}"
        grade_release = teaching + "/grade-release"
        client, headers = self.student_client, self.student_headers
        response = client.post(
            path + "/workspace",
            {},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="enter-direct",
            **headers,
        )
        assert response.status_code == 200, response.content
        invalid = client.post(
            path + "/report",
            {"file": SimpleUploadedFile("report.txt", b"txt")},
            HTTP_IDEMPOTENCY_KEY="not-word",
            **headers,
        )
        assert invalid.status_code == 409, invalid.content
        content = word_file()
        store = Mock()
        store.put_stream.return_value = SimpleNamespace(version_id="version")
        with (
            patch("apps.reports.assessment_reports.object_storage", return_value=store),
            patch("apps.reports.assessment_reports.ClamAVScanner") as scan,
        ):
            scan.return_value.scan.return_value.clean = True
            response = client.post(
                path + "/report",
                {"file": SimpleUploadedFile("report.docx", content)},
                HTTP_IDEMPOTENCY_KEY="upload-word",
                **headers,
            )
        assert response.status_code == 200, response.content
        assert document_paragraphs(content) == [
            {"paragraph": 1, "text": "Report evidence", "sizes_pt": ["10"]},
        ]
        assert (
            self.teacher.post(
                grade_release,
                {},
                HTTP_IDEMPOTENCY_KEY="too-early",
                **self.teacher_headers,
            ).status_code
            == 409
        )

        response = self.teacher.post(
            teaching + "/word-reviews",
            {},
            HTTP_IDEMPOTENCY_KEY="batch-word",
            **self.teacher_headers,
        )
        assert response.status_code == 202, response.content
        report = ReportSubmission.objects.get(task=task)
        assert report.review_status == "QUEUED"
        with (
            patch("apps.reports.assessment_review.asset_bytes", return_value=content),
            patch(
                "apps.reports.assessment_review.structured_lab_response",
                side_effect=ValueError("AI unavailable"),
            ),
        ):
            review_word_report(report.pk, report.asset_id, report.row_version)
        report.refresh_from_db()
        assert report.review_status == "FAILED"
        before_deadline = timezone.now() - timedelta(seconds=1)
        TaskPublication.objects.filter(pk=publication.pk).update(window_end=before_deadline)
        blocked = self.teacher.post(
            grade_release,
            {},
            HTTP_IDEMPOTENCY_KEY="blocked",
            **self.teacher_headers,
        )
        assert blocked.status_code == 409, blocked.content

        response = self.teacher.post(
            teaching + "/word-reviews",
            {},
            HTTP_IDEMPOTENCY_KEY="retry-word",
            **self.teacher_headers,
        )
        assert response.status_code == 202, response.content
        report.refresh_from_db()
        suggestion = WordReview.model_validate({
            "score": "65",
            "feedback": "Check the font",
            "comments": [{"paragraph": 1, "text": "Use 12 pt"}],
        })
        with (
            patch("apps.reports.assessment_review.asset_bytes", return_value=content),
            patch(
                "apps.reports.assessment_review.structured_lab_response", return_value=suggestion
            ),
        ):
            review_word_report(report.pk, report.asset_id, report.row_version)
        report.refresh_from_db()
        assert report.review_status == "READY"
        hidden = client.get(path + "/report", **headers)
        assert b"Check the font" not in hidden.content
        assert hidden.json()["data"]["score"] is None
        assert client.get(path + "/published-grade", **headers).status_code == 404

        released_at = None
        for key in ("publish-grades", "publish-grades-again"):
            response = self.teacher.post(
                grade_release,
                {},
                HTTP_IDEMPOTENCY_KEY=key,
                **self.teacher_headers,
            )
            assert response.status_code == 200, response.content
            value = response.json()["data"]["grades_published_at"]
            assert value and (released_at is None or released_at == value)
            released_at = value
        grade = client.get(path + "/published-grade", **headers).json()["data"]
        assert grade["max_score"] == "100.00"
        assert grade["score"] == "65.00"
        assert grade["parts"][0]["status"] == "NOT_SUBMITTED"
        assert b"Release explanation" in client.get(path + "/assessment", **headers).content
        assert b"Check the font" in client.get(path + "/report", **headers).content

        with patch("apps.reports.assessment_views.asset_bytes", return_value=content):
            response = client.get(path + "/report/reviewed", **headers)
            assert response.status_code == 200, response.content if not response.streaming else ""
            with ZipFile(BytesIO(b"".join(response.streaming_content))) as archive:
                assert b"Use 12 pt" in archive.read("word/comments.xml")
                document = archive.read("word/document.xml").decode()
                assert "commentRangeStart" in document and "65.00" in document
                assert (
                    document.index("分数") < document.index("总评语") < document.index("教师签名")
                )

        edit = client.post(
            path + "/report",
            {"file": SimpleUploadedFile("redo.docx", content)},
            HTTP_IDEMPOTENCY_KEY="locked-upload",
            **headers,
        )
        assert edit.status_code == 409, edit.content
        create_enrollment(self.course, suffix="late")
        grades = self.teacher.get(teaching + "/published-grades", **self.teacher_headers).json()[
            "data"
        ]
        assert [row["should_do"] for row in grades["rows"]] == [True, False]

    def test_manual_review_after_ai_failure_and_choice_representation(self) -> None:
        publication = self.make_publication()
        task = publication.tasks.get()
        question = publication.chapter_snapshots.get().task_snapshots.get()
        path = f"/api/v2/tasks/{task.public_id}"
        client, headers = self.student_client, self.student_headers
        response = client.post(
            path + "/workspace", {}, content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="open-manual-workspace", **headers,
        )
        assert response.status_code == 200, response.content
        draft_path = path + f"/questions/{question.public_id}/draft"
        draft = client.get(draft_path, **headers).json()["data"]
        saved = client.put(
            draft_path, {"selected_option_ids": ["a"]}, content_type="application/json",
            HTTP_IF_MATCH=f'"{draft["row_version"]}"', **headers,
        )
        assert saved.status_code == 200, saved.content
        receipt = client.post(
            path + "/sections/choice/submissions",
            {"versions": {question.public_id: saved.json()["data"]["row_version"]}},
            content_type="application/json", HTTP_IDEMPOTENCY_KEY="choice-direct", **headers,
        )
        assert receipt.status_code == 201, receipt.content
        assert receipt.json()["data"]["part"]["score"] is None
        assert task_grades([task], student=True)[task.pk]["parts"][0]["score"] is None

        content = word_file()
        asset = ObjectAsset.objects.create(
            bucket="test", object_key="manual-report", owner_type="ASSESSMENT_REPORT",
            owner_ref=task.public_id, purpose="ASSESSMENT_REPORT", original_name="manual.docx",
            digest_sha256="a" * 64, size_bytes=len(content), scan_status="CLEAN",
        )
        report = ReportSubmission.objects.create(
            task=task, asset=asset, submitted_at=timezone.now(), review_status="FAILED",
        )
        with patch("apps.reports.assessment_reports.asset_bytes", return_value=content):
            response = self.teacher.post(
                self.course_url + f"/tasks/{task.public_id}/report",
                {"score": "48", "feedback": "Reviewed by teacher",
                 "comments": [{"paragraph": 1, "text": "Check the format"}]},
                content_type="application/json", HTTP_IF_MATCH=f'"{report.row_version}"',
                HTTP_IDEMPOTENCY_KEY="manual-report-grade", **self.teacher_headers,
            )
        assert response.status_code == 200, response.content
        assert response.json()["data"]["score"] == "48.00"
        assert client.get(path + "/report", **headers).json()["data"]["feedback"] == ""

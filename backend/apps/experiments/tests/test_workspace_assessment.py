from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import timezone

from apps.core.models import ObjectAsset
from apps.provisioning.stdio import StdioResult
from apps.reports.models import ReportSubmission
from apps.workspaces.models import StudentWorkspace, WorkspaceSnapshot
from apps.workspaces.tasks import sync_student_workspace

from ..assessment_workers import execute_assessment_job
from ..models import ProgrammingSubmission, PublicationTask


class WorkspaceAssessmentTests(TestCase):
    def setUp(self) -> None:
        from .test_assessment import AssessmentTests

        AssessmentTests.setUp(self)
        self.path = f"/api/v2/tasks/{self.task.public_id}"
        self.teaching_path = (
            f"/api/v2/teaching/courses/{self.course.public_id}/tasks/{self.task.public_id}"
        )
        self.student_client, self.student_headers = self._login("USER", self.student.email)

    def _login(self, portal: str, email: str) -> tuple[Client, dict[str, str]]:
        client = Client(enforce_csrf_checks=True)
        headers = {
            "HTTP_X_PORTAL": portal,
            "HTTP_X_PROXY_CONTEXT": "ingress-v1",
            "REMOTE_ADDR": "127.0.0.1",
        }
        client.get("/api/v2/auth/csrf", **headers)
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            response = client.post(
                "/api/v2/auth/login",
                {"identifier": email, "password": "ValidPassword!234"},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
                **headers,
            )
        assert response.status_code == 200, response.content
        headers["HTTP_X_CSRFTOKEN"] = client.cookies["csrftoken"].value
        return client, headers

    def _post(self, suffix: str, data: dict[str, Any], key: str, code: int = 200) -> Any:
        response = self.student_client.post(
            self.path + suffix,
            data,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
            **self.student_headers,
        )
        assert response.status_code == code, response.content
        return response.json().get("data")

    def _program(self, order: int) -> PublicationTask:
        return PublicationTask.objects.create(
            publication_chapter=self.question.publication_chapter,
            sort_order=order,
            source_task_id=str(order).zfill(26),
            task_type="PROGRAMMING",
            title=f"Program {order}",
            max_score=20,
            question_spec={
                "allowed_languages": ["python"],
                "samples": [{"input": str(i), "output": str(i)} for i in range(3)],
                "starter_files": {"python": {"main.py": "print(input())"}},
                "limits": {"python": {"timeout_seconds": 3, "memory_mb": 512}},
            },
            execution_snapshot={"case_count": 5},
        )

    def _snapshot(self, *, task: Any, question: Any, draft: Any) -> WorkspaceSnapshot:
        number = WorkspaceSnapshot.objects.count() + 1
        asset = ObjectAsset.objects.create(
            bucket="test",
            object_key=f"source-{number}",
            digest_sha256="a" * 64,
            size_bytes=1,
            owner_type="WORKSPACE_TASK",
            owner_ref=task.public_id,
            purpose="SOURCE_SNAPSHOT",
            scan_status="CLEAN",
        )
        return WorkspaceSnapshot.objects.create(
            task=task,
            question=question,
            asset=asset,
            version_no=number,
            client_seq=number,
            digest_sha256=asset.digest_sha256,
            saved_at=timezone.now(),
            language=draft.language,
        )

    def _attempt(self, question: PublicationTask, mode: str, input_text: str, key: str) -> Any:
        path = f"/questions/{question.public_id}"
        draft = self.student_client.get(self.path + path + "/code/python", **self.student_headers)
        assert draft.status_code == 200, draft.content
        run = self._post(
            path + f"/{mode}",
            {
                "language": "python",
                "row_version": draft.json()["data"]["row_version"],
                "stdin": input_text,
            },
            key,
            201,
        )
        execute_assessment_job(pk=run["id"], formal=False)
        response = self.student_client.get(
            self.path + path + f"/attempts/{run['id']}",
            **self.student_headers,
        )
        assert response.status_code == 200, response.content
        return response.json()["data"]

    def test_attempts_hide_private_values_and_submit_questions_once(self) -> None:
        first, second = self._program(2), self._program(3)
        assert self._post("/workspace", {}, "enter")["status"] == "PENDING"
        self._post("/workspace", {}, "refresh")
        assert StudentWorkspace.objects.filter(task=self.task).count() == 1
        cases = [
            {"input": key, "output": key} for key in ("0", "1", "hidden-2", "hidden-3", "hidden-4")
        ]
        runtime = Mock()
        runtime.execute.side_effect = [
            (None, [StdioResult("PASSED", "self test")]),
            (
                None,
                [StdioResult("PASSED", case["output"]) for case in cases[:-1]]
                + [StdioResult("PASSED", "private failure detail")],
            ),
            (None, [StdioResult("PASSED", case["output"]) for case in cases]),
            (None, [StdioResult("PASSED", case["output"]) for case in cases]),
        ]
        with (
            patch("apps.experiments.workspace_assessment.create_code_snapshot", self._snapshot),
            patch("apps.experiments.workspace_judge._cases", return_value=cases),
            patch("apps.experiments.workspace_judge._read_source", return_value={"main.py": ""}),
            patch(
                "apps.experiments.workspace_judge.workspace_runtime",
                return_value=nullcontext(
                    runtime,
                ),
            ),
        ):
            self_test = self._attempt(first, "self-test", "input", "self-test")
            assert self_test["stdout"] == "self test"
            assert self_test["duration_ms"] is not None
            assert not self_test["case_results"]
            failed = self._attempt(first, "final-run", "", "final-failed")
            assert not failed["submitted"]
            assert failed["case_results"][4] == {"number": 5, "passed": False}
            assert failed["case_results"][0]["expected_output"] == "0"
            assert "hidden-" not in str(failed) and "private failure detail" not in str(failed)
            passed = self._attempt(first, "final-run", "", "final-first")
            assert passed["submitted"] and passed["next_question_id"] == second.public_id
            status = self.student_client.get(self.path + "/assessment", **self.student_headers)
            data = status.json()["data"]
            assert data["current_question_id"] == second.public_id
            assert len(data["questions"][1]["samples"]) == 2
            assert data["parts"][1]["score"] == "50.00"
            path = self.path + f"/questions/{first.public_id}"
            response = self.student_client.put(
                path + "/code/python",
                {"files": {"main.py": "changed"}},
                content_type="application/json",
                HTTP_IF_MATCH='"1"',
                **self.student_headers,
            )
            assert response.status_code == 409, response.content
            self._post(
                f"/questions/{first.public_id}/final-run",
                {
                    "language": "python",
                    "row_version": 1,
                    "stdin": "",
                },
                "repeat-locked",
                409,
            )
            assert self._attempt(second, "final-run", "", "final-second")["submitted"]
        self.task.refresh_from_db()
        assert self.task.status == "COMPLETED"
        assert ProgrammingSubmission.objects.filter(task=self.task).count() == 2
        assert not ReportSubmission.objects.exists()

    def test_choice_redo_and_expired_workspace_cleanup(self) -> None:
        assert self._post("/workspace", {}, "enter")["status"] == "NOT_REQUIRED"
        assert not StudentWorkspace.objects.exists()
        question = f"{self.path}/questions/{self.question.public_id}/draft"
        draft = self.student_client.get(question, **self.student_headers)
        response = self.student_client.put(
            question,
            {"selected_option_ids": ["b"]},
            content_type="application/json",
            HTTP_IF_MATCH=draft["ETag"],
            **self.student_headers,
        )
        version = response.json()["data"]["row_version"]
        self._program(2)
        self._post("/workspace", {}, "enter-program")
        payload = {"versions": {self.question.public_id: version}}
        result = self._post("/sections/choice/submissions", payload, "submit-one", 201)
        assert result["part"]["score"] == "100.00"
        self._post("/sections/choice/submissions", payload, "submit-again", 409)
        teacher, headers = self._login("TEACHING", self.owner.email)
        runtime = Mock()
        at = timezone.now() - timedelta(seconds=1)
        type(self.publication).objects.filter(pk=self.publication.pk).update(
            window_end=at,
            assignment_deadline=None,
        )
        StudentWorkspace.objects.filter(task=self.task).update(expires_at=at)
        with patch("apps.workspaces.tasks.workspace_runtime", return_value=nullcontext(runtime)):
            workspace = StudentWorkspace.objects.get(task=self.task)
            sync_student_workspace(workspace.pk)
            workspace.refresh_from_db()
            assert workspace.status == "EXPIRED"
            runtime.remove.assert_called_once()
            redo = teacher.post(
                self.teaching_path + "/assessment/parts",
                {
                    "part": "CHOICE",
                    "redo_until": (at + timedelta(hours=1)).isoformat(),
                },
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="redo-choice",
                **headers,
            )
            assert redo.status_code == 200, redo.content
            result = self._post("/sections/choice/submissions", payload, "submit-redo", 201)
            assert result["part"]["score"] == "60.00"

    def test_report_upload_replacement_and_teacher_redo_score_cap(self) -> None:
        teacher, headers = self._login("TEACHING", self.owner.email)
        template_url = (
            f"/api/v2/teaching/courses/{self.course.public_id}/experiments/"
            f"{self.publication.public_id}/report-template"
        )
        store = Mock()
        store.put_stream.return_value = SimpleNamespace(version_id="version")

        def upload(url: str, file_name: str, key: str, client: Client, auth: dict[str, str]) -> Any:
            response = client.post(
                url,
                {"file": SimpleUploadedFile(file_name, b"document")},
                HTTP_IDEMPOTENCY_KEY=key,
                **auth,
            )
            assert response.status_code == 200, response.content
            return response.json()["data"]

        with (
            patch("apps.reports.assessment_reports.object_storage", return_value=store),
            patch("apps.reports.assessment_reports.ClamAVScanner") as scan,
        ):
            scan.return_value.scan.return_value.clean = True
            type(self.publication).objects.filter(pk=self.publication.pk).update(status="DRAFT")
            template = upload(
                template_url,
                "template.txt",
                "template",
                teacher,
                {
                    **headers,
                    "HTTP_IF_MATCH": f'"{self.publication.row_version}"',
                },
            )
            type(self.publication).objects.filter(pk=self.publication.pk).update(status="PUBLISHED")
            self._post("/workspace", {}, "enter")
            url = self.path + "/report"
            first = upload(
                url,
                "first.txt",
                "upload-one",
                self.student_client,
                self.student_headers,
            )
            assert first["template"] == template["report_template"]
            second = upload(
                url,
                "second.txt",
                "upload-two",
                self.student_client,
                self.student_headers,
            )
            assert ReportSubmission.objects.filter(task=self.task).count() == 1
            assert second["attachment"]["file_name"] == "second.txt"
            assert ObjectAsset.objects.get(public_id=first["attachment"]["asset_id"]).status == (
                "PURGE_PENDING"
            )
            at = timezone.now() - timedelta(seconds=1)
            type(self.publication).objects.filter(pk=self.publication.pk).update(
                window_end=at,
                assignment_deadline=None,
            )
            response = teacher.post(
                self.teaching_path + "/assessment/parts",
                {
                    "part": "REPORT",
                    "redo_until": (at + timedelta(days=1)).isoformat(),
                },
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="redo-report",
                **headers,
            )
            assert response.status_code == 200, response.content
            assert ReportSubmission.objects.get(task=self.task).status == "RETURNED"
            latest = upload(
                url,
                "redo.txt",
                "upload-redo",
                self.student_client,
                self.student_headers,
            )
            response = teacher.post(
                self.teaching_path + "/report",
                {"score": "90"},
                content_type="application/json",
                HTTP_IF_MATCH=f'"{latest["row_version"]}"',
                HTTP_IDEMPOTENCY_KEY="grade",
                **headers,
            )
            assert response.status_code == 200, response.content
            assert response.json()["data"]["score"] == "60.00"

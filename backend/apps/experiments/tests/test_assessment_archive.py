import json
import zipfile

from django.test import TestCase

from apps.archives.services import _build_package


class AssessmentArchiveTests(TestCase):
    def setUp(self) -> None:
        from .test_assessment import AssessmentTests

        AssessmentTests.setUp(self)

    def test_choice_archive_contains_own_answers_not_marking_configuration(self) -> None:
        from ..assessment import read_draft, save_draft, submit_choices

        draft = read_draft(
            actor=self.student, task_id=self.task.public_id, question_id=self.question.public_id,
        )
        saved = save_draft(
            actor=self.student, task_id=self.task.public_id, question_id=self.question.public_id,
            expected_version=draft["row_version"], data={"selected_option_ids": ["b"]},
        )
        submit_choices(
            actor=self.student, task_id=self.task.public_id,
            versions={self.question.public_id: saved["row_version"]}, trace_id="a" * 32,
        )
        self.task.refresh_from_db()
        package, _, _, _ = _build_package(self.task)
        try:
            with zipfile.ZipFile(package) as archive:
                text = "\n".join(archive.read(name).decode() for name in archive.namelist())
                assert "secret explanation" not in text
                assert "correct_option_ids" not in text
                report = json.loads(archive.read("report.json"))
                assert report["submissions"][0]["answers"][0]["selected_option_ids"] == ["b"]
        finally:
            package.close()

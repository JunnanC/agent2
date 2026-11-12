import io
import json
import os
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.core.tests.storage import InMemoryObjectStorage
from apps.governance.models import RuntimeAdapter
from apps.labtemplates.models import Template, TemplateTask

from ..models import TaskPublication


class AssessmentSeedTests(TestCase):
    def setUp(self) -> None:
        from .test_assessment import AssessmentTests

        AssessmentTests.setUp(self)

    def test_choice_seed_is_repeatable_and_requires_no_runtime_arguments(self) -> None:
        options = {
            "course_id": self.course.public_id, "kind": "CHOICE", "run_id": "seed-test",
        }
        with (
            patch.dict(os.environ, APP_ENV="test"),
            patch("apps.core.tasks.relay_outbox.apply_async"),
        ):
            first, second = io.StringIO(), io.StringIO()
            call_command("seed_assessment_e2e", **options, stdout=first)
            call_command("seed_assessment_e2e", **options, stdout=second)
        assert json.loads(first.getvalue()) == json.loads(second.getvalue())
        publication = TaskPublication.objects.get(course=self.course, title="seed-test-choice")
        assert publication.runtime_adapter_id is None
        assert publication.tasks.count() == 1
        assert list(TemplateTask.objects.filter(
            chapter__template_version=publication.template_version,
        ).values_list("task_type", flat=True).order_by("sort_order")) == [
            "SINGLE_CHOICE", "MULTIPLE_CHOICE",
        ]

    def test_production_guard_runs_before_any_seed_writes(self) -> None:
        count = Template.objects.count()
        with patch.dict(os.environ, APP_ENV="production"), self.assertRaises(CommandError):
            call_command("seed_assessment_e2e", course_id=self.course.public_id, kind="CHOICE")
        assert Template.objects.count() == count

    @override_settings(LOCAL_RUNTIME_MODE="REAL")
    def test_three_forms_publish_without_importing_test_helpers_or_faking_a_judge(self) -> None:
        version = self.publication.template_version
        RuntimeAdapter.objects.filter(pk=version.runtime_adapter_id).update(
            driver="DOCKER_LOCAL", config_ref="assessment/local",
        )
        with (
            patch.dict(os.environ, APP_ENV="test"),
            patch("apps.core.object_storage.S3ObjectStorage", InMemoryObjectStorage),
            patch("apps.labtemplates.assessment_assets.ClamAVScanner") as scanner,
            patch("apps.labtemplates.questions._precheck_references") as reference,
            patch("apps.core.tasks.relay_outbox.apply_async"),
        ):
            scanner.return_value.scan.return_value.clean = True
            output = io.StringIO()
            call_command(
                "seed_assessment_e2e", course_id=self.course.public_id, run_id="three-forms",
                runtime_id=version.runtime_adapter.public_id, image_id=version.image.public_id,
                profile_id=version.resource_profile.public_id, stdout=output,
            )
        result = json.loads(output.getvalue())
        assert {item["kind"] for item in result["fixtures"]} == {"CHOICE", "PROGRAMMING", "MIXED"}
        assert reference.call_count == 2
        for fixture in result["fixtures"]:
            publication = TaskPublication.objects.get(public_id=fixture["publication_id"])
            assert publication.status == "PUBLISHED"
            assert publication.report_required == (fixture["kind"] == "MIXED")
            assert publication.tasks.count() == 1

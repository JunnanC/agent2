from django.core.management.base import CommandError
from django.test import TestCase

from apps.core.concurrency import compare_and_swap
from apps.core.models import ObjectAsset
from apps.experiments.models import ExperimentTask
from apps.experiments.services import publish_publication
from apps.experiments.tests.helpers import (
    context,
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.labtemplates.errors import TemplateAssetNotReady
from apps.labtemplates.models import TemplateVersion
from apps.workspaces.workbench import _validate_tests_asset, workbench_data

from ..management.commands.seed_simulated_experiment import Command


class SimulatedExperimentSeedTests(TestCase):
    def setUp(self) -> None:
        self.teacher, self.course, self.source, self.rubric = create_domain(suffix="seed-assets")
        self.version = TemplateVersion.objects.create(
            template=self.source.template,
            version_no=self.source.version_no + 1,
            runtime_type=self.source.runtime_type,
            runtime_adapter=Command._fake_adapter(),
            image=self.source.image,
            resource_profile=self.source.resource_profile,
            execution_spec=self.source.execution_spec,
            created_by=self.teacher,
        )

    def test_new_version_and_repeat_repair_preserve_source(self) -> None:
        with self.assertRaises(TemplateAssetNotReady):
            _validate_tests_asset(self.version)
        version = Command._ensure_tests_asset(self.version)
        asset = ObjectAsset.objects.get(public_id=version.execution_spec["tests_asset"])
        self.assertEqual(asset.owner_ref, version.public_id)
        self.assertNotEqual(asset.public_id, self.source.execution_spec["tests_asset"])
        self.assertEqual(asset.status, ObjectAsset.Status.ACTIVE)
        self.assertEqual(asset.scan_status, ObjectAsset.ScanStatus.CLEAN)
        source_asset = ObjectAsset.objects.get(public_id=self.source.execution_spec["tests_asset"])
        self.assertNotEqual(asset.object_key, source_asset.object_key)
        count = ObjectAsset.objects.count()
        repeated = Command._ensure_tests_asset(version)
        self.assertEqual(repeated.row_version, version.row_version)
        self.assertEqual(ObjectAsset.objects.count(), count)
        _validate_tests_asset(repeated)
        _validate_tests_asset(self.source)

    def test_repeat_seed_repairs_existing_published_version_and_workbench(self) -> None:
        enrollment = create_enrollment(self.course, suffix="seed-student")
        type(enrollment.student).objects.filter(pk=enrollment.student_id).update(
            email="student.integration@example.edu"
        )
        publication = create_draft_publication(
            owner=self.teacher,
            course=self.course,
            template_version=self.source,
            rubric_version=self.rubric,
        )
        publish_publication(
            course_id=self.course.public_id,
            publication_id=publication.public_id,
            actor=self.teacher,
            expected_version=publication.row_version,
            selected_ids=None,
            context=context(self.teacher),
        )
        self.version = compare_and_swap(
            TemplateVersion,
            pk=self.version.pk,
            expected_version=self.version.row_version,
            changes={"status": TemplateVersion.Status.PUBLISHED, "spec_digest": "f" * 64},
        )
        # Reproduce a legacy publication/task pointing at the derived version.
        type(publication).objects.filter(pk=publication.pk).update(
            title="P07 FakeRuntime 任务", template_version=self.version
        )
        task = ExperimentTask.objects.get(publication=publication)
        ExperimentTask.objects.filter(pk=task.pk).update(template_version=self.version)
        with self.assertRaises(TemplateAssetNotReady):
            workbench_data(actor=task.student, task_id=task.public_id)
        repaired = Command._fake_template_version(
            self.course, self.teacher, self.version.runtime_adapter, "a" * 32
        )
        self.assertEqual(repaired.public_id, self.version.public_id)
        publication.refresh_from_db()
        self.assertEqual(publication.title, "模拟环境实验任务")
        workbench_data(actor=task.student, task_id=task.public_id)
        _validate_tests_asset(self.source)
        count = ObjectAsset.objects.count()
        repeated = Command._fake_template_version(
            self.course, self.teacher, self.version.runtime_adapter, "a" * 32
        )
        self.assertEqual(repeated.row_version, repaired.row_version)
        self.assertEqual(ObjectAsset.objects.count(), count)

    def test_legacy_adapter_is_renamed_and_reused(self) -> None:
        adapter = self.version.runtime_adapter
        type(adapter).objects.filter(pk=adapter.pk).update(
            code="FAKE-LOCAL-P07", name="P07 Local FakeRuntime"
        )
        count = type(adapter).objects.count()
        renamed = Command._fake_adapter()
        self.assertEqual(renamed.pk, adapter.pk)
        self.assertEqual(renamed.name, "本地模拟实验环境")
        self.assertEqual(renamed.code, "FAKE-LOCAL-P07")
        self.assertEqual(type(adapter).objects.count(), count)
        self.assertEqual(Command._fake_adapter().row_version, renamed.row_version)

    def test_previous_command_remains_an_alias(self) -> None:
        from django.core.management import load_command_class

        command = load_command_class("apps.provisioning", "seed_provisioning_e2e")
        self.assertIsInstance(command, Command)

    def test_unclean_source_is_rejected_without_creating_assets(self) -> None:
        ObjectAsset.objects.filter(public_id=self.source.execution_spec["tests_asset"]).update(
            scan_status=ObjectAsset.ScanStatus.PENDING
        )
        count = ObjectAsset.objects.count()
        with self.assertRaises(CommandError):
            Command._ensure_tests_asset(self.version)
        self.assertEqual(ObjectAsset.objects.count(), count)

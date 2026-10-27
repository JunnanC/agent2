import inspect
from typing import Any, cast
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.core.errors import RowVersionConflict
from apps.core.models import ObjectAsset
from apps.governance.models import ResourceProfile
from apps.provisioning.adapters import RuntimeAdapterFailure, fake_runtime, reset_fake_runtime

from ..errors import TemplateStateConflict, TemplateValidationError
from ..image_services import (
    create_experiment_image,
    prepare_experiment_image,
    resolve_external_digest,
)
from ..models import (
    AutoCheckRule,
    ExperimentImage,
    TemplateChapter,
    TemplatePrecheckRun,
    TemplateTask,
    TemplateVersion,
)
from ..serializers import version_data
from ..services import (
    build_execution_command,
    clone_version,
    compute_spec_digest,
    create_chapter,
    create_task,
    execute_precheck,
    publish_version,
    reorder_chapters,
    reorder_tasks,
    replace_rules,
    request_precheck,
    update_chapter,
    update_task,
    update_version,
)
from ..tasks import prepare_experiment_image_task
from .helpers import add_valid_rule, context, create_template_version


class TemplateServiceTests(TestCase):
    def test_prepare_task_payload_contains_no_build_args(self) -> None:
        self.assertNotIn("build_args", str(inspect.signature(prepare_experiment_image_task.run)))

    def test_image_requires_registry_and_seals_build_args(self) -> None:
        owner, _course, _template, version = create_template_version(suffix="image-secrets")
        with self.assertRaises(TemplateValidationError):
            create_experiment_image(
                template_version=version,
                source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
                repository="labs/external",
                requested_tag="v1",
                actor=owner,
                context=context(owner, "image"),
            )
        image = create_experiment_image(
            template_version=version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry="registry.example.edu",
            repository="labs/external",
            requested_tag="v1",
            build_args={"TOKEN": "super-secret"},
            actor=owner,
            context=context(owner, "image"),
        )
        self.assertNotIn("super-secret", str(image.build_args_masked))
        self.assertNotIn("super-secret", image.build_args_sealed)

    def test_image_reference_is_normalized_and_strictly_validated(self) -> None:
        owner, _course, _template, version = create_template_version(suffix="image-reference")
        image = create_experiment_image(
            template_version=version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry=" REGISTRY.EXAMPLE.EDU:5000 ",
            repository="Labs/External",
            requested_tag=" v1.0 ",
            actor=owner,
            context=context(owner, "image-reference"),
        )
        self.assertEqual(image.registry, "registry.example.edu:5000")
        self.assertEqual(image.repository, "labs/external")
        self.assertEqual(image.requested_tag, "v1.0")
        invalid = (
            "https://registry.example.edu",
            "registry.example.edu/path",
            "user@registry.example.edu",
            "registry.example.edu:bad",
            "registry.example.edu:65536",
            "registry..example.edu",
        )
        for registry in invalid:
            with self.subTest(registry=registry), self.assertRaises(TemplateValidationError):
                create_experiment_image(
                    template_version=version,
                    source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
                    registry=registry,
                    repository="labs/external",
                    requested_tag="v1",
                    actor=owner,
                    context=context(owner, "image-invalid"),
                )
        for repository, tag in (("labs/external:latest", "v1"), ("labs/external", "bad/tag")):
            with self.subTest(repository=repository, tag=tag), self.assertRaises(
                TemplateValidationError
            ):
                create_experiment_image(
                    template_version=version,
                    source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
                    registry="registry.example.edu",
                    repository=repository,
                    requested_tag=tag,
                    actor=owner,
                    context=context(owner, "image-invalid-ref"),
                )

    def test_image_registry_allowlist_is_fail_closed_when_configured(self) -> None:
        owner, _course, _template, version = create_template_version(suffix="image-allowlist")
        with (
            override_settings(EXPERIMENT_IMAGE_REGISTRY_ALLOWLIST=("registry.example.edu",)),
            self.assertRaises(TemplateValidationError),
        ):
            create_experiment_image(
                template_version=version,
                source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
                registry="other.example.edu",
                repository="labs/external",
                requested_tag="v1",
                actor=owner,
                context=context(owner, "image-allowlist"),
            )

    def test_resolve_external_digest_preserves_runtime_failure_code_and_retryable(self) -> None:
        owner, _course, _template, version = create_template_version(suffix="image-failure-map")
        image = create_experiment_image(
            template_version=version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry="registry.example.edu",
            repository="labs/external",
            requested_tag="v1",
            actor=owner,
            context=context(owner, "image-failure"),
        )

        class FailingRuntime:
            def __init__(self, stage: str, failure: RuntimeAdapterFailure) -> None:
                self.stage = stage
                self.failure = failure

            def build_image(self, **_kwargs: object) -> dict[str, str]:
                if self.stage == "build":
                    raise self.failure
                return {"digest": "sha256:" + "a" * 64}

            def resolve_image(self, **_kwargs: object) -> dict[str, str]:
                if self.stage == "resolve":
                    raise self.failure
                return {"digest": "sha256:" + "a" * 64}

            def validate_image(self, **_kwargs: object) -> dict[str, bool]:
                if self.stage == "validate":
                    raise self.failure
                return {"valid": True}

        with self.assertRaises(RuntimeAdapterFailure) as raised:
            resolve_external_digest(
                image_id=image.public_id,
                runtime=FailingRuntime(
                    "resolve", RuntimeAdapterFailure("RUNTIME_IMAGE_PULL_FAILED", retryable=True)
                ),
            )
        self.assertEqual(raised.exception.code, "RUNTIME_IMAGE_PULL_FAILED")
        self.assertTrue(raised.exception.retryable)
        image.refresh_from_db()
        self.assertEqual(image.error_code, "RUNTIME_IMAGE_PULL_FAILED")

        image = create_experiment_image(
            template_version=version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry="registry.example.edu",
            repository="labs/validate",
            requested_tag="v1",
            actor=owner,
            context=context(owner, "image-validate"),
        )
        with self.assertRaises(RuntimeAdapterFailure) as raised:
            resolve_external_digest(
                image_id=image.public_id,
                runtime=FailingRuntime(
                    "validate",
                    RuntimeAdapterFailure("RUNTIME_IMAGE_VALIDATE_FAILED", retryable=False),
                ),
            )
        self.assertEqual(raised.exception.code, "RUNTIME_IMAGE_VALIDATE_FAILED")
        self.assertFalse(raised.exception.retryable)

    def test_prepare_build_failure_preserves_runtime_failure_metadata(self) -> None:
        owner, _course, _template, version = create_template_version(suffix="image-build-failure")
        context_asset = ObjectAsset.objects.create(
            bucket="test-assets",
            object_key="contexts/context.tgz",
            object_version="v1",
            digest_sha256="c" * 64,
            size_bytes=1,
            media_type="application/gzip",
            original_name="context.tgz",
            owner_type="TEMPLATE_VERSION",
            owner_ref=version.public_id,
            purpose="BUILD_CONTEXT",
            scan_status=ObjectAsset.ScanStatus.CLEAN,
            status=ObjectAsset.Status.ACTIVE,
        )
        image = create_experiment_image(
            template_version=version,
            source_type=ExperimentImage.SourceType.BUILD_CONTEXT,
            registry="registry.example.edu",
            repository="labs/build",
            requested_tag="v1",
            build_context_asset_id=context_asset.public_id,
            actor=owner,
            context=context(owner, "image-build-failure"),
        )

        class FailingBuildRuntime:
            def build_image(self, **_kwargs: object) -> dict[str, str]:
                raise RuntimeAdapterFailure("RUNTIME_IMAGE_BUILD_FAILED", retryable=True)

            def resolve_image(self, **_kwargs: object) -> dict[str, str]:
                return {"digest": "sha256:" + "a" * 64}

            def validate_image(self, **_kwargs: object) -> dict[str, bool]:
                return {"valid": True}

        with patch(
            "apps.labtemplates.image_services._build_context_archive", return_value=b"context"
        ):
            prepared = prepare_experiment_image(
                image_id=image.public_id, runtime=FailingBuildRuntime()
            )
        self.assertEqual(prepared.status, ExperimentImage.Status.FAILED)
        self.assertEqual(prepared.error_code, "RUNTIME_IMAGE_BUILD_FAILED")
        self.assertTrue(prepared._runtime_failure.retryable)

    def test_external_digest_uses_supplied_runtime_and_maps_missing_image(self) -> None:
        owner, _course, _template, version = create_template_version(suffix="image-runtime")
        image = create_experiment_image(
            template_version=version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry="registry.example.edu",
            repository="labs/external",
            requested_tag="v1",
            actor=owner,
            context=context(owner, "image"),
        )
        runtime = fake_runtime()
        with (
            patch(
                "apps.labtemplates.image_services.runtime_for_driver", side_effect=AssertionError
            ),
            self.assertRaises(Exception) as not_ready,
        ):
            resolve_external_digest(image_id=image.public_id, runtime=runtime)
        self.assertEqual(getattr(not_ready.exception, "code", ""), "IMAGE_GOVERNANCE_NOT_READY")
        with self.assertRaises(Exception) as raised:
            resolve_external_digest(image_id="0" * 26, runtime=runtime)
        self.assertEqual(getattr(raised.exception, "code", ""), "RESOURCE_NOT_FOUND")

    def test_external_reference_resolves_to_governed_ready_digest(self) -> None:
        owner, _course, _template, version = create_template_version(suffix="image-external")
        reset_fake_runtime()
        image = create_experiment_image(
            template_version=version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry="registry.example.edu",
            repository="labs/external",
            requested_tag="v1",
            actor=owner,
            context=context(owner, "image"),
        )
        with patch(
            "apps.labtemplates.image_services.runtime_for_driver",
            return_value=fake_runtime(),
        ):
            prepared = prepare_experiment_image(image_id=image.public_id)
        self.assertEqual(prepared.status, ExperimentImage.Status.PENDING_APPROVAL)
        self.assertTrue(prepared.resolved_digest.startswith("sha256:"))
        self.assertFalse(prepared.image_asset.is_ready)
        self.assertEqual(prepare_experiment_image(image_id=image.public_id).pk, prepared.pk)

    def test_build_context_rejects_unscanned_asset_without_runtime_call(self) -> None:
        owner, _course, _template, version = create_template_version(suffix="image-build")
        context_asset = ObjectAsset.objects.create(
            bucket="test-assets",
            object_key="contexts/context.tar",
            object_version="v1",
            digest_sha256="c" * 64,
            size_bytes=1,
            owner_type="TEMPLATE_VERSION",
            owner_ref=version.public_id,
            purpose="BUILD_CONTEXT",
            scan_status=ObjectAsset.ScanStatus.PENDING,
            status=ObjectAsset.Status.ACTIVE,
        )
        image = create_experiment_image(
            template_version=version,
            source_type=ExperimentImage.SourceType.BUILD_CONTEXT,
            registry="registry.example.edu",
            repository="labs/build",
            requested_tag="v1",
            build_context_asset_id=context_asset.public_id,
            actor=owner,
            context=context(owner, "build"),
        )
        reset_fake_runtime()
        with patch(
            "apps.labtemplates.image_services.runtime_for_driver",
            return_value=fake_runtime(),
        ):
            prepared = prepare_experiment_image(image_id=image.public_id)
        self.assertEqual(prepared.status, ExperimentImage.Status.FAILED)
        self.assertEqual(prepared.error_code, "TEMPLATE_ASSET_NOT_READY")
        self.assertNotIn(("IMAGE_BUILD", "call"), fake_runtime().calls)

    def test_versioned_content_orders_inherits_resources_and_serializes_nested(self) -> None:
        owner, course, _template, version = create_template_version(suffix="content")
        create_chapter(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            data={"title": "Second", "sort_order": 2},
            context=context(owner, "a"),
        )
        version.refresh_from_db()
        first = create_chapter(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            data={"title": "First", "sort_order": 1},
            context=context(owner, "b"),
        )
        version.refresh_from_db()
        task = create_task(
            course_id=course.public_id,
            chapter_id=first.public_id,
            actor=owner,
            expected_version=version.row_version,
            data={"title": "Inherited task", "task_type": "CODE", "sort_order": 1},
            context=context(owner, "c"),
        )
        version.refresh_from_db()
        data = version_data(version)
        chapters = cast(list[dict[str, Any]], data["chapters"])
        self.assertEqual([item["title"] for item in chapters], ["First", "Second"])
        self.assertEqual(chapters[0]["tasks"][0]["public_id"], task.public_id)
        self.assertEqual(
            chapters[0]["tasks"][0]["effective_resource_profile_id"],
            version.resource_profile.public_id,
        )

    def test_content_reorder_rejects_duplicate_and_mixed_parent_ids(self) -> None:
        owner, course, _template, version = create_template_version(suffix="content-order")
        first = create_chapter(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            data={"title": "First"},
            context=context(owner, "a"),
        )
        version.refresh_from_db()
        second = create_chapter(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            data={"title": "Second"},
            context=context(owner, "b"),
        )
        version.refresh_from_db()
        with self.assertRaises(TemplateValidationError):
            reorder_chapters(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=owner,
                expected_version=version.row_version,
                chapter_ids=[first.public_id, first.public_id],
                context=context(owner, "c"),
            )
        with self.assertRaises(TemplateValidationError):
            reorder_tasks(
                course_id=course.public_id,
                chapter_id=first.public_id,
                actor=owner,
                expected_version=version.row_version,
                task_ids=[second.public_id],
                context=context(owner, "d"),
            )
        reordered = reorder_chapters(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            chapter_ids=[second.public_id, first.public_id],
            context=context(owner, "e"),
        )
        self.assertEqual(
            [
                item.sort_order
                for item in TemplateChapter.objects.filter(template_version=reordered).order_by(
                    "sort_order"
                )
            ],
            [1, 2],
        )

    def test_content_is_locked_after_publication(self) -> None:
        owner, course, _template, version = create_template_version(suffix="content-lock")
        TemplateVersion.objects.filter(pk=version.pk).update(
            status=TemplateVersion.Status.PUBLISHED
        )
        version.refresh_from_db()
        with self.assertRaises(TemplateStateConflict):
            create_chapter(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=owner,
                expected_version=version.row_version,
                data={"title": "Locked"},
                context=context(owner, "a"),
            )

    def test_child_edits_use_template_version_cas_and_clone_content(self) -> None:
        owner, course, _template, version = create_template_version(suffix="content-clone")
        chapter = create_chapter(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            data={"title": "Chapter"},
            context=context(owner, "a"),
        )
        version.refresh_from_db()
        task = create_task(
            course_id=course.public_id,
            chapter_id=chapter.public_id,
            actor=owner,
            expected_version=version.row_version,
            data={"title": "Task", "task_type": "CODE"},
            context=context(owner, "b"),
        )
        version.refresh_from_db()
        stale_version = version.row_version
        update_chapter(
            course_id=course.public_id,
            chapter_id=chapter.public_id,
            actor=owner,
            expected_version=stale_version,
            changes={"description": "changed"},
            context=context(owner, "c"),
        )
        with self.assertRaises(RowVersionConflict):
            update_task(
                course_id=course.public_id,
                task_id=task.public_id,
                actor=owner,
                expected_version=stale_version,
                changes={"description": "stale"},
                context=context(owner, "d"),
            )
        TemplateVersion.objects.filter(pk=version.pk).update(
            status=TemplateVersion.Status.PUBLISHED
        )
        version.refresh_from_db()
        cloned = clone_version(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner, "e"),
        )
        self.assertEqual(cloned.chapters.count(), 1)
        self.assertEqual(cloned.chapters.first().tasks.count(), 1)

    def test_reorder_requires_complete_collection(self) -> None:
        owner, course, _template, version = create_template_version(suffix="content-partial")
        first = create_chapter(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            data={"title": "First"},
            context=context(owner, "a"),
        )
        version.refresh_from_db()
        create_chapter(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            data={"title": "Second"},
            context=context(owner, "b"),
        )
        version.refresh_from_db()
        with self.assertRaises(TemplateValidationError):
            reorder_chapters(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=owner,
                expected_version=version.row_version,
                chapter_ids=[first.public_id],
                context=context(owner, "c"),
            )

    def test_execution_spec_is_in_digest_and_only_generates_python_command(self) -> None:
        owner, course, _template, version = create_template_version(suffix="execution")
        version = add_valid_rule(owner=owner, course=course, version=version)
        self.assertEqual(build_execution_command(version.execution_spec), ["python", "main.py"])
        digest = compute_spec_digest(version)
        self.assertEqual(len(digest), 64)
        changed = dict(version.execution_spec)
        changed["entrypoint"] = "solution.py"
        version.execution_spec = changed
        self.assertNotEqual(compute_spec_digest(version), digest)

    def test_execution_spec_rejects_command_and_unscanned_tests_asset(self) -> None:
        owner, course, _template, version = create_template_version(suffix="execution-guards")
        with self.assertRaises(TemplateValidationError):
            update_version(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=owner,
                expected_version=version.row_version,
                changes={
                    "execution_spec": {
                        **version.execution_spec,
                        "command": "python main.py; curl http://example.invalid",
                    }
                },
                context=context(owner),
            )
        tests_asset = ObjectAsset.objects.get(public_id=version.execution_spec["tests_asset"])
        ObjectAsset.objects.filter(pk=tests_asset.pk).update(
            scan_status=ObjectAsset.ScanStatus.PENDING
        )
        version = TemplateVersion.objects.get(pk=version.pk)
        run = request_precheck(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner, "u"),
        )
        completed = execute_precheck(run_id=run.public_id)
        self.assertEqual(completed.status, TemplatePrecheckRun.Status.FAILED)
        self.assertEqual(completed.error_code, "TEMPLATE_ASSET_NOT_READY")

    def test_failed_precheck_can_be_repaired_before_retry(self) -> None:
        owner, course, _template, version = create_template_version(suffix="execution-retry")
        tests_asset = ObjectAsset.objects.get(public_id=version.execution_spec["tests_asset"])
        ObjectAsset.objects.filter(pk=tests_asset.pk).update(
            scan_status=ObjectAsset.ScanStatus.PENDING
        )
        run = request_precheck(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner, "f"),
        )
        execute_precheck(run_id=run.public_id)
        version.refresh_from_db()
        ObjectAsset.objects.filter(pk=tests_asset.pk).update(
            scan_status=ObjectAsset.ScanStatus.CLEAN
        )
        repaired = update_version(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            changes={"execution_spec": version.execution_spec},
            context=context(owner, "g"),
        )
        self.assertEqual(repaired.status, TemplateVersion.Status.PRECHECK_FAILED)
        retry = request_precheck(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=repaired.row_version,
            context=context(owner, "h"),
        )
        self.assertEqual(
            execute_precheck(run_id=retry.public_id).status,
            TemplatePrecheckRun.Status.PASSED,
        )

    def test_precheck_freezes_publish_and_clone_preserves_spec(self) -> None:
        owner, course, _template, version = create_template_version(suffix="freeze")
        TemplateChapter.objects.create(
            template_version=version,
            title="Freeze chapter",
            description="",
            learning_objectives=[],
            sort_order=1,
            status=TemplateChapter.Status.DRAFT,
            resource_profile=version.resource_profile,
        )
        version = add_valid_rule(owner=owner, course=course, version=version)
        run = request_precheck(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner, "r"),
        )
        completed = execute_precheck(run_id=run.public_id)
        self.assertEqual(completed.status, TemplatePrecheckRun.Status.PASSED)
        self.assertEqual(
            [item["stage"] for item in completed.stage_results],
            ["SCOPE", "ASSETS", "GOVERNANCE", "RULES", "POLICY", "DIGEST"],
        )
        version = TemplateVersion.objects.get(pk=version.pk)
        self.assertEqual(version.status, TemplateVersion.Status.PRECHECK_PASSED)
        self.assertEqual(len(version.spec_digest or ""), 64)

        published = publish_version(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner),
        )
        with self.assertRaises(TemplateStateConflict):
            update_version(
                course_id=course.public_id,
                version_id=published.public_id,
                actor=owner,
                expected_version=published.row_version,
                changes={"retention_days": 60},
                context=context(owner),
            )
        clone = clone_version(
            course_id=course.public_id,
            version_id=published.public_id,
            actor=owner,
            expected_version=published.row_version,
            context=context(owner),
        )
        self.assertEqual(clone.status, TemplateVersion.Status.DRAFT)
        self.assertIsNone(clone.spec_digest)
        self.assertNotEqual(clone.public_id, published.public_id)
        self.assertEqual(clone.execution_spec["entrypoint"], published.execution_spec["entrypoint"])
        self.assertEqual(build_execution_command(clone.execution_spec), ["python", "main.py"])

    def test_publish_cascades_draft_chapters_and_tasks(self) -> None:
        owner, course, _template, version = create_template_version(suffix="cascade-publish")
        draft_chapter = TemplateChapter.objects.create(
            template_version=version,
            title="Cascade chapter",
            description="",
            learning_objectives=[],
            sort_order=1,
            status=TemplateChapter.Status.DRAFT,
            resource_profile=version.resource_profile,
        )
        create_task(
            course_id=course.public_id,
            chapter_id=draft_chapter.public_id,
            actor=owner,
            expected_version=version.row_version,
            data={"title": "Cascade task", "description": ""},
            context=context(owner, "cascade"),
        )
        digest = compute_spec_digest(version)
        TemplateVersion.objects.filter(pk=version.pk).update(
            status=TemplateVersion.Status.PRECHECK_PASSED, spec_digest=digest
        )
        version = TemplateVersion.objects.get(pk=version.pk)
        published = publish_version(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner, "pub"),
        )
        self.assertEqual(published.status, TemplateVersion.Status.PUBLISHED)
        for chapter in version.chapters.all():
            self.assertEqual(chapter.status, TemplateChapter.Status.PUBLISHED)
            for task in chapter.tasks.all():
                self.assertEqual(task.status, TemplateTask.Status.PUBLISHED)

    def test_publish_rejects_version_without_chapters(self) -> None:
        owner, course, _template, version = create_template_version(suffix="no-chapters")
        digest = compute_spec_digest(version)
        TemplateVersion.objects.filter(pk=version.pk).update(
            status=TemplateVersion.Status.PRECHECK_PASSED, spec_digest=digest
        )
        version = TemplateVersion.objects.get(pk=version.pk)
        with self.assertRaises(TemplateValidationError) as caught:
            publish_version(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=owner,
                expected_version=version.row_version,
                context=context(owner, "pub"),
            )
        self.assertEqual(caught.exception.detail, {"chapters": "at_least_one_required"})

    def test_precheck_passed_content_edit_reopens_draft(self) -> None:
        owner, course, _template, version = create_template_version(suffix="reopen-edit")
        TemplateVersion.objects.filter(pk=version.pk).update(
            status=TemplateVersion.Status.PRECHECK_PASSED, spec_digest="e" * 64
        )
        version = TemplateVersion.objects.get(pk=version.pk)
        chapter = TemplateChapter.objects.create(
            template_version=version,
            title="Late chapter",
            description="",
            learning_objectives=[],
            sort_order=1,
            status=TemplateChapter.Status.DRAFT,
            resource_profile=version.resource_profile,
        )
        task = create_task(
            course_id=course.public_id,
            chapter_id=chapter.public_id,
            actor=owner,
            expected_version=version.row_version,
            data={"title": "Late task", "description": "added after precheck"},
            context=context(owner, "reopen"),
        )
        self.assertEqual(task.title, "Late task")
        reopened = TemplateVersion.objects.get(pk=version.pk)
        self.assertEqual(reopened.status, TemplateVersion.Status.DRAFT)
        self.assertIsNone(reopened.spec_digest)
        self.assertNotEqual(reopened.row_version, version.row_version)

    def test_precheck_uses_profile_limits_when_requests_are_smaller(self) -> None:
        owner, course, _template, version = create_template_version(suffix="resource-limits")
        ResourceProfile.objects.filter(pk=version.resource_profile_id).update(
            cpu_millicores=250,
            memory_mb=128,
            cpu_request_millicores=125,
            cpu_limit_millicores=750,
            memory_request_mb=64,
            memory_limit_mb=384,
        )
        version = add_valid_rule(owner=owner, course=course, version=version)
        AutoCheckRule.objects.filter(template_version=version, is_active=True).update(
            resource_limit={"cpu_millicores": 750, "memory_mb": 384, "disk_gb": 2}
        )

        run = request_precheck(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner, "limits"),
        )

        self.assertEqual(
            execute_precheck(run_id=run.public_id).status,
            TemplatePrecheckRun.Status.PASSED,
        )

    def test_invalid_schema_records_exact_failed_stage(self) -> None:
        owner, course, _template, version = create_template_version(suffix="schema")
        version = replace_rules(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            rules=[
                {
                    "position": 1,
                    "checker_type": "PYTEST",
                    "input_schema": {"type": "not-a-json-schema-type"},
                    "output_schema": {"type": "object"},
                    "timeout_seconds": 10,
                    "resource_limit": {},
                    "network_policy": {"mode": "DENY_ALL"},
                    "display_policy": {},
                    "failure_semantics": {"on_failure": "FAIL_CHECK"},
                }
            ],
            context=context(owner),
        )
        run = request_precheck(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner),
        )
        completed = execute_precheck(run_id=run.public_id)
        self.assertEqual(completed.status, TemplatePrecheckRun.Status.FAILED)
        self.assertEqual(completed.current_stage, "RULES")
        self.assertEqual(completed.error_code, "TEMPLATE_VALIDATION_ERROR")
        self.assertEqual(completed.stage_results[-1]["result"], "FAILED")

    def test_governance_retirement_is_rechecked_by_precheck(self) -> None:
        owner, course, _template, version = create_template_version(suffix="retired")
        version = add_valid_rule(owner=owner, course=course, version=version)
        ResourceProfile.objects.filter(pk=version.resource_profile_id).update(status="RETIRED")
        run = request_precheck(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner),
        )
        completed = execute_precheck(run_id=run.public_id)
        self.assertEqual(completed.status, TemplatePrecheckRun.Status.FAILED)
        self.assertEqual(completed.current_stage, "GOVERNANCE")

    def test_rule_replacement_preserves_inactive_history(self) -> None:
        owner, course, _template, version = create_template_version(suffix="history")
        version = add_valid_rule(owner=owner, course=course, version=version)
        first = AutoCheckRule.objects.get(template_version=version, is_active=True)
        version = replace_rules(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            rules=[
                {
                    "position": 1,
                    "checker_type": "SHELL",
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "timeout_seconds": 30,
                    "resource_limit": {},
                    "network_policy": {"mode": "DENY_ALL"},
                    "display_policy": {},
                    "failure_semantics": {"on_failure": "WARN"},
                }
            ],
            context=context(owner),
        )
        self.assertEqual(AutoCheckRule.objects.filter(template_version=version).count(), 2)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertEqual(
            AutoCheckRule.objects.get(template_version=version, is_active=True).checker_type,
            "SHELL",
        )

    def test_cas_and_unavailable_resource_are_rejected(self) -> None:
        owner, course, template, version = create_template_version(suffix="guards")
        with self.assertRaises(RowVersionConflict):
            update_version(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=owner,
                expected_version=999,
                changes={"retention_days": 1},
                context=context(owner),
            )
        with self.assertRaises(TemplateValidationError):
            from ..services import create_version

            create_version(
                course_id=course.public_id,
                template_id=template.public_id,
                actor=owner,
                data={
                    "runtime_type": "CONTAINER",
                    "runtime_adapter_id": "0" * 26,
                    "image_id": "0" * 26,
                    "resource_profile_id": "0" * 26,
                },
                context=context(owner),
            )

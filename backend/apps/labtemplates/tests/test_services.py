import inspect
from typing import Any, cast
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.core.errors import RowVersionConflict
from apps.core.models import ObjectAsset
from apps.core.tests.image_runtime import image_runtime, reset_image_runtime
from apps.provisioning.adapters import RuntimeAdapterFailure

from ..errors import TemplateStateConflict, TemplateValidationError
from ..image_services import (
    create_experiment_image,
    prepare_experiment_image,
    resolve_external_digest,
)
from ..models import (
    ExperimentImage,
    TemplateChapter,
    TemplateTask,
    TemplateVersion,
)
from ..selectors import options_for_course
from ..serializers import version_data
from ..services import (
    clone_version,
    compute_spec_digest,
    create_chapter,
    create_task,
    publish_version,
    reorder_chapters,
    reorder_tasks,
    update_chapter,
    update_task,
    update_version,
)
from ..tasks import prepare_experiment_image_task
from ..toolchains import TOOLCHAIN_CATALOG
from .helpers import context, create_template_version


class TemplateServiceTests(TestCase):
    def test_teacher_options_return_language_catalog(self) -> None:
        owner, course, _template, _version = create_template_version(suffix="toolchain-options")
        options = options_for_course(actor=owner, course_id=course.public_id)
        self.assertEqual(
            [item["language"] for item in options["toolchains"]],
            ["c", "cpp", "java", "python", "go"],
        )

    def test_toolchain_catalog_marks_all_verified_image_languages_available(self) -> None:
        self.assertEqual(
            [item["language"] for item in TOOLCHAIN_CATALOG],
            ["c", "cpp", "java", "python", "go"],
        )
        available = [item for item in TOOLCHAIN_CATALOG if item["available"]]
        self.assertEqual(
            [item["language"] for item in available], ["c", "cpp", "java", "python", "go"]
        )
        self.assertTrue(
            all(any(version["default"] for version in item["versions"]) for item in available)
        )
        self.assertTrue(all(len(item["versions"]) == 1 for item in TOOLCHAIN_CATALOG))

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
            with (
                self.subTest(repository=repository, tag=tag),
                self.assertRaises(TemplateValidationError),
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
        runtime = image_runtime()
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
        reset_image_runtime()
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
            return_value=image_runtime(),
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
        reset_image_runtime()
        with patch(
            "apps.labtemplates.image_services.runtime_for_driver",
            return_value=image_runtime(),
        ):
            prepared = prepare_experiment_image(image_id=image.public_id)
        self.assertEqual(prepared.status, ExperimentImage.Status.FAILED)
        self.assertEqual(prepared.error_code, "TEMPLATE_ASSET_NOT_READY")
        self.assertNotIn(("IMAGE_BUILD", "call"), image_runtime().calls)

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
            data={
                "title": "Inherited task",
                "task_type": "SINGLE_CHOICE",
                "max_score": "5",
                "question_spec": {"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]},
                "marking_spec": {"correct_option_ids": ["b"]},
                "sort_order": 1,
            },
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
            data={
                "title": "Task",
                "task_type": "SINGLE_CHOICE",
                "max_score": "5",
                "question_spec": {"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]},
                "marking_spec": {"correct_option_ids": ["b"]},
            },
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
            data={
                "title": "Cascade task",
                "description": "",
                "task_type": "SINGLE_CHOICE",
                "max_score": "5",
                "question_spec": {"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]},
                "marking_spec": {"correct_option_ids": ["b"]},
            },
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
        digest = "a" * 64
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
            data={
                "title": "Late task",
                "description": "added after precheck",
                "task_type": "SINGLE_CHOICE",
                "max_score": "5",
                "question_spec": {"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]},
                "marking_spec": {"correct_option_ids": ["b"]},
            },
            context=context(owner, "reopen"),
        )
        self.assertEqual(task.title, "Late task")
        reopened = TemplateVersion.objects.get(pk=version.pk)
        self.assertEqual(reopened.status, TemplateVersion.Status.DRAFT)
        self.assertIsNone(reopened.spec_digest)
        self.assertNotEqual(reopened.row_version, version.row_version)

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

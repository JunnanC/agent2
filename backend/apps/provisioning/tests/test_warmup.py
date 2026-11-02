from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.experiments.models import TaskPublication
from apps.experiments.services import publish_publication
from apps.experiments.tests.helpers import context as experiment_context
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)

from ..adapters import RuntimeAdapterFailure
from ..ports import RuntimeSpec
from ..services import warmup_publication_image


class _RecordingAdapter:
    def __init__(self) -> None:
        self.prepare_calls: list[RuntimeSpec] = []
        self.resolve_calls: list[dict[str, str]] = []
        self.validate_calls: list[dict[str, str]] = []
        self.failures: dict[str, Exception] = {}

    def prepare_image(self, spec: RuntimeSpec) -> None:
        self.prepare_calls.append(spec)
        if "prepare_image" in self.failures:
            raise self.failures["prepare_image"]

    def resolve_image(self, *, registry: str, repository: str, tag: str) -> dict[str, str]:
        self.resolve_calls.append(
            {"registry": registry, "repository": repository, "tag": tag}
        )
        if "resolve_image" in self.failures:
            raise self.failures["resolve_image"]
        return {"digest": tag}

    def validate_image(self, *, digest: str) -> dict[str, object]:
        self.validate_calls.append({"digest": digest})
        if "validate_image" in self.failures:
            raise self.failures["validate_image"]
        return {"valid": True, "digest": digest}


class WarmupServiceTests(TestCase):
    def setUp(self) -> None:
        self.owner, self.course, self.template_version, self.rubric_version = create_domain(
            suffix="warmup"
        )
        self.enrollment = create_enrollment(self.course, suffix="warmup-student")
        self.publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="warmup",
        )
        self.published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=experiment_context(self.owner),
        )
        self.adapter = _RecordingAdapter()

    def _warmup(self) -> str:
        with patch(
            "apps.provisioning.services._runtime_adapter_for_row",
            return_value=self.adapter,
        ):
            return warmup_publication_image(
                publication_id=self.published.public_id, trace_id="warmup-trace"
            )

    def test_warmup_pulls_and_validates_the_pinned_digest(self) -> None:
        result = self._warmup()

        self.assertEqual(result, "warmed")
        self.assertEqual(len(self.adapter.resolve_calls), 1)
        self.assertEqual(
            self.adapter.resolve_calls[0],
            {
                "registry": self.published.image_registry,
                "repository": self.published.image_repository,
                "tag": self.published.image_digest,
            },
        )
        self.assertEqual(
            self.adapter.validate_calls[0], {"digest": self.published.image_digest}
        )
        self.assertEqual(self.adapter.prepare_calls, [])

    def test_local_registry_warmup_only_inspects_the_digest_reference(self) -> None:
        TaskPublication.objects.filter(pk=self.published.pk).update(
            image_registry="local", image_repository="experimental-platform-workspace"
        )
        self.published.refresh_from_db()

        result = self._warmup()

        self.assertEqual(result, "warmed")
        self.assertEqual(len(self.adapter.prepare_calls), 1)
        spec = self.adapter.prepare_calls[0]
        self.assertEqual(spec.image_registry, "local")
        self.assertEqual(spec.image_digest, self.published.image_digest)
        self.assertEqual(
            spec.image_ref,
            f"local/experimental-platform-workspace@{self.published.image_digest}",
        )
        self.assertEqual(self.adapter.resolve_calls, [])
        self.assertEqual(self.adapter.validate_calls, [])

    @override_settings(AUTO_PROVISION_ON_ASSIGNMENT=False)
    def test_disabled_warmup_performs_no_runtime_calls(self) -> None:
        result = self._warmup()

        self.assertEqual(result, "disabled")
        self.assertEqual(self.adapter.prepare_calls, [])
        self.assertEqual(self.adapter.resolve_calls, [])
        self.assertEqual(self.adapter.validate_calls, [])

    def test_unknown_publication_is_skipped(self) -> None:
        self.assertEqual(
            warmup_publication_image(publication_id="missing-publication"),
            "skipped_publication_status",
        )
        self.assertEqual(self.adapter.prepare_calls, [])
        self.assertEqual(self.adapter.resolve_calls, [])

    def test_publication_without_pinned_digest_is_skipped(self) -> None:
        TaskPublication.objects.filter(pk=self.published.pk).update(image_digest="")
        self.published.refresh_from_db()

        result = self._warmup()

        self.assertEqual(result, "skipped_image_snapshot")
        self.assertEqual(self.adapter.prepare_calls, [])
        self.assertEqual(self.adapter.resolve_calls, [])

    def test_runtime_failure_is_silent_and_keeps_the_publication(self) -> None:
        self.adapter.failures["resolve_image"] = RuntimeAdapterFailure(
            "RUNTIME_IMAGE_PULL_FAILED", retryable=True
        )

        result = self._warmup()

        self.assertEqual(result, "error")
        self.assertEqual(len(self.adapter.resolve_calls), 1)
        self.assertEqual(self.adapter.validate_calls, [])
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, TaskPublication.Status.PUBLISHED)

    def test_unexpected_failure_is_silent(self) -> None:
        self.adapter.failures["prepare_image"] = ValueError("docker engine offline")
        TaskPublication.objects.filter(pk=self.published.pk).update(
            image_registry="local", image_repository="experimental-platform-workspace"
        )

        result = self._warmup()

        self.assertEqual(result, "error")
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, TaskPublication.Status.PUBLISHED)


class PublishWarmupDispatchTests(TestCase):
    def setUp(self) -> None:
        self.owner, self.course, self.template_version, self.rubric_version = create_domain(
            suffix="dispatch"
        )
        self.enrollment = create_enrollment(self.course, suffix="dispatch-student")
        self.publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="dispatch",
        )

    def test_publish_dispatches_warmup_task_once_after_commit(self) -> None:
        with patch("apps.core.tasks.relay_outbox"), patch(
            "apps.provisioning.tasks.warmup_publication_image_task"
        ) as dispatch, self.captureOnCommitCallbacks(execute=True):
            published, _status = publish_publication(
                    course_id=self.course.public_id,
                    publication_id=self.publication.public_id,
                    actor=self.owner,
                    expected_version=self.publication.row_version,
                    selected_ids=[],
                    context=experiment_context(self.owner),
                )
        self.assertEqual(dispatch.apply_async.call_count, 1)
        self.assertEqual(
            dispatch.apply_async.call_args.kwargs["kwargs"]["publication_id"],
            published.public_id,
        )

    @override_settings(AUTO_PROVISION_ON_ASSIGNMENT=False)
    def test_publish_skips_warmup_dispatch_when_disabled(self) -> None:
        with patch("apps.core.tasks.relay_outbox"), patch(
            "apps.provisioning.tasks.warmup_publication_image_task"
        ) as dispatch, self.captureOnCommitCallbacks(execute=True):
            publish_publication(
                    course_id=self.course.public_id,
                    publication_id=self.publication.public_id,
                    actor=self.owner,
                    expected_version=self.publication.row_version,
                    selected_ids=[],
                    context=experiment_context(self.owner),
                )
        self.assertEqual(dispatch.apply_async.call_count, 0)

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.audit import append_audit, append_failure, hash_client_ip
from apps.core.concurrency import compare_and_swap
from apps.core.models import ObjectAsset
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.governance.models import ImageAsset, RuntimeAdapter
from apps.provisioning.adapters import RuntimeAdapterFailure, runtime_for_driver

from . import events
from .errors import TemplateAssetNotReady, TemplateValidationError
from .models import ExperimentImage, ImageBuildJob, TemplateVersion


class ExperimentImageRuntime(Protocol):
    def build_image(self, *, registry: str, repository: str, tag: str, context: Mapping[str, Any], build_args: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def resolve_image(self, *, registry: str, repository: str, tag: str) -> Mapping[str, Any]: ...
    def validate_image(self, *, digest: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ImagePreparationResult:
    digest: str
    logs: str = ""
    validation: Mapping[str, Any] = None  # type: ignore[assignment]


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _masked(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): "[REDACTED]" if "arg" in str(key).lower() or "secret" in str(key).lower() else _masked(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_masked(item) for item in value]
    return str(value)[:4000]


def _context(context: Any, trace_id: str = "") -> tuple[str, str, str, str, str]:
    return (
        str(getattr(context, "actor_ref", "system")),
        str(getattr(context, "portal", "TEACHING")),
        str(getattr(context, "trace_id", trace_id)),
        str(getattr(context, "client_ip", "")),
        str(getattr(context, "user_agent", "")),
    )


def _event(image: ExperimentImage, event_type: str, trace_id: str, payload: dict[str, Any]) -> None:
    append_outbox_event(
        event_type=event_type,
        aggregate_type="experiment_image",
        aggregate_ref=image.public_id,
        payload=payload,
        trace_id=trace_id,
    )
    enqueue_relay_after_commit(trace_id=trace_id)


def _runtime(adapter: RuntimeAdapter) -> ExperimentImageRuntime:
    runtime = runtime_for_driver(adapter.driver, config_ref=adapter.config_ref)
    missing = [name for name in ("build_image", "resolve_image", "validate_image") if not hasattr(runtime, name)]
    if missing:
        raise RuntimeAdapterFailure("RUNTIME_IMAGE_LIFECYCLE_UNAVAILABLE", retryable=False)
    return runtime  # type: ignore[return-value]


def create_experiment_image(
    *,
    template_version: TemplateVersion | None = None,
    template_version_id: str | None = None,
    version_id: str | None = None,
    source_type: str,
    repository: str,
    requested_tag: str,
    registry: str = "",
    build_context_asset_id: str | None = None,
    actor: Any,
    context: Any,
    build_args: Mapping[str, Any] | None = None,
) -> ExperimentImage:
    if source_type not in ExperimentImage.SourceType.values:
        raise TemplateValidationError(detail={"source_type": "unsupported"})
    version = template_version or TemplateVersion.objects.get(public_id=template_version_id or version_id)
    asset = None
    if source_type == ExperimentImage.SourceType.BUILD_CONTEXT:
        asset = ObjectAsset.objects.filter(public_id=build_context_asset_id).first()
        if asset is None or asset.owner_ref != version.public_id:
            raise TemplateValidationError(detail={"build_context_asset_id": "not_found"})
    elif build_context_asset_id:
        raise TemplateValidationError(detail={"build_context_asset_id": "not_allowed"})
    actor_ref, portal, trace_id, client_ip, user_agent = _context(context)
    image = ExperimentImage.objects.create(
        template_version=version,
        source_type=source_type,
        registry=registry.strip(),
        repository=repository.strip(),
        requested_tag=requested_tag.strip(),
        build_context_asset=asset,
        build_args_masked=_masked(dict(build_args or {})),
        trace_id=trace_id,
        created_by=actor,
    )
    append_audit(
        actor_ref=actor_ref, actor_portal=portal, actor_context={}, action="experiment_image.create",
        target_type="experiment_image", target_ref=image.public_id, course_ref=version.template.course.public_id,
        result="SUCCEEDED", trace_id=trace_id, after={"source_type": source_type, "requested_tag": requested_tag},
        client_ip_hash=hash_client_ip(client_ip, salt=settings.AUDIT_IP_HASH_SALT), user_agent_summary=user_agent,
    )
    _event(image, events.IMAGE_CREATED, trace_id, {"image_id": image.public_id, "source_type": source_type})
    return image


def prepare_experiment_image(*, image_id: str, trace_id: str = "") -> ExperimentImage:
    image = ExperimentImage.objects.select_related("template_version__template", "template_version__runtime_adapter", "build_context_asset").get(public_id=image_id)
    if image.status == ExperimentImage.Status.READY:
        return image
    if image.status == ExperimentImage.Status.RETIRED:
        return image
    trace_id = trace_id or image.trace_id
    if image.status != ExperimentImage.Status.PREPARING:
        image = compare_and_swap(ExperimentImage, pk=image.pk, expected_version=image.row_version, changes={"status": ExperimentImage.Status.PREPARING})
    job = ImageBuildJob.objects.filter(experiment_image=image).order_by("-created_at").first()
    if job is None or job.status in (ImageBuildJob.Status.FAILED, ImageBuildJob.Status.SUCCEEDED):
        job = ImageBuildJob.objects.create(experiment_image=image, status=ImageBuildJob.Status.RUNNING, attempt_count=1, build_args_masked=image.build_args_masked, trace_id=trace_id, started_at=timezone.now())
    try:
        adapter = image.template_version.runtime_adapter
        runtime = _runtime(adapter)
        if image.source_type == ExperimentImage.SourceType.BUILD_CONTEXT:
            asset = image.build_context_asset
            if asset is None or asset.scan_status != ObjectAsset.ScanStatus.CLEAN or asset.status != ObjectAsset.Status.ACTIVE:
                raise TemplateAssetNotReady(detail={"asset_id": getattr(asset, "public_id", "")})
            result = runtime.build_image(
                registry=image.registry, repository=image.repository, tag=image.requested_tag,
                context={"bucket": asset.bucket, "object_key": asset.object_key, "object_version": asset.object_version, "digest_sha256": asset.digest_sha256},
                build_args=image.build_args_masked,
            )
        else:
            result = runtime.resolve_image(registry=image.registry, repository=image.repository, tag=image.requested_tag)
        digest = str(result.get("digest", ""))
        if not _DIGEST.fullmatch(digest):
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_DIGEST_INVALID", retryable=False)
        validation = runtime.validate_image(digest=digest)
        if validation.get("valid", True) is False or validation.get("scan_status", "CLEAN") not in ("CLEAN", "clean"):
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_VALIDATION_FAILED", retryable=False)
        governed, created = ImageAsset.objects.get_or_create(
            digest=digest,
            defaults={"registry": image.registry, "repository": image.repository, "display_tag": image.requested_tag, "scan_status": ImageAsset.ScanStatus.CLEAN, "approval_status": ImageAsset.ApprovalStatus.APPROVED, "risk_level": ImageAsset.RiskLevel.LOW, "approved_by": image.created_by, "approved_at": timezone.now(), "change_reason": "experiment image preparation"},
        )
        if not created and not governed.is_ready:
            raise RuntimeAdapterFailure("IMAGE_GOVERNANCE_NOT_READY", retryable=False)
        image = compare_and_swap(ExperimentImage, pk=image.pk, expected_version=image.row_version, changes={"resolved_digest": digest, "image_asset_id": governed.pk, "status": ExperimentImage.Status.READY, "scan_status": ExperimentImage.ScanStatus.CLEAN, "validation_detail": _masked(dict(validation)), "logs_masked": _masked(result.get("logs", "")), "error_code": ""})
        compare_and_swap(ImageBuildJob, pk=job.pk, expected_version=job.row_version, changes={"status": ImageBuildJob.Status.SUCCEEDED, "logs_masked": _masked(result.get("logs", "")), "completed_at": timezone.now(), "error_code": ""})
        _event(image, events.IMAGE_PREPARED, trace_id, {"image_id": image.public_id, "digest": digest})
        return image
    except Exception as exc:
        code = getattr(exc, "code", "IMAGE_PREPARATION_FAILED")
        image = compare_and_swap(ExperimentImage, pk=image.pk, expected_version=image.row_version, changes={"status": ExperimentImage.Status.FAILED, "scan_status": ExperimentImage.ScanStatus.FAILED, "error_code": code, "logs_masked": ""})
        compare_and_swap(ImageBuildJob, pk=job.pk, expected_version=job.row_version, changes={"status": ImageBuildJob.Status.FAILED, "error_code": code, "completed_at": timezone.now()})
        append_failure(failure_type="EXPERIMENT_IMAGE", subject_type="EXPERIMENT_IMAGE", subject_ref=image.public_id, error_code=code, message=str(exc), detail={}, retryable=False, trace_id=trace_id)
        return image


def retire_experiment_image(*, image_id: str, context: Any) -> ExperimentImage:
    image = ExperimentImage.objects.get(public_id=image_id)
    return compare_and_swap(ExperimentImage, pk=image.pk, expected_version=image.row_version, changes={"status": ExperimentImage.Status.RETIRED})


def resolve_external_digest(
    *, image_id: str | None = None, runtime: ExperimentImageRuntime | None = None,
    registry: str = "", repository: str = "", tag: str = ""
) -> str:
    if image_id:
        return prepare_experiment_image(image_id=image_id).resolved_digest
    if runtime is None:
        raise ValueError("runtime or image_id is required")
    return str(runtime.resolve_image(registry=registry, repository=repository, tag=tag).get("digest", ""))


def validate_experiment_image(*, image_id: str) -> bool:
    image = ExperimentImage.objects.get(public_id=image_id)
    return image.status == ExperimentImage.Status.READY and bool(_DIGEST.fullmatch(image.resolved_digest))

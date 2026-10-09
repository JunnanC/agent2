import re
from collections.abc import Mapping
from typing import Any, Protocol

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.audit import append_audit, append_failure, hash_client_ip
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound
from apps.core.models import ObjectAsset
from apps.core.object_storage import object_storage
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.core.redaction import redact
from apps.courses.services import ActorContext
from apps.governance.models import ImageAsset, RuntimeAdapter
from apps.governance.services import create_image
from apps.provisioning.adapters import RuntimeAdapterFailure, runtime_for_driver

from . import events
from .errors import TemplateAssetNotReady, TemplateValidationError
from .models import ExperimentImage, ImageBuildJob, TemplateVersion


class ExperimentImageRuntime(Protocol):
    def build_image(
        self,
        *,
        registry: str,
        repository: str,
        tag: str,
        context: Mapping[str, Any],
        build_args: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...
    def resolve_image(self, *, registry: str, repository: str, tag: str) -> Mapping[str, Any]: ...
    def validate_image(self, *, digest: str) -> Mapping[str, Any]: ...


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SECRET_KEY = re.compile(
    r"(?i)(secret|token|password|passwd|credential|authorization|cookie|private|api[_-]?key)"
)
_SECRET_VALUE = re.compile(
    r"(?i)(secret|token|password|passwd|credential|authorization|cookie|"
    r"private[_ -]?key|api[_ -]?key)(\s*[=:]\s*)([^\s,;]+)"
)


def _masked(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else _masked(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_masked(item, secrets) for item in value]
    if isinstance(value, str):
        masked = str(redact(value))
        for secret in secrets:
            if secret:
                masked = masked.replace(secret, "[REDACTED]")
        return _SECRET_VALUE.sub(r"\1\2[REDACTED]", masked[:4000])
    return value


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
    missing = [
        name
        for name in ("build_image", "resolve_image", "validate_image")
        if not hasattr(runtime, name)
    ]
    if missing:
        raise RuntimeAdapterFailure("RUNTIME_IMAGE_LIFECYCLE_UNAVAILABLE", retryable=False)
    return runtime  # type: ignore[return-value]


def _build_context_archive(asset: ObjectAsset) -> bytes:
    stored = object_storage().open_object(
        bucket=asset.bucket, object_key=asset.object_key, version_id=asset.object_version
    )
    try:
        content = stored.body.read()
    finally:
        stored.body.close()
    return bytes(content)


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
    version = template_version or TemplateVersion.objects.get(
        public_id=template_version_id or version_id
    )
    asset = None
    if source_type == ExperimentImage.SourceType.BUILD_CONTEXT:
        asset = ObjectAsset.objects.filter(public_id=build_context_asset_id).first()
        if (
            asset is None
            or asset.owner_ref != version.public_id
            or asset.owner_type != "TEMPLATE_VERSION"
            or asset.purpose != "BUILD_CONTEXT"
        ):
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
        actor_ref=actor_ref,
        actor_portal=portal,
        actor_context={},
        action="experiment_image.create",
        target_type="experiment_image",
        target_ref=image.public_id,
        course_ref=version.template.course.public_id,
        result="SUCCEEDED",
        trace_id=trace_id,
        after={"source_type": source_type, "requested_tag": requested_tag},
        client_ip_hash=hash_client_ip(client_ip, salt=settings.AUDIT_IP_HASH_SALT),
        user_agent_summary=user_agent,
    )
    _event(
        image,
        events.IMAGE_CREATED,
        trace_id,
        {"image_id": image.public_id, "source_type": source_type},
    )
    return image


def _image_changes(image: ExperimentImage, changes: dict[str, Any]) -> ExperimentImage:
    digest = changes.get("resolved_digest")
    if image.resolved_digest and digest and digest != image.resolved_digest:
        raise RuntimeAdapterFailure("EXPERIMENT_IMAGE_DIGEST_IMMUTABLE", retryable=False)
    return compare_and_swap(
        ExperimentImage, pk=image.pk, expected_version=image.row_version, changes=changes
    )


@transaction.atomic
def prepare_experiment_image(
    *, image_id: str, trace_id: str = "", build_args: Mapping[str, Any] | None = None
) -> ExperimentImage:
    try:
        image = (
            ExperimentImage.objects.select_for_update()
            .select_related(
                "template_version__template",
                "template_version__runtime_adapter",
                "build_context_asset",
                "image_asset",
            )
            .get(public_id=image_id)
        )
    except ExperimentImage.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if image.status in (ExperimentImage.Status.READY, ExperimentImage.Status.RETIRED):
        return image
    if image.status == ExperimentImage.Status.PENDING_APPROVAL:
        if image.image_asset_id and image.image_asset.is_ready:
            return _image_changes(
                image,
                {
                    "status": ExperimentImage.Status.READY,
                    "scan_status": ExperimentImage.ScanStatus.CLEAN,
                },
            )
        return image
    running = ImageBuildJob.objects.filter(
        experiment_image=image, status=ImageBuildJob.Status.RUNNING
    ).first()
    if image.status == ExperimentImage.Status.PREPARING and running:
        return image
    trace_id = trace_id or image.trace_id
    image = _image_changes(image, {"status": ExperimentImage.Status.PREPARING})
    job = ImageBuildJob.objects.create(
        experiment_image=image,
        status=ImageBuildJob.Status.RUNNING,
        attempt_count=1,
        build_args_masked=image.build_args_masked,
        trace_id=trace_id,
        started_at=timezone.now(),
    )
    try:
        adapter = image.template_version.runtime_adapter
        runtime = _runtime(adapter)
        if image.source_type == ExperimentImage.SourceType.BUILD_CONTEXT:
            asset = image.build_context_asset
            if (
                asset is None
                or asset.owner_type != "TEMPLATE_VERSION"
                or asset.owner_ref != image.template_version.public_id
                or asset.purpose != "BUILD_CONTEXT"
                or asset.scan_status != ObjectAsset.ScanStatus.CLEAN
                or asset.status != ObjectAsset.Status.ACTIVE
            ):
                raise TemplateAssetNotReady(detail={"asset_id": getattr(asset, "public_id", "")})
            result = runtime.build_image(
                registry=image.registry,
                repository=image.repository,
                tag=image.requested_tag,
                context={
                    "archive": _build_context_archive(asset),
                    "bucket": asset.bucket,
                    "object_key": asset.object_key,
                    "object_version": asset.object_version,
                    "digest_sha256": asset.digest_sha256,
                },
                build_args=dict(build_args or {}),
            )
        else:
            result = runtime.resolve_image(
                registry=image.registry, repository=image.repository, tag=image.requested_tag
            )
        digest = str(result.get("digest", ""))
        if not _DIGEST.fullmatch(digest):
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_DIGEST_INVALID", retryable=False)
        validation = runtime.validate_image(digest=digest)
        if validation.get("valid", True) is False:
            raise RuntimeAdapterFailure("RUNTIME_IMAGE_VALIDATION_FAILED", retryable=False)
        governed = ImageAsset.objects.filter(digest=digest).first()
        if governed is None:
            actor_context = ActorContext(image.created_by.public_id, "TEACHING", trace_id)
            governed = create_image(
                actor=image.created_by,
                registry=image.registry,
                repository=image.repository,
                display_tag=image.requested_tag,
                digest=digest,
                risk_level=ImageAsset.RiskLevel.LOW,
                reason="experiment image preparation",
                context=actor_context,
            )
        if governed.is_ready:
            ready_status = ExperimentImage.Status.READY
            scan_status = ExperimentImage.ScanStatus.CLEAN
        else:
            ready_status = ExperimentImage.Status.PENDING_APPROVAL
            scan_status = ExperimentImage.ScanStatus.PENDING
        secrets = tuple(str(value) for value in (build_args or {}).values() if value is not None)
        image = _image_changes(
            image,
            {
                "resolved_digest": digest,
                "image_asset_id": governed.pk,
                "status": ready_status,
                "scan_status": scan_status,
                "validation_detail": _masked(dict(validation), secrets),
                "logs_masked": _masked(result.get("logs", ""), secrets),
                "error_code": "",
            },
        )
        compare_and_swap(
            ImageBuildJob,
            pk=job.pk,
            expected_version=job.row_version,
            changes={
                "status": ImageBuildJob.Status.SUCCEEDED,
                "logs_masked": _masked(result.get("logs", ""), secrets),
                "completed_at": timezone.now(),
                "error_code": "",
            },
        )
        _event(
            image,
            events.IMAGE_PREPARED,
            trace_id,
            {"image_id": image.public_id, "digest": digest, "status": image.status},
        )
        return image
    except Exception as exc:
        latest = ExperimentImage.objects.get(pk=image.pk)
        if latest.status == ExperimentImage.Status.READY:
            return latest
        code = getattr(exc, "code", "IMAGE_PREPARATION_FAILED")
        image = _image_changes(
            latest,
            {
                "status": ExperimentImage.Status.FAILED,
                "scan_status": ExperimentImage.ScanStatus.FAILED,
                "error_code": code,
                "logs_masked": "",
            },
        )
        compare_and_swap(
            ImageBuildJob,
            pk=job.pk,
            expected_version=job.row_version,
            changes={
                "status": ImageBuildJob.Status.FAILED,
                "error_code": code,
                "completed_at": timezone.now(),
            },
        )
        append_failure(
            failure_type="EXPERIMENT_IMAGE",
            subject_type="EXPERIMENT_IMAGE",
            subject_ref=image.public_id,
            error_code=code,
            message=str(exc),
            detail={},
            retryable=False,
            trace_id=trace_id,
        )
        return image


def retire_experiment_image(
    *, image_id: str, context: Any, expected_version: int
) -> ExperimentImage:
    try:
        image = (
            ExperimentImage.objects.select_for_update()
            .select_related("template_version__template")
            .get(public_id=image_id)
        )
    except ExperimentImage.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if image.status == ExperimentImage.Status.RETIRED and image.row_version == expected_version:
        return image
    changed = compare_and_swap(
        ExperimentImage,
        pk=image.pk,
        expected_version=expected_version,
        changes={"status": ExperimentImage.Status.RETIRED},
    )
    actor_ref, portal, trace_id, client_ip, user_agent = _context(context)
    append_audit(
        actor_ref=actor_ref,
        actor_portal=portal,
        actor_context={},
        action="experiment_image.retire",
        target_type="experiment_image",
        target_ref=image.public_id,
        course_ref=image.template_version.template.course.public_id,
        before={"status": image.status},
        after={"status": changed.status},
        result="SUCCEEDED",
        trace_id=trace_id,
        client_ip_hash=hash_client_ip(client_ip, salt=settings.AUDIT_IP_HASH_SALT),
        user_agent_summary=user_agent,
    )
    _event(
        changed,
        events.IMAGE_RETIRED,
        trace_id,
        {"image_id": changed.public_id, "status": changed.status},
    )
    return changed


def resolve_external_digest(
    *,
    image_id: str,
    runtime: ExperimentImageRuntime | None = None,
) -> str:
    image = ExperimentImage.objects.select_related(
        "template_version__runtime_adapter", "image_asset"
    ).get(public_id=image_id)
    if image.source_type != ExperimentImage.SourceType.EXTERNAL_REFERENCE:
        raise TemplateValidationError(detail={"source_type": "external_reference_required"})
    prepared = prepare_experiment_image(image_id=image_id)
    if not _DIGEST.fullmatch(prepared.resolved_digest):
        raise RuntimeAdapterFailure("RUNTIME_IMAGE_DIGEST_INVALID", retryable=False)
    if prepared.image_asset is None or not prepared.image_asset.is_ready:
        raise RuntimeAdapterFailure("IMAGE_GOVERNANCE_NOT_READY", retryable=False)
    return prepared.resolved_digest


def validate_experiment_image(*, image_id: str) -> bool:
    image = ExperimentImage.objects.get(public_id=image_id)
    if (
        image.status != ExperimentImage.Status.READY
        or not image.image_asset_id
        or not image.image_asset.is_ready
    ):
        return False
    return bool(_DIGEST.fullmatch(image.resolved_digest))

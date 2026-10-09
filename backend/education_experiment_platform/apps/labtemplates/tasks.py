from typing import Any

from celery import shared_task
from django.utils import timezone

from apps.core.audit import append_failure
from apps.core.concurrency import compare_and_swap

from .assets import fail_unavailable_asset, scan_and_attach_asset
from .image_services import prepare_experiment_image
from .models import ExperimentImage, TemplatePrecheckRun, TemplateVersion
from .services import execute_precheck


@shared_task(bind=True, max_retries=2, queue="q_provision", acks_late=True)
def run_template_precheck(self: Any, run_id: str) -> str:
    try:
        return execute_precheck(run_id=run_id).public_id
    except Exception as exc:
        run = TemplatePrecheckRun.objects.filter(public_id=run_id).first()
        if run is None:
            raise
        if self.request.retries < self.max_retries:
            compare_and_swap(
                TemplatePrecheckRun,
                pk=run.pk,
                expected_version=run.row_version,
                changes={
                    "status": TemplatePrecheckRun.Status.RETRY,
                    "retryable": True,
                    "error_code": "PRECHECK_WORKER_RETRY",
                },
            )
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
        append_failure(
            failure_type="TEMPLATE_PRECHECK",
            subject_type="TEMPLATE_VERSION",
            subject_ref=run.template_version.public_id,
            error_code="PRECHECK_WORKER_FAILED",
            message=str(exc),
            detail={"run_id": run.public_id},
            retryable=False,
            trace_id=run.trace_id,
        )
        compare_and_swap(
            TemplatePrecheckRun,
            pk=run.pk,
            expected_version=run.row_version,
            changes={
                "status": TemplatePrecheckRun.Status.FAILED,
                "retryable": False,
                "error_code": "PRECHECK_WORKER_FAILED",
                "completed_at": timezone.now(),
            },
        )
        version = TemplateVersion.objects.get(pk=run.template_version_id)
        if version.status == TemplateVersion.Status.PRECHECKING:
            compare_and_swap(
                TemplateVersion,
                pk=version.pk,
                expected_version=version.row_version,
                changes={"status": TemplateVersion.Status.PRECHECK_FAILED},
            )
        raise


@shared_task(bind=True, max_retries=2, queue="q_provision", acks_late=True)
def scan_template_asset(self: Any, asset_id: str, trace_id: str = "") -> str:
    from apps.core.models import ObjectAsset

    try:
        return scan_and_attach_asset(asset_id=asset_id, trace_id=trace_id).public_id
    except Exception as exc:
        asset = ObjectAsset.objects.filter(public_id=asset_id).first()
        if asset is None:
            raise
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
        append_failure(
            failure_type="TEMPLATE_ASSET_SCAN",
            subject_type="OBJECT_ASSET",
            subject_ref=asset.public_id,
            error_code="ASSET_SCAN_UNAVAILABLE",
            message="Template asset scan failed after retries",
            detail={},
            retryable=False,
            trace_id=trace_id,
        )
        fail_unavailable_asset(asset_id=asset.public_id, trace_id=trace_id)
        raise


@shared_task(bind=True, max_retries=2, queue="q_provision", acks_late=True)
def prepare_experiment_image_task(
    self: Any, image_id: str, trace_id: str = "", build_args: dict[str, Any] | None = None
) -> str:
    image = prepare_experiment_image(image_id=image_id, trace_id=trace_id, build_args=build_args)
    if image.status == ExperimentImage.Status.FAILED and self.request.retries < self.max_retries:
        raise self.retry(
            args=(image_id, trace_id, build_args),
            exc=RuntimeError(image.error_code),
            countdown=2**self.request.retries,
        )
    return image.public_id

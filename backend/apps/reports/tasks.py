from typing import Any

from celery import shared_task

from .assessment_review import review_word_report  # noqa: F401
from .services import fail_report_attachment_scan, scan_report_attachment


@shared_task(bind=True, max_retries=2, queue="q_provision", acks_late=True)
def scan_report_asset(self: Any, asset_id: str, trace_id: str = "") -> str:
    from apps.core.models import ObjectAsset

    try:
        return scan_report_attachment(asset_id=asset_id, trace_id=trace_id).public_id
    except Exception as exc:
        asset = ObjectAsset.objects.filter(public_id=asset_id).first()
        if asset is None:
            raise
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
        fail_report_attachment_scan(
            asset_id=asset.public_id,
            trace_id=trace_id,
            code="ASSET_SCAN_UNAVAILABLE",
        )
        raise

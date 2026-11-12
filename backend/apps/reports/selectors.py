
from apps.core.errors import ResourceNotFound
from apps.core.models import ObjectAsset


def visible_report_asset(*, asset_id: str) -> ObjectAsset:
    try:
        return ObjectAsset.objects.get(public_id=asset_id)
    except ObjectAsset.DoesNotExist as exc:
        raise ResourceNotFound() from exc

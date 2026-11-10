from django.db.models import F

from apps.accounts.models import User
from apps.core.errors import DownloadScopeDenied
from apps.core.models import ObjectAsset

from .models import Chapter, Enrollment, MaterialVersion


def authorize_course_material_download(asset: ObjectAsset, actor: User, portal: str) -> str:
    if portal != "USER" or asset.purpose not in {"MANUAL", "REPORT_TEMPLATE"}:
        raise DownloadScopeDenied()
    version = (
        MaterialVersion.objects.filter(
            object_asset=asset,
            status=MaterialVersion.Status.PUBLISHED,
            material__current_version_id=F("pk"),
            material__chapter__status=Chapter.Status.PUBLISHED,
            material__course__enrollments__student=actor,
            material__course__enrollments__status=Enrollment.Status.ACTIVE,
        )
        .select_related("material__course")
        .first()
    )
    if version is None:
        raise DownloadScopeDenied()
    return version.material.course.public_id

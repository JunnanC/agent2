from django.db.models import F

from apps.accounts.models import User
from apps.core.errors import DownloadScopeDenied
from apps.core.models import ObjectAsset

from .models import Chapter, Enrollment, MaterialVersion


def authorize_course_material_download(asset: ObjectAsset, actor: User, portal: str) -> str:
    if portal == "TEACHING" and asset.owner_type == "COURSE_ATTACHMENT":
        from apps.core.errors import ResourceNotFound

        from .models import Course
        from .selectors import require_course_capability

        try:
            course = Course.objects.get(public_id=asset.owner_ref)
        except Course.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        require_course_capability(course=course, actor=actor, capability="MANAGE_CONTENT")
        return course.public_id
    if portal != "USER" or asset.purpose not in {"MANUAL", "REPORT_TEMPLATE"}:
        raise DownloadScopeDenied()
    version = (
        MaterialVersion.objects
        .filter(
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

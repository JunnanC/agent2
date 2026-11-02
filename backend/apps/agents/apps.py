from django.apps import AppConfig


class AgentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.agents"

    def ready(self) -> None:
        from apps.accounts.models import User
        from apps.core.compensation import register_compensation_handler
        from apps.core.downloads import register_download_authorizer
        from apps.core.models import ObjectAsset
        from apps.courses.models import Enrollment, MaterialVersion
        from apps.courses.ports import register_course_copy_handler

        from .assets import delete_agent_source_asset_compensation
        from .models import AgentSourceVersion
        from .services import copy_agent_configuration

        register_compensation_handler(
            "DELETE_AGENT_SOURCE_ASSET", delete_agent_source_asset_compensation
        )
        register_course_copy_handler(copy_agent_configuration)

        def authorize_source(asset: ObjectAsset, actor: User, portal: str) -> str:
            if portal != "USER":
                from apps.core.errors import DownloadScopeDenied

                raise DownloadScopeDenied()
            try:
                if asset.owner_type == "AGENT_SOURCE_VERSION":
                    version = AgentSourceVersion.objects.select_related("source__course").get(
                        public_id=asset.owner_ref,
                        object_asset=asset,
                        status=AgentSourceVersion.Status.INDEXED,
                        source__status="ACTIVE",
                    )
                else:
                    version = AgentSourceVersion.objects.select_related("source__course").get(
                        object_asset=asset,
                        material_version__public_id=asset.owner_ref,
                        material_version__status=MaterialVersion.Status.PUBLISHED,
                        status=AgentSourceVersion.Status.INDEXED,
                        source__status="ACTIVE",
                    )
                enrollment = actor.enrollments.get(
                    course=version.source.course,
                    status="ACTIVE",
                )
            except (
                AgentSourceVersion.DoesNotExist,
                AgentSourceVersion.MultipleObjectsReturned,
                Enrollment.DoesNotExist,
            ) as exc:
                from apps.core.errors import DownloadScopeDenied

                raise DownloadScopeDenied() from exc
            return enrollment.course.public_id

        for owner_type in ("AGENT_SOURCE_VERSION", "MATERIAL_VERSION", "COURSE_MATERIAL"):
            register_download_authorizer(owner_type, authorize_source)

from django.apps import AppConfig


class CoursesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.courses"

    def ready(self) -> None:
        from apps.core.downloads import register_download_authorizer

        from .downloads import authorize_course_material_download

        register_download_authorizer("TEMPLATE_VERSION", authorize_course_material_download)

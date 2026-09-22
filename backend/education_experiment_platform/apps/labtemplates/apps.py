from django.apps import AppConfig


class LabTemplatesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.labtemplates"

    def ready(self) -> None:
        from apps.core.compensation import register_compensation_handler
        from apps.courses.ports import register_course_copy_handler

        from .assets import delete_template_asset_compensation
        from .services import copy_templates

        register_course_copy_handler(copy_templates)
        register_compensation_handler("DELETE_TEMPLATE_ASSET", delete_template_asset_compensation)

from django.apps import AppConfig


class ProvisioningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.provisioning"

    def ready(self) -> None:
        from apps.core.compensation import register_compensation_handler

        from .services import compensate_provisioning

        register_compensation_handler("COMPENSATE_PROVISIONING", compensate_provisioning)

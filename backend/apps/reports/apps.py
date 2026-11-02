from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reports"

    def ready(self) -> None:
        from apps.core.compensation import register_compensation_handler
        from apps.core.downloads import register_download_authorizer

        from .services import authorize_report_asset_download, delete_report_asset_compensation

        register_compensation_handler("DELETE_REPORT_ASSET", delete_report_asset_compensation)
        register_download_authorizer("REPORT_ATTACHMENT", authorize_report_asset_download)
        register_download_authorizer("WORKSPACE_TASK", authorize_report_asset_download)
        register_download_authorizer("WORKSPACE_EXECUTION", authorize_report_asset_download)

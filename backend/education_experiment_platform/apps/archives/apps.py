from django.apps import AppConfig


class ArchivesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.archives"

    def ready(self) -> None:
        from apps.core.compensation import register_compensation_handler
        from apps.core.downloads import (
            register_download_authorizer,
            register_download_grant_observer,
        )
        from apps.courses.ports import (
            register_course_archive_blocker,
            register_course_closed_handler,
        )
        from apps.experiments.ports import register_task_terminal_handler

        from .services import (
            archive_course_blockers,
            authorize_archive_download,
            record_archive_export,
            request_task_archive,
            retry_archive_compensation,
            retry_judge_destroy_compensation,
            retry_runtime_cleanup_compensation,
            retry_runtime_object_purge_compensation,
            retry_runtime_resource_destroy_compensation,
            schedule_course_reconciliation,
        )

        register_compensation_handler("RETRY_ARCHIVE_JOB", retry_archive_compensation)
        register_compensation_handler("RETRY_RUNTIME_DESTROY", retry_runtime_cleanup_compensation)
        register_compensation_handler("RETRY_JUDGE_DESTROY", retry_judge_destroy_compensation)
        register_compensation_handler(
            "RETRY_RUNTIME_OBJECT_PURGE", retry_runtime_object_purge_compensation
        )
        register_compensation_handler(
            "RETRY_RUNTIME_RESOURCE_DESTROY", retry_runtime_resource_destroy_compensation
        )
        register_download_authorizer("ARCHIVE_PACKAGE", authorize_archive_download)
        register_download_grant_observer(record_archive_export)
        register_course_archive_blocker(archive_course_blockers)
        register_course_closed_handler(schedule_course_reconciliation)
        register_task_terminal_handler(request_task_archive)

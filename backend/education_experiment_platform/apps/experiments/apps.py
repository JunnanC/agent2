from django.apps import AppConfig


class ExperimentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.experiments"

    def ready(self) -> None:
        from apps.core.compensation import register_compensation_handler
        from apps.courses.ports import (
            register_enrollment_activation_handler,
            register_enrollment_blocker,
        )

        from .services import (
            assign_late_enrollment,
            enrollment_task_blockers,
            retry_publication_assignment_compensation,
        )

        register_enrollment_activation_handler(assign_late_enrollment)
        register_enrollment_blocker(enrollment_task_blockers)
        register_compensation_handler(
            "RETRY_EXPERIMENT_PUBLICATION",
            retry_publication_assignment_compensation,
        )

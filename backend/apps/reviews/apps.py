from django.apps import AppConfig


class ReviewsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reviews"

    def ready(self) -> None:
        from apps.courses.ports import register_course_copy_handler

        from .services import copy_rubrics

        register_course_copy_handler(copy_rubrics)

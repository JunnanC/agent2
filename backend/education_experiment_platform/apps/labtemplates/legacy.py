from dataclasses import dataclass
from typing import Any

from .models import TemplateChapter, TemplateVersion


@dataclass(frozen=True)
class LegacyTemplateAdapter:
    template_version_id: str
    chapters: tuple[dict[str, Any], ...]
    migration_required: bool = False
    migration_code: str = ""

    @classmethod
    def from_version(cls, version: TemplateVersion) -> LegacyTemplateAdapter:
        chapters = list(
            version.chapters.prefetch_related("tasks").order_by("sort_order", "id")
        )
        if chapters:
            return cls(
                template_version_id=version.public_id,
                chapters=tuple(cls._chapter_data(chapter) for chapter in chapters),
            )
        image = getattr(version, "image", None)
        if image is None or not str(image.digest or "").startswith("sha256:"):
            return cls(
                template_version_id=version.public_id,
                chapters=(),
                migration_required=True,
                migration_code="MIGRATION_REQUIRED",
            )
        return cls(
            template_version_id=version.public_id,
            chapters=(
                {
                    "public_id": f"legacy:{version.public_id}:chapter",
                    "title": "实验内容",
                    "description": version.template.description,
                    "sort_order": 1,
                    "status": (
                        "PUBLISHED"
                        if version.status == TemplateVersion.Status.PUBLISHED
                        else "DRAFT"
                    ),
                    "tasks": (
                        {
                            "public_id": f"legacy:{version.public_id}:task",
                            "title": "实验任务",
                            "description": version.template.description,
                            "instructions": "按照实验说明完成任务。",
                            "task_type": "PRACTICE",
                            "sort_order": 1,
                            "status": (
                                "PUBLISHED"
                                if version.status == TemplateVersion.Status.PUBLISHED
                                else "DRAFT"
                            ),
                            "execution_spec": dict(version.execution_spec or {}),
                        },
                    ),
                },
            ),
        )

    @staticmethod
    def _chapter_data(chapter: TemplateChapter) -> dict[str, Any]:
        return {
            "public_id": chapter.public_id,
            "title": chapter.title,
            "description": chapter.description,
            "learning_objectives": list(chapter.learning_objectives or []),
            "sort_order": chapter.sort_order,
            "status": chapter.status,
            "tasks": tuple(
                {
                    "public_id": task.public_id,
                    "title": task.title,
                    "description": task.description,
                    "instructions": task.instructions,
                    "task_type": task.task_type,
                    "sort_order": task.sort_order,
                    "status": task.status,
                    "execution_spec": dict(task.execution_spec or {}),
                }
                for task in chapter.tasks.all().order_by("sort_order", "id")
            ),
        }

import hashlib
import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.courses.models import Course, MaterialVersion

from ...models import (
    AgentDefinition,
    AgentSession,
    AgentSource,
    AgentSourceVersion,
    CourseAgentProfile,
    KnowledgeBase,
    ModelRoute,
    ToolPolicy,
)


class Command(BaseCommand):
    help = "Create disposable P12 Agent configuration for the existing integration course."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("P12 E2E seed is restricted to disposable environments")
        course = Course.objects.filter(code="P03-DEMO-001").first()
        teacher = User.objects.filter(email="teacher.integration@example.edu").first()
        if course is None or teacher is None:
            raise CommandError("Run the P02-P11 seeds before seed_p12_e2e")
        route = self._route()
        definition, _ = AgentDefinition.objects.get_or_create(
            key="course-agent",
            version_no=1,
            defaults={
                "model_route": route.public_id,
                "mode": "COURSE_AGENT",
                "safety_config": {"platform_baseline": True},
            },
        )
        policy, _ = ToolPolicy.objects.get_or_create(
            key="p12-workspace-draft",
            version_no=1,
            defaults={
                "tool_name": "workspace_draft",
                "risk": ToolPolicy.Risk.HIGH,
                "allowlist": ["workspace_draft"],
                "schema": {"type": "object", "additionalProperties": True},
                "status": ToolPolicy.Status.ACTIVE,
            },
        )
        knowledge = KnowledgeBase.objects.filter(
            course=course, name="P12 Integration Knowledge"
        ).first()
        if knowledge is None:
            knowledge = KnowledgeBase.objects.create(
                course=course,
                name="P12 Integration Knowledge",
                description="Disposable local P12 seed",
                status=KnowledgeBase.Status.ACTIVE,
            )
        material = MaterialVersion.objects.filter(
            material__course=course,
            status=MaterialVersion.Status.PUBLISHED,
        ).select_related("material").order_by("id").first()
        if material is not None:
            source, _ = AgentSource.objects.get_or_create(
                knowledge_base=knowledge,
                title="P12 published course material",
                defaults={
                    "course": course,
                    "source_type": AgentSource.SourceType.COURSE_MATERIAL,
                    "material_version": material,
                    "audience": {"course_id": course.public_id},
                    "status": AgentSource.Status.ACTIVE,
                },
            )
            digest = material.digest_sha256 or hashlib.sha256(
                material.text_content.encode("utf-8")
            ).hexdigest()
            AgentSourceVersion.objects.get_or_create(
                source=source,
                version_no=1,
                defaults={
                    "digest_sha256": digest,
                    "material_version": material,
                    "audience": {"course_id": course.public_id},
                    "status": AgentSourceVersion.Status.INDEXED,
                },
            )
        profile = CourseAgentProfile.objects.filter(course=course, version_no=1).first()
        if profile is None:
            profile = CourseAgentProfile.objects.create(
                course=course,
                definition=definition,
                version_no=1,
                status=CourseAgentProfile.Status.ACTIVE,
                modes=list(AgentSession.Mode.values),
                knowledge_base=knowledge,
                tool_policy=policy,
                model_route=route.public_id,
                budget={
                    "max_tokens": 2048,
                    "daily_tokens": 100000,
                    "requests_per_minute": 30,
                    "daily_tool_calls": 100,
                    "daily_cost_minor": 100000,
                },
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"P12 E2E facts ready: course={course.public_id} profile={profile.public_id} "
                f"route={route.public_id} trace={secrets.token_hex(8)}"
            )
        )

    @staticmethod
    def _route() -> ModelRoute:
        route = ModelRoute.objects.filter(key="local-rule-based", version_no=1).first()
        if route is not None:
            return route
        return ModelRoute.objects.create(
            key="local-rule-based",
            version_no=1,
            provider="LOCAL",
            model_name="rule-based",
            regions=["LOCAL"],
            timeout_seconds=5,
            max_tokens=4096,
        )

import os
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.courses.models import Course
from apps.governance.models import (
    ImageAsset,
    NetworkAllowlist,
    Quota,
    RuntimeAdapter,
    SecurityPolicy,
)


class Command(BaseCommand):
    help = "Create disposable P04 data for local browser and integration verification."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("P04 E2E seed is restricted to disposable environments")
        admin = User.objects.filter(email="admin.integration@example.edu").first()
        student = User.objects.filter(email="student.integration@example.edu").first()
        course = Course.objects.filter(code="P03-DEMO-001").first()
        if admin is None or student is None or course is None:
            raise CommandError("Run seed_p02_e2e and seed_p03_e2e first")
        Quota.objects.get_or_create(
            scope_key="PLATFORM",
            defaults={
                "scope_type": "PLATFORM",
                "max_concurrent_instances": 50,
                "max_concurrent_starts": 20,
                "max_cpu_millicores": 100000,
                "max_memory_mb": 204800,
                "max_disk_gb": 2000,
                "max_object_storage_bytes": 1_000_000_000_000,
                "max_agent_tokens_per_day": 10_000_000,
                "max_agent_requests_per_minute": 1000,
                "updated_by": admin,
                "change_reason": "P04 disposable seed",
            },
        )
        Quota.objects.get_or_create(
            scope_key=f"COURSE:{course.public_id}",
            defaults={
                "scope_type": "COURSE",
                "course": course,
                "max_concurrent_instances": 10,
                "max_concurrent_starts": 5,
                "max_cpu_millicores": 20000,
                "max_memory_mb": 40960,
                "max_disk_gb": 200,
                "max_object_storage_bytes": 100_000_000_000,
                "max_agent_tokens_per_day": 1_000_000,
                "max_agent_requests_per_minute": 100,
                "updated_by": admin,
                "change_reason": "P04 disposable seed",
            },
        )
        Quota.objects.get_or_create(
            scope_key=f"USER:{student.public_id}",
            defaults={
                "scope_type": "USER",
                "user": student,
                "max_concurrent_instances": 2,
                "max_concurrent_starts": 1,
                "max_cpu_millicores": 4000,
                "max_memory_mb": 8192,
                "max_disk_gb": 40,
                "max_object_storage_bytes": 10_000_000_000,
                "max_agent_tokens_per_day": 100_000,
                "max_agent_requests_per_minute": 20,
                "updated_by": admin,
                "change_reason": "P04 disposable seed",
            },
        )
        RuntimeAdapter.objects.get_or_create(
            code="LOCAL-SWARM",
            defaults={
                "name": "本地 Swarm 目录项",
                "runtime_type": "CONTAINER",
                "driver": "DOCKER_SWARM",
                "status": "DISABLED",
                "config_ref": "runtime/local-swarm",
                "change_reason": "P04 disposable seed",
            },
        )
        RuntimeAdapter.objects.get_or_create(
            code="LOCAL-DOCKER",
            defaults={
                "name": "本地 Docker 算法运行时治理项",
                "runtime_type": RuntimeAdapter.RuntimeType.CONTAINER,
                "driver": RuntimeAdapter.Driver.DOCKER_LOCAL,
                "status": RuntimeAdapter.Status.DISABLED,
                "config_ref": "runtime/local-docker",
                "change_reason": "P04 disposable seed",
            },
        )
        ImageAsset.objects.get_or_create(
            digest=f"sha256:{'a' * 64}",
            defaults={
                "registry": "registry.local",
                "repository": "edu/python-lab",
                "display_tag": "3.13",
                "scan_status": "CLEAN",
                "approval_status": "APPROVED",
                "risk_level": "LOW",
                "scan_report_ref": "scan/p04-e2e",
                "scanned_at": timezone.now(),
                "approved_by": admin,
                "approved_at": timezone.now(),
                "change_reason": "P04 disposable seed",
            },
        )
        SecurityPolicy.objects.get_or_create(
            policy_kind="RESOURCE_SCALING",
            scope_key=f"COURSE:{course.public_id}",
            defaults={
                "scope_type": "COURSE",
                "course": course,
                "risk_level": "MEDIUM",
                "rules": {
                    "prewarm_enabled": True,
                    "prewarm_lead_minutes": 30,
                    "min_replicas": 0,
                    "max_replicas": 3,
                    "cooldown_seconds": 300,
                    "idle_reclaim_seconds": 1800,
                    "budget_minor": 10000,
                    "currency_code": "CNY",
                    "max_course_concurrency": 10,
                },
                "updated_by": admin,
                "change_reason": "P04 disposable seed",
            },
        )
        NetworkAllowlist.objects.get_or_create(
            scope_key="PLATFORM",
            target_type="HOST",
            target_value="pypi.org",
            protocol="TCP",
            port_start=443,
            port_end=443,
            defaults={
                "scope_type": "PLATFORM",
                "risk_level": "LOW",
                "status": "ACTIVE",
                "approved_by": admin,
                "approved_at": timezone.now() - timedelta(seconds=1),
                "change_reason": "P04 disposable seed",
            },
        )
        self.stdout.write(self.style.SUCCESS("P04 disposable governance data ready"))

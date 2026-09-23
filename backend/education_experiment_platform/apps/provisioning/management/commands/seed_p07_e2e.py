import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.core.concurrency import compare_and_swap
from apps.courses.models import Course
from apps.governance.models import Quota, RuntimeAdapter
from apps.labtemplates.models import TemplateVersion


class Command(BaseCommand):
    help = (
        "Prepare disposable P07 FakeRuntime, quotas, and provisioning facts "
        "for local verification."
    )

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("P07 E2E seed is restricted to disposable environments")
        teacher = User.objects.filter(email="teacher.integration@example.edu").first()
        student = User.objects.filter(email="student.integration@example.edu").first()
        course = Course.objects.filter(code="P03-DEMO-001").first()
        if teacher is None or student is None or course is None:
            raise CommandError("Run seed_p02_e2e through seed_p06_e2e first")
        template_version = (
            TemplateVersion.objects.filter(template__course=course)
            .select_related("runtime_adapter")
            .order_by("-version_no")
            .first()
        )
        if template_version is None:
            raise CommandError("P05/P06 template version is missing")
        trace_id = secrets.token_hex(16)
        fake = self._fake_adapter()
        if template_version.runtime_adapter_id != fake.pk:
            compare_and_swap(
                TemplateVersion,
                pk=template_version.pk,
                expected_version=template_version.row_version,
                changes={"runtime_adapter": fake},
            )
        self._quota(
            scope_type=Quota.ScopeType.PLATFORM,
            scope_key="PLATFORM",
            values={
                "max_concurrent_instances": 100,
                "max_concurrent_starts": 100,
                "max_cpu_millicores": 200000,
                "max_memory_mb": 400000,
                "max_disk_gb": 2000,
            },
        )
        self._quota(
            scope_type=Quota.ScopeType.COURSE,
            scope_key=f"COURSE:{course.public_id}",
            course=course,
            values={"max_concurrent_instances": 100, "max_concurrent_starts": 100},
        )
        self._quota(
            scope_type=Quota.ScopeType.USER,
            scope_key=f"USER:{student.public_id}",
            user=student,
            values={"max_concurrent_instances": 10, "max_concurrent_starts": 10},
        )
        self.stdout.write(
            self.style.SUCCESS(
                "P07 E2E data ready: "
                f"course={course.public_id} fake_runtime={fake.public_id} "
                f"template_version={template_version.public_id} trace={trace_id}"
            )
        )

    @staticmethod
    def _fake_adapter() -> RuntimeAdapter:
        adapter = RuntimeAdapter.objects.filter(code="FAKE-LOCAL-P07").first()
        if adapter is not None:
            return adapter
        return RuntimeAdapter.objects.create(
            code="FAKE-LOCAL-P07",
            name="P07 Local FakeRuntime",
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            driver=RuntimeAdapter.Driver.FAKE,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
            node_count=1,
            capacity_cpu_millicores=200000,
            available_cpu_millicores=200000,
            capacity_memory_mb=400000,
            available_memory_mb=400000,
            config_ref="local-fake-runtime",
            last_health_at=timezone.now(),
            change_reason="P07 disposable local seed",
        )

    @staticmethod
    def _quota(
        *, scope_type: str, scope_key: str, values: dict[str, int], **targets: object
    ) -> None:
        quota = Quota.objects.filter(scope_key=scope_key).first()
        if quota is None:
            Quota.objects.create(
                scope_type=scope_type,
                scope_key=scope_key,
                change_reason="P07 disposable local seed",
                **targets,
                **values,
            )
            return
        changes = {key: value for key, value in values.items() if getattr(quota, key) != value}
        if changes:
            compare_and_swap(
                Quota, pk=quota.pk, expected_version=quota.row_version, changes=changes
            )

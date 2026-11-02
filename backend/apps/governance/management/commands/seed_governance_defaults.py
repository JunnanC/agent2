from django.core.management.base import BaseCommand

from apps.governance.models import ResourceProfile, SecurityPolicy


class Command(BaseCommand):
    help = "Create idempotent system-required governance defaults."

    def handle(self, *args: object, **options: object) -> None:
        profile, _ = ResourceProfile.objects.get_or_create(
            code="STANDARD-2C-4G-20G",
            defaults={
                "name": "标准容器规格",
                "runtime_type": "CONTAINER",
                "status": "ACTIVE",
                "cpu_millicores": 2000,
                "memory_mb": 4096,
                "disk_gb": 20,
                "network_mode": "DENY_ALL",
                "cost_minor_per_hour": 0,
                "currency_code": "CNY",
                "change_reason": "system default",
            },
        )
        policy, _ = SecurityPolicy.objects.get_or_create(
            policy_kind=SecurityPolicy.PolicyKind.RUNTIME_SECURITY,
            scope_key="PLATFORM",
            defaults={
                "scope_type": SecurityPolicy.ScopeType.PLATFORM,
                "risk_level": SecurityPolicy.RiskLevel.HIGH,
                "rules": {
                    "default_egress": "DENY_ALL",
                    "allow_privileged": False,
                    "require_workspace_gateway": True,
                },
                "change_reason": "system default",
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Governance defaults ready: profile={profile.public_id}, policy={policy.public_id}"
            )
        )

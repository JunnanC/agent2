"""登记服务器运行时环境：Docker（本机）与 Docker 集群。

服务器部署时执行一次，之后运维在管理端查看健康与容量：

    python manage.py configure_runtime_adapters --admin <平台管理员账号>
    python manage.py configure_runtime_adapters --admin <账号> --enable-swarm

默认只启用本机 Docker；Docker 集群适配器会登记但保持停用，直到集群判题驱动实现。
"""

from __future__ import annotations

import secrets
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import PlatformAdminAssignment, User
from apps.accounts.services import ActorContext
from apps.governance.models import RuntimeAdapter
from apps.governance.services import create_runtime_adapter, update_runtime_adapter


class Command(BaseCommand):
    help = "Register runtime adapters for local Docker and Docker Swarm."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--admin",
            default="",
            help="平台管理员用户名；默认取第一个启用的平台管理员",
        )
        parser.add_argument(
            "--enable-swarm",
            action="store_true",
            help="同时启用 Docker 集群适配器（需集群判题驱动已实现）",
        )
        parser.add_argument(
            "--local-code",
            default="DOCKER-LOCAL",
            help="本机 Docker 适配器编码，默认 DOCKER-LOCAL",
        )
        parser.add_argument(
            "--swarm-code",
            default="DOCKER-SWARM",
            help="Docker 集群适配器编码，默认 DOCKER-SWARM",
        )
        parser.add_argument("--reason", default="服务器运行时环境登记", help="变更原因")

    def handle(self, *args: object, **options: Any) -> None:
        admin = self._platform_admin(str(options["admin"]))
        context = ActorContext(
            actor_ref=admin.public_id,
            portal="PLATFORM",
            trace_id=secrets.token_hex(16),
        )
        reason = str(options["reason"]).strip() or "服务器运行时环境登记"
        specs = (
            {
                "code": str(options["local_code"]),
                "config_ref": settings.RUNTIME_ADAPTER_CODE,
                "name": "Docker",
                "driver": RuntimeAdapter.Driver.DOCKER_LOCAL,
                "status": RuntimeAdapter.Status.ENABLED,
            },
            {
                "code": str(options["swarm_code"]),
                "config_ref": "runtime/swarm",
                "name": "Docker 集群",
                "driver": RuntimeAdapter.Driver.DOCKER_SWARM,
                "status": (
                    RuntimeAdapter.Status.ENABLED
                    if options["enable_swarm"]
                    else RuntimeAdapter.Status.DISABLED
                ),
            },
        )
        for spec in specs:
            self._ensure(admin=admin, context=context, spec=spec, reason=reason)
        if not options["enable_swarm"]:
            self.stdout.write(
                "Docker 集群适配器已登记但保持停用：集群判题驱动尚未实现，"
                "实现后再用 --enable-swarm 启用。"
            )

    def _platform_admin(self, username: str) -> User:
        if username:
            admin = User.objects.filter(username=username).first()
            if admin is None:
                raise CommandError(f"平台管理员账号不存在：{username}")
            if not PlatformAdminAssignment.objects.filter(
                user=admin, status=PlatformAdminAssignment.Status.ACTIVE
            ).exists():
                raise CommandError(f"{username} 不是启用的平台管理员")
            return admin
        assignment = (
            PlatformAdminAssignment.objects.filter(
                status=PlatformAdminAssignment.Status.ACTIVE
            )
            .select_related("user")
            .order_by("created_at")
            .first()
        )
        if assignment is None:
            raise CommandError("没有启用的平台管理员，请先执行 bootstrap_platform_admin")
        return assignment.user

    def _ensure(
        self, *, admin: User, context: ActorContext, spec: dict[str, str], reason: str
    ) -> None:
        code = spec["code"].strip().upper()
        adapter = RuntimeAdapter.objects.filter(code=code).first()
        if adapter is None:
            # 已有环境可能用别的编码登记过同一运行时：优先复用，避免出现重复适配器。
            adapter = (
                RuntimeAdapter.objects.filter(
                    driver=spec["driver"],
                    runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
                    config_ref=spec["config_ref"],
                )
                .order_by("code")
                .first()
            )
        if adapter is None:
            adapter = create_runtime_adapter(
                actor=admin,
                code=code,
                name=spec["name"],
                runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
                driver=spec["driver"],
                config_ref=spec["config_ref"],
                reason=reason,
                context=context,
            )
            self.stdout.write(f"created {adapter.code} ({adapter.driver})")
        changes: dict[str, str] = {}
        if adapter.name != spec["name"]:
            changes["name"] = spec["name"]
        if adapter.config_ref != spec["config_ref"]:
            changes["config_ref"] = spec["config_ref"]
        if adapter.status != spec["status"]:
            changes["status"] = spec["status"]
        if changes:
            adapter = update_runtime_adapter(
                adapter_id=adapter.public_id,
                actor=admin,
                expected_version=adapter.row_version,
                changes=changes,
                reason=reason,
                context=context,
            )
            self.stdout.write(f"updated {adapter.code}: {', '.join(sorted(changes))}")
        self.stdout.write(
            self.style.SUCCESS(f"{adapter.code} {adapter.driver} {adapter.status}")
        )

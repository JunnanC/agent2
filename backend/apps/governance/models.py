from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import VersionedModel
from apps.courses.models import Course


class GovernanceModel(VersionedModel):
    public_id = models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )

    class Meta:
        abstract = True


class RuntimeAdapter(GovernanceModel):
    class RuntimeType(models.TextChoices):
        CONTAINER = "CONTAINER"
        VM = "VM"

    class Driver(models.TextChoices):
        DOCKER_SWARM = "DOCKER_SWARM"
        DOCKER_LOCAL = "DOCKER_LOCAL"
        LIBVIRT = "LIBVIRT"

    class Status(models.TextChoices):
        ENABLED = "ENABLED"
        DISABLED = "DISABLED"

    class HealthStatus(models.TextChoices):
        UNKNOWN = "UNKNOWN"
        HEALTHY = "HEALTHY"
        DEGRADED = "DEGRADED"
        UNAVAILABLE = "UNAVAILABLE"

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    runtime_type = models.CharField(max_length=16, choices=RuntimeType.choices)
    driver = models.CharField(max_length=32, choices=Driver.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DISABLED)
    config_ref = models.CharField(max_length=128, blank=True, default="")
    health_status = models.CharField(
        max_length=16,
        choices=HealthStatus.choices,
        default=HealthStatus.UNKNOWN,
    )
    node_count = models.PositiveIntegerField(default=0)
    capacity_cpu_millicores = models.PositiveBigIntegerField(default=0)
    available_cpu_millicores = models.PositiveBigIntegerField(default=0)
    capacity_memory_mb = models.PositiveBigIntegerField(default=0)
    available_memory_mb = models.PositiveBigIntegerField(default=0)
    budget_cpu_millicores = models.PositiveBigIntegerField(default=0)
    budget_memory_mb = models.PositiveBigIntegerField(default=0)
    last_health_at = models.DateTimeField(null=True, blank=True)
    health_detail = models.JSONField(default=dict)
    change_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "governance_runtime_adapter"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(runtime_type__in=("CONTAINER", "VM")),
                name="gov_runtime_type_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    driver__in=("DOCKER_SWARM", "DOCKER_LOCAL", "LIBVIRT")
                ),
                name="gov_runtime_driver_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(driver="DOCKER_LOCAL", runtime_type="CONTAINER")
                | ~models.Q(driver="DOCKER_LOCAL"),
                name="gov_runtime_local_container_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(driver="DOCKER_LOCAL", config_ref__gt="")
                | ~models.Q(driver="DOCKER_LOCAL"),
                name="gov_runtime_local_config_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ENABLED", "DISABLED")),
                name="gov_runtime_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    health_status__in=("UNKNOWN", "HEALTHY", "DEGRADED", "UNAVAILABLE")
                ),
                name="gov_runtime_health_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    available_cpu_millicores__lte=models.F("capacity_cpu_millicores")
                ),
                name="gov_runtime_cpu_capacity_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(available_memory_mb__lte=models.F("capacity_memory_mb")),
                name="gov_runtime_mem_capacity_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "health_status"), name="gov_runtime_health_idx"),
            models.Index(fields=("runtime_type", "status"), name="gov_runtime_type_idx"),
        ]


class ImageAsset(GovernanceModel):
    class ScanStatus(models.TextChoices):
        PENDING = "PENDING"
        CLEAN = "CLEAN"
        INFECTED = "INFECTED"
        FAILED = "FAILED"

    class ApprovalStatus(models.TextChoices):
        PENDING = "PENDING"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
        RETIRED = "RETIRED"

    class RiskLevel(models.TextChoices):
        LOW = "LOW"
        MEDIUM = "MEDIUM"
        HIGH = "HIGH"

    @property
    def is_ready(self) -> bool:
        return (
            self.scan_status == self.ScanStatus.CLEAN
            and self.approval_status == self.ApprovalStatus.APPROVED
            and bool(self.digest)
        )

    registry = models.CharField(max_length=255)
    repository = models.CharField(max_length=255)
    display_name = models.CharField(max_length=120, blank=True, default="")
    display_tag = models.CharField(max_length=128, blank=True, default="")
    digest = models.CharField(
        max_length=71,
        unique=True,
        db_collation="ascii_bin",
        null=True,
        blank=True,
    )
    scan_status = models.CharField(
        max_length=16,
        choices=ScanStatus.choices,
        default=ScanStatus.PENDING,
    )
    approval_status = models.CharField(
        max_length=16,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    risk_level = models.CharField(max_length=16, choices=RiskLevel.choices)
    scan_report_ref = models.CharField(max_length=128, blank=True, default="")
    scanned_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_runtime_images",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    change_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "governance_image_asset"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(scan_status__in=("PENDING", "CLEAN", "INFECTED", "FAILED")),
                name="gov_image_scan_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    approval_status__in=("PENDING", "APPROVED", "REJECTED", "RETIRED")
                ),
                name="gov_image_approval_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(risk_level__in=("LOW", "MEDIUM", "HIGH")),
                name="gov_image_risk_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("approval_status", "scan_status"), name="gov_image_state_idx"),
            models.Index(fields=("repository", "display_tag"), name="gov_image_display_idx"),
        ]


class ResourceProfile(GovernanceModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        ACTIVE = "ACTIVE"
        RETIRED = "RETIRED"

    class NetworkMode(models.TextChoices):
        DENY_ALL = "DENY_ALL"
        ALLOWLIST = "ALLOWLIST"

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    runtime_type = models.CharField(max_length=16, choices=RuntimeAdapter.RuntimeType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    cpu_millicores = models.PositiveIntegerField()
    memory_mb = models.PositiveIntegerField()
    cpu_request_millicores = models.PositiveIntegerField()
    cpu_limit_millicores = models.PositiveIntegerField()
    memory_request_mb = models.PositiveIntegerField()
    memory_limit_mb = models.PositiveIntegerField()
    disk_gb = models.PositiveIntegerField()
    network_mode = models.CharField(max_length=16, choices=NetworkMode.choices)
    cost_minor_per_hour = models.PositiveBigIntegerField(default=0)
    currency_code = models.CharField(max_length=3, default="CNY")
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    change_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "governance_resource_profile"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cpu_millicores__gt=0), name="gov_profile_cpu_ck"
            ),
            models.CheckConstraint(condition=models.Q(memory_mb__gt=0), name="gov_profile_mem_ck"),
            models.CheckConstraint(
                condition=models.Q(cpu_request_millicores__gt=0)
                & models.Q(cpu_limit_millicores__gte=models.F("cpu_request_millicores")),
                name="gov_profile_cpu_request_limit_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(memory_request_mb__gt=0)
                & models.Q(memory_limit_mb__gte=models.F("memory_request_mb")),
                name="gov_profile_memory_request_limit_ck",
            ),
            models.CheckConstraint(condition=models.Q(disk_gb__gt=0), name="gov_profile_disk_ck"),
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "ACTIVE", "RETIRED")),
                name="gov_profile_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(network_mode__in=("DENY_ALL", "ALLOWLIST")),
                name="gov_profile_network_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("runtime_type", "status"), name="gov_profile_runtime_idx"),
        ]


class Quota(GovernanceModel):
    class ScopeType(models.TextChoices):
        PLATFORM = "PLATFORM"
        COURSE = "COURSE"
        USER = "USER"

    scope_type = models.CharField(max_length=16, choices=ScopeType.choices)
    scope_key = models.CharField(max_length=64, unique=True, db_collation="ascii_bin")
    course = models.OneToOneField(
        Course,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="governance_quota",
    )
    user = models.OneToOneField(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="governance_quota",
    )
    max_concurrent_instances = models.PositiveIntegerField(null=True, blank=True)
    max_concurrent_starts = models.PositiveIntegerField(null=True, blank=True)
    max_cpu_millicores = models.PositiveBigIntegerField(null=True, blank=True)
    max_memory_mb = models.PositiveBigIntegerField(null=True, blank=True)
    max_disk_gb = models.PositiveBigIntegerField(null=True, blank=True)
    max_object_storage_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    max_agent_tokens_per_day = models.PositiveBigIntegerField(null=True, blank=True)
    max_agent_requests_per_minute = models.PositiveIntegerField(null=True, blank=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_governance_quotas",
    )
    change_reason = models.CharField(max_length=500)

    class Meta:
        db_table = "governance_quota"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(scope_type="PLATFORM", course__isnull=True, user__isnull=True)
                    | models.Q(scope_type="COURSE", course__isnull=False, user__isnull=True)
                    | models.Q(scope_type="USER", course__isnull=True, user__isnull=False)
                ),
                name="gov_quota_scope_target_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(max_concurrent_instances__isnull=True)
                    | models.Q(max_concurrent_instances__gt=0)
                ),
                name="gov_quota_instances_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(max_concurrent_starts__isnull=True)
                    | models.Q(max_concurrent_starts__gt=0)
                ),
                name="gov_quota_starts_ck",
            ),
        ]
        indexes = [models.Index(fields=("scope_type", "updated_at"), name="gov_quota_scope_idx")]


class QuotaReservation(GovernanceModel):
    class ReservationType(models.TextChoices):
        STANDARD = "STANDARD"
        PREWARM = "PREWARM"
        SCALING = "SCALING"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        RELEASED = "RELEASED"
        EXPIRED = "EXPIRED"

    reservation_key = models.CharField(max_length=128, unique=True, db_collation="ascii_bin")
    reservation_type = models.CharField(max_length=16, choices=ReservationType.choices)
    subject_type = models.CharField(max_length=32)
    subject_ref = models.CharField(max_length=128, db_collation="ascii_bin")
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quota_reservations",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quota_reservations",
    )
    resource_profile = models.ForeignKey(
        ResourceProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quota_reservations",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    instance_count = models.PositiveIntegerField(default=1)
    start_count = models.PositiveIntegerField(default=0)
    cpu_millicores = models.PositiveBigIntegerField(default=0)
    memory_mb = models.PositiveBigIntegerField(default=0)
    disk_gb = models.PositiveBigIntegerField(default=0)
    object_storage_bytes = models.PositiveBigIntegerField(default=0)
    agent_tokens = models.PositiveBigIntegerField(default=0)
    agent_requests = models.PositiveIntegerField(default=0)
    estimated_cost_minor = models.PositiveBigIntegerField(default=0)
    currency_code = models.CharField(max_length=3, default="CNY")
    reserved_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.CharField(max_length=500, blank=True, default="")
    trace_id = models.CharField(max_length=32)
    active_slot = models.GeneratedField(
        expression=models.Case(
            models.When(status="ACTIVE", then=models.Value(1)),
            default=models.Value(None),
        ),
        output_field=models.PositiveSmallIntegerField(null=True),
        db_persist=True,
    )

    class Meta:
        db_table = "governance_quota_reservation"
        constraints = [
            models.UniqueConstraint(
                fields=("subject_type", "subject_ref", "active_slot"),
                name="gov_reservation_active_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(reservation_type__in=("STANDARD", "PREWARM", "SCALING")),
                name="gov_reservation_type_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "RELEASED", "EXPIRED")),
                name="gov_reservation_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(instance_count__gt=0),
                name="gov_reservation_count_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__isnull=True)
                | models.Q(expires_at__gt=models.F("reserved_at")),
                name="gov_reservation_expiry_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "expires_at"), name="gov_reservation_expiry_idx"),
            models.Index(fields=("course", "status"), name="gov_reservation_course_idx"),
            models.Index(fields=("user", "status"), name="gov_reservation_user_idx"),
            models.Index(fields=("reservation_type", "status"), name="gov_reservation_type_idx"),
        ]


class SecurityPolicy(GovernanceModel):
    class PolicyKind(models.TextChoices):
        RUNTIME_SECURITY = "RUNTIME_SECURITY"
        RESOURCE_SCALING = "RESOURCE_SCALING"

    class ScopeType(models.TextChoices):
        PLATFORM = "PLATFORM"
        COURSE = "COURSE"

    class RiskLevel(models.TextChoices):
        LOW = "LOW"
        MEDIUM = "MEDIUM"
        HIGH = "HIGH"

    policy_kind = models.CharField(max_length=32, choices=PolicyKind.choices)
    scope_type = models.CharField(max_length=16, choices=ScopeType.choices)
    scope_key = models.CharField(max_length=64, db_collation="ascii_bin")
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="governance_policies",
    )
    risk_level = models.CharField(max_length=16, choices=RiskLevel.choices)
    rules = models.JSONField(default=dict)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_governance_policies",
    )
    change_reason = models.CharField(max_length=500)

    class Meta:
        db_table = "governance_security_policy"
        constraints = [
            models.UniqueConstraint(
                fields=("policy_kind", "scope_key"),
                name="gov_policy_kind_scope_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope_type="PLATFORM", course__isnull=True)
                    | models.Q(scope_type="COURSE", course__isnull=False)
                ),
                name="gov_policy_scope_target_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(policy_kind__in=("RUNTIME_SECURITY", "RESOURCE_SCALING")),
                name="gov_policy_kind_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(risk_level__in=("LOW", "MEDIUM", "HIGH")),
                name="gov_policy_risk_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("policy_kind", "scope_type"), name="gov_policy_scope_idx"),
        ]


class NetworkAllowlist(GovernanceModel):
    class ScopeType(models.TextChoices):
        PLATFORM = "PLATFORM"
        COURSE = "COURSE"

    class TargetType(models.TextChoices):
        HOST = "HOST"
        CIDR = "CIDR"

    class Protocol(models.TextChoices):
        TCP = "TCP"
        UDP = "UDP"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        REVOKED = "REVOKED"

    scope_type = models.CharField(max_length=16, choices=ScopeType.choices)
    scope_key = models.CharField(max_length=64, db_collation="ascii_bin")
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="network_allowlist_entries",
    )
    target_type = models.CharField(max_length=16, choices=TargetType.choices)
    target_value = models.CharField(max_length=255)
    protocol = models.CharField(max_length=8, choices=Protocol.choices)
    port_start = models.PositiveIntegerField()
    port_end = models.PositiveIntegerField()
    risk_level = models.CharField(max_length=16, choices=SecurityPolicy.RiskLevel.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="approved_network_allowlist_entries",
    )
    approved_at = models.DateTimeField()
    change_reason = models.CharField(max_length=500)

    class Meta:
        db_table = "governance_network_allowlist"
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "scope_key",
                    "target_type",
                    "target_value",
                    "protocol",
                    "port_start",
                    "port_end",
                ),
                name="gov_allowlist_target_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope_type="PLATFORM", course__isnull=True)
                    | models.Q(scope_type="COURSE", course__isnull=False)
                ),
                name="gov_allowlist_scope_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(target_type__in=("HOST", "CIDR")),
                name="gov_allowlist_target_type_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(protocol__in=("TCP", "UDP")),
                name="gov_allowlist_protocol_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(port_start__gte=1)
                & models.Q(port_end__lte=65535)
                & models.Q(port_end__gte=models.F("port_start")),
                name="gov_allowlist_port_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "REVOKED")),
                name="gov_allowlist_status_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("scope_type", "scope_key", "status"),
                name="gov_allowlist_scope_idx",
            ),
        ]

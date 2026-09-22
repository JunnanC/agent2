from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import ObjectAsset, VersionedModel
from apps.courses.models import Course
from apps.governance.models import ImageAsset, ResourceProfile, RuntimeAdapter


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class Template(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"
        WITHDRAWN = "WITHDRAWN"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="lab_templates")
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="owned_lab_templates")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    current_version = models.ForeignKey(
        "TemplateVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_for_templates",
    )

    class Meta:
        db_table = "labtemplates_template"
        constraints = [
            models.UniqueConstraint(fields=("course", "name"), name="lab_tpl_course_name_uniq"),
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "PUBLISHED", "WITHDRAWN")),
                name="lab_tpl_status_ck",
            ),
        ]
        indexes = [models.Index(fields=("course", "status"), name="lab_tpl_course_status_idx")]


class TemplateVersion(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PRECHECKING = "PRECHECKING"
        PRECHECK_FAILED = "PRECHECK_FAILED"
        PRECHECK_PASSED = "PRECHECK_PASSED"
        PUBLISHED = "PUBLISHED"
        WITHDRAWN = "WITHDRAWN"

    public_id = public_id_field()
    template = models.ForeignKey(Template, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveIntegerField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    runtime_type = models.CharField(max_length=16, choices=RuntimeAdapter.RuntimeType.choices)
    runtime_adapter = models.ForeignKey(
        RuntimeAdapter, on_delete=models.PROTECT, related_name="template_versions"
    )
    image = models.ForeignKey(
        ImageAsset, on_delete=models.PROTECT, related_name="template_versions"
    )
    resource_profile = models.ForeignKey(
        ResourceProfile, on_delete=models.PROTECT, related_name="template_versions"
    )
    dependencies = models.JSONField(default=list)
    network_policy = models.JSONField(default=dict)
    workspace_capabilities = models.JSONField(default=dict)
    material_refs = models.JSONField(default=list)
    manual_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="template_manual_versions",
    )
    starter_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="template_starter_versions",
    )
    report_template_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="template_report_versions",
    )
    report_policy = models.JSONField(default=dict)
    review_policy = models.JSONField(default=dict)
    retention_days = models.PositiveIntegerField(default=30)
    spec_digest = models.CharField(max_length=64, null=True, blank=True, db_collation="ascii_bin")
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_template_versions"
    )
    published_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_template_versions",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="withdrawn_template_versions",
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "labtemplates_template_version"
        constraints = [
            models.UniqueConstraint(fields=("template", "version_no"), name="lab_tpl_ver_no_uniq"),
            models.UniqueConstraint(
                fields=("template", "spec_digest"), name="lab_tpl_spec_digest_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "DRAFT",
                        "PRECHECKING",
                        "PRECHECK_FAILED",
                        "PRECHECK_PASSED",
                        "PUBLISHED",
                        "WITHDRAWN",
                    )
                ),
                name="lab_tpl_ver_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(retention_days__gte=1), name="lab_tpl_retention_ck"
            ),
        ]
        indexes = [
            models.Index(fields=("status", "published_at"), name="lab_tpl_ver_status_idx"),
            models.Index(fields=("template", "status"), name="lab_tpl_ver_parent_idx"),
        ]


class AutoCheckRule(VersionedModel):
    public_id = public_id_field()
    template_version = models.ForeignKey(
        TemplateVersion, on_delete=models.PROTECT, related_name="auto_check_rules"
    )
    position = models.PositiveIntegerField()
    position_key = models.CharField(max_length=64, default="")
    is_active = models.BooleanField(default=True)
    checker_type = models.CharField(max_length=64)
    input_schema = models.JSONField(default=dict)
    output_schema = models.JSONField(default=dict)
    timeout_seconds = models.PositiveIntegerField()
    resource_limit = models.JSONField(default=dict)
    network_policy = models.JSONField(default=dict)
    display_policy = models.JSONField(default=dict)
    failure_semantics = models.JSONField(default=dict)
    rule_digest = models.CharField(max_length=64, db_collation="ascii_bin")

    class Meta:
        db_table = "labtemplates_auto_check_rule"
        constraints = [
            models.UniqueConstraint(
                fields=("template_version", "position_key"), name="lab_rule_position_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1), name="lab_rule_position_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(timeout_seconds__gte=1), name="lab_rule_timeout_ck"
            ),
        ]
        indexes = [models.Index(fields=("template_version", "position"), name="lab_rule_order_idx")]


class TemplatePrecheckRun(VersionedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        RETRY = "RETRY"
        PASSED = "PASSED"
        FAILED = "FAILED"

    public_id = public_id_field()
    template_version = models.ForeignKey(
        TemplateVersion, on_delete=models.PROTECT, related_name="precheck_runs"
    )
    requested_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="requested_template_prechecks"
    )
    requested_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    current_stage = models.CharField(max_length=32, blank=True, default="")
    stage_results = models.JSONField(default=list)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_detail_masked = models.JSONField(default=dict)
    retryable = models.BooleanField(default=False)
    trace_id = models.CharField(max_length=32)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "labtemplates_template_precheck_run"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("QUEUED", "RUNNING", "RETRY", "PASSED", "FAILED")),
                name="lab_precheck_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1)
                & models.Q(attempt_count__lte=models.F("max_attempts")),
                name="lab_precheck_attempts_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("template_version", "created_at"), name="lab_precheck_ver_idx"),
            models.Index(fields=("status", "created_at"), name="lab_precheck_status_idx"),
        ]

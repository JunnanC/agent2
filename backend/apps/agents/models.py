from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import AppendOnlyModel, ObjectAsset, VersionedModel
from apps.courses.models import Course, Enrollment, MaterialVersion
from apps.experiments.models import ExperimentTask


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class AgentDefinition(VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        RETIRED = "RETIRED"

    public_id = public_id_field()
    key = models.CharField(max_length=64)
    version_no = models.PositiveIntegerField()
    mode = models.CharField(max_length=32, default="COURSE_AGENT")
    model_route = models.CharField(max_length=128)
    system_prompt = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    safety_config = models.JSONField(default=dict)

    class Meta:
        db_table = "agents_agent_definition"
        constraints = [
            models.UniqueConstraint(
                fields=("key", "version_no"), name="agents_definition_key_ver_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gt=0), name="agents_definition_ver_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "RETIRED")),
                name="agents_definition_status_ck",
            ),
        ]
        indexes = [models.Index(fields=("key", "status"), name="agents_definition_key_idx")]


class KnowledgeBase(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        ACTIVE = "ACTIVE"
        RETIRED = "RETIRED"

    public_id = public_id_field()
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="agent_knowledge_bases"
    )
    name = models.CharField(max_length=180)
    description = models.CharField(max_length=500, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        db_table = "agents_knowledge_base"
        constraints = [
            models.UniqueConstraint(fields=("course", "name"), name="agents_kb_course_name_uniq"),
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "ACTIVE", "RETIRED")),
                name="agents_kb_status_ck",
            ),
        ]
        indexes = [models.Index(fields=("course", "status"), name="agents_kb_course_idx")]


class AgentSource(VersionedModel):
    class SourceType(models.TextChoices):
        COURSE_MATERIAL = "COURSE_MATERIAL"
        LAB_MANUAL = "LAB_MANUAL"
        TEACHER_FAQ = "TEACHER_FAQ"
        STATIC = "STATIC"

    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        ACTIVE = "ACTIVE"
        RETIRED = "RETIRED"

    public_id = public_id_field()
    knowledge_base = models.ForeignKey(
        KnowledgeBase, on_delete=models.PROTECT, related_name="sources"
    )
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="agent_sources")
    source_type = models.CharField(max_length=32, choices=SourceType.choices)
    title = models.CharField(max_length=180)
    material_version = models.ForeignKey(
        MaterialVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agent_sources",
    )
    object_asset = models.ForeignKey(
        ObjectAsset, on_delete=models.PROTECT, null=True, blank=True, related_name="agent_sources"
    )
    audience = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        db_table = "agents_source"
        constraints = [
            models.UniqueConstraint(
                fields=("knowledge_base", "title"), name="agents_source_kb_title_uniq"
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(source_type="COURSE_MATERIAL")
                        & models.Q(material_version__isnull=False)
                    )
                    | (~models.Q(source_type="COURSE_MATERIAL"))
                ),
                name="agents_source_material_shape_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "ACTIVE", "RETIRED")),
                name="agents_source_status_ck",
            ),
        ]
        indexes = [models.Index(fields=("course", "status"), name="agents_source_course_idx")]


class AgentSourceVersion(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        INGESTING = "INGESTING"
        INDEXED = "INDEXED"
        FAILED = "FAILED"
        WITHDRAWN = "WITHDRAWN"

    public_id = public_id_field()
    source = models.ForeignKey(AgentSource, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveIntegerField()
    digest_sha256 = models.CharField(max_length=64, db_collation="ascii_bin")
    object_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agent_source_versions",
    )
    material_version = models.ForeignKey(
        MaterialVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agent_source_versions",
    )
    audience = models.JSONField(default=dict)
    parse_summary = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    indexed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "agents_source_version"
        constraints = [
            models.UniqueConstraint(
                fields=("source", "version_no"), name="agents_source_version_no_uniq"
            ),
            models.UniqueConstraint(
                fields=("source", "digest_sha256"), name="agents_source_version_digest_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gt=0), name="agents_source_version_no_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("DRAFT", "INGESTING", "INDEXED", "FAILED", "WITHDRAWN")
                ),
                name="agents_source_version_status_ck",
            ),
        ]
        indexes = [models.Index(fields=("source", "status"), name="agents_source_ver_status_idx")]


class IngestionRun(VersionedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        SUCCEEDED = "SUCCEEDED"
        FAILED = "FAILED"

    public_id = public_id_field()
    source_version = models.ForeignKey(
        AgentSourceVersion, on_delete=models.PROTECT, related_name="ingestion_runs"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    chunk_count = models.PositiveIntegerField(default=0)
    indexed_count = models.PositiveIntegerField(default=0)
    filtered_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True, default="")
    trace_id = models.CharField(max_length=32)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "agents_ingestion_run"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("QUEUED", "RUNNING", "SUCCEEDED", "FAILED")),
                name="agents_ingest_status_ck",
            )
        ]
        indexes = [
            models.Index(fields=("source_version", "created_at"), name="agents_ingest_source_idx")
        ]


class PromptTemplate(VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        RETIRED = "RETIRED"

    public_id = public_id_field()
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agent_prompt_templates",
    )
    name = models.CharField(max_length=180)
    template_type = models.CharField(max_length=32, default="COURSE_INSTRUCTION")
    platform_managed = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    def __str__(self) -> str:
        return self.name

    class Meta:
        db_table = "agents_prompt_template"
        indexes = [
            models.Index(
                fields=("course", "status", "name"), name="agents_prompt_scope_status_idx"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("course", "name"), name="agents_prompt_template_scope_name_uniq"
            )
        ]


class PromptVersion(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"
        RETIRED = "RETIRED"

    public_id = public_id_field()
    template = models.ForeignKey(PromptTemplate, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveIntegerField()
    body = models.TextField()
    digest_sha256 = models.CharField(max_length=64, db_collation="ascii_bin")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="agent_prompt_versions"
    )

    class Meta:
        db_table = "agents_prompt_version"
        constraints = [
            models.UniqueConstraint(
                fields=("template", "version_no"), name="agents_prompt_version_no_uniq"
            )
        ]
        indexes = [models.Index(fields=("template", "status"), name="agents_prompt_ver_status_idx")]


class ModelRoute(VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        RETIRED = "RETIRED"

    public_id = public_id_field()
    key = models.CharField(max_length=64)
    version_no = models.PositiveIntegerField()
    provider = models.CharField(max_length=64)
    model_name = models.CharField(max_length=128)
    fallback_routes = models.JSONField(default=list)
    regions = models.JSONField(default=list)
    sensitive_data_allowed = models.BooleanField(default=False)
    timeout_seconds = models.PositiveIntegerField(default=30)
    max_tokens = models.PositiveIntegerField(default=4096)
    cost_per_1k_input_minor = models.PositiveIntegerField(default=0)
    cost_per_1k_output_minor = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        db_table = "agents_model_route"
        constraints = [
            models.UniqueConstraint(
                fields=("key", "version_no"), name="agents_model_route_key_ver_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gt=0), name="agents_model_route_ver_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "RETIRED")),
                name="agents_model_route_status_ck",
            ),
        ]
        indexes = [models.Index(fields=("key", "status"), name="agents_model_route_key_idx")]


class ToolPolicy(VersionedModel):
    class Risk(models.TextChoices):
        LOW = "LOW"
        MEDIUM = "MEDIUM"
        HIGH = "HIGH"
        FORBIDDEN = "FORBIDDEN"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        RETIRED = "RETIRED"

    public_id = public_id_field()
    key = models.CharField(max_length=64)
    version_no = models.PositiveIntegerField()
    tool_name = models.CharField(max_length=128)
    risk = models.CharField(max_length=16, choices=Risk.choices)
    schema = models.JSONField(default=dict)
    allowlist = models.JSONField(default=list)
    redaction_rules = models.JSONField(default=list)
    timeout_seconds = models.PositiveIntegerField(default=30)
    output_limit = models.PositiveIntegerField(default=8192)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, null=True, blank=True, related_name="agent_tool_policies"
    )

    class Meta:
        db_table = "agents_tool_policy"
        constraints = [
            models.UniqueConstraint(
                fields=("key", "version_no"), name="agents_tool_policy_key_ver_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gt=0), name="agents_tool_policy_ver_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(risk__in=("LOW", "MEDIUM", "HIGH", "FORBIDDEN")),
                name="agents_tool_policy_risk_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "RETIRED")),
                name="agents_tool_policy_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("tool_name", "risk", "status"), name="agents_tool_policy_tool_idx")
        ]


class CourseAgentProfile(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        EVALUATING = "EVALUATING"
        ACTIVE = "ACTIVE"
        RETIRED = "RETIRED"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="agent_profiles")
    definition = models.ForeignKey(
        AgentDefinition, on_delete=models.PROTECT, related_name="course_profiles"
    )
    version_no = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    active_course_key = models.GeneratedField(
        expression=models.Case(
            models.When(status="ACTIVE", then=models.F("course")),
            default=models.Value(None),
            output_field=models.BigIntegerField(null=True),
        ),
        output_field=models.BigIntegerField(null=True),
        db_persist=True,
    )
    modes = models.JSONField(default=list)
    knowledge_base = models.ForeignKey(
        KnowledgeBase, on_delete=models.PROTECT, null=True, blank=True, related_name="profiles"
    )
    prompt_version = models.ForeignKey(
        PromptVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="profiles"
    )
    tool_policy = models.ForeignKey(
        ToolPolicy, on_delete=models.PROTECT, null=True, blank=True, related_name="profiles"
    )
    model_route = models.CharField(max_length=128)
    budget = models.JSONField(default=dict)
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_until = models.DateTimeField(null=True, blank=True)
    last_eval_run = models.ForeignKey(
        "EvalRun", on_delete=models.PROTECT, null=True, blank=True, related_name="gated_profiles"
    )

    class Meta:
        db_table = "agents_course_profile"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "version_no"), name="agents_course_profile_ver_uniq"
            ),
            models.UniqueConstraint(
                fields=("active_course_key",), name="agents_course_profile_active_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "EVALUATING", "ACTIVE", "RETIRED")),
                name="agents_course_profile_status_ck",
            ),
        ]
        indexes = [models.Index(fields=("course", "status"), name="agents_profile_course_idx")]


class AgentSession(VersionedModel):
    class Mode(models.TextChoices):
        KNOWLEDGE_QA = "KNOWLEDGE_QA"
        SOCRATIC_HINT = "SOCRATIC_HINT"
        DEBUG_ASSIST = "DEBUG_ASSIST"
        REPORT_COACH = "REPORT_COACH"
        CODE_ASSIST = "CODE_ASSIST"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        CLOSED = "CLOSED"
        BLOCKED = "BLOCKED"

    public_id = public_id_field()
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="agent_sessions")
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="agent_sessions")
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.PROTECT, related_name="agent_sessions"
    )
    task = models.ForeignKey(
        ExperimentTask,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agent_sessions",
    )
    profile = models.ForeignKey(
        CourseAgentProfile, on_delete=models.PROTECT, related_name="sessions"
    )
    definition = models.ForeignKey(
        AgentDefinition, on_delete=models.PROTECT, related_name="sessions"
    )
    profile_version = models.PositiveIntegerField()
    mode = models.CharField(max_length=32, choices=Mode.choices)
    prompt_version = models.ForeignKey(
        PromptVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="sessions"
    )
    knowledge_base = models.ForeignKey(
        KnowledgeBase, on_delete=models.PROTECT, null=True, blank=True, related_name="sessions"
    )
    tool_policy = models.ForeignKey(
        ToolPolicy, on_delete=models.PROTECT, null=True, blank=True, related_name="sessions"
    )
    model_route = models.CharField(max_length=128, default="")
    budget_snapshot = models.JSONField(default=dict)
    knowledge_snapshot = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    last_message_at = models.DateTimeField(null=True, blank=True)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "agents_session"
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(mode="KNOWLEDGE_QA") | models.Q(task__isnull=False)),
                name="agents_session_task_mode_ck",
            ),
            models.UniqueConstraint(
                fields=("student", "course", "task", "mode", "profile_version"),
                name="agents_session_scope_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=("student", "course", "status"), name="agents_session_student_idx"),
            models.Index(fields=("task", "status"), name="agents_session_task_idx"),
        ]


class AgentMessage(AppendOnlyModel):
    class Role(models.TextChoices):
        USER = "USER"
        ASSISTANT = "ASSISTANT"
        SYSTEM = "SYSTEM"
        TOOL = "TOOL"

    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        COMPLETE = "COMPLETE"
        FAILED = "FAILED"

    public_id = public_id_field()
    session = models.ForeignKey(AgentSession, on_delete=models.PROTECT, related_name="messages")
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="replies",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    body = models.TextField()
    body_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    token_count = models.PositiveIntegerField(default=0)
    cost_minor = models.PositiveIntegerField(default=0)
    citation_status = models.CharField(max_length=32, blank=True, default="NOT_APPLICABLE")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    error_code = models.CharField(max_length=64, blank=True, default="")
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "agents_message"
        constraints = [
            models.UniqueConstraint(
                fields=("reply_to", "role"), name="agents_message_reply_role_uniq"
            )
        ]
        indexes = [
            models.Index(fields=("session", "created_at"), name="agents_message_session_idx")
        ]


class RetrievalTrace(AppendOnlyModel):
    public_id = public_id_field()
    session = models.ForeignKey(
        AgentSession, on_delete=models.PROTECT, related_name="retrieval_traces"
    )
    message = models.ForeignKey(
        AgentMessage,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="retrieval_traces",
    )
    query_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    model_route = models.CharField(max_length=128, blank=True, default="")
    prompt_version = models.ForeignKey(
        PromptVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="retrieval_traces",
    )
    scope_snapshot = models.JSONField(default=dict)
    result_count = models.PositiveIntegerField(default=0)
    filtered_count = models.PositiveIntegerField(default=0)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "agents_retrieval_trace"
        indexes = [
            models.Index(fields=("session", "created_at"), name="agents_retrieval_session_idx")
        ]


class Citation(AppendOnlyModel):
    public_id = public_id_field()
    trace = models.ForeignKey(RetrievalTrace, on_delete=models.PROTECT, related_name="citations")
    message = models.ForeignKey(AgentMessage, on_delete=models.PROTECT, related_name="citations")
    source_version = models.ForeignKey(
        AgentSourceVersion, on_delete=models.PROTECT, related_name="citations"
    )
    rank = models.PositiveIntegerField()
    title = models.CharField(max_length=180)
    snippet = models.TextField()
    score = models.FloatField(default=0)
    accessible = models.BooleanField(default=True)
    download_asset = models.ForeignKey(
        ObjectAsset, on_delete=models.PROTECT, null=True, blank=True, related_name="agent_citations"
    )

    class Meta:
        db_table = "agents_citation"
        constraints = [
            models.UniqueConstraint(fields=("trace", "rank"), name="agents_citation_rank_uniq")
        ]
        indexes = [models.Index(fields=("message", "rank"), name="agents_citation_message_idx")]


class AgentToolCall(AppendOnlyModel):
    public_id = public_id_field()
    session = models.ForeignKey(AgentSession, on_delete=models.PROTECT, related_name="tool_calls")
    message = models.ForeignKey(AgentMessage, on_delete=models.PROTECT, related_name="tool_calls")
    policy = models.ForeignKey(ToolPolicy, on_delete=models.PROTECT, related_name="tool_calls")
    tool_name = models.CharField(max_length=128)
    risk = models.CharField(max_length=16)
    arguments_masked = models.JSONField(default=dict)
    arguments_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "agents_tool_call"
        indexes = [
            models.Index(fields=("session", "created_at"), name="agents_tool_call_session_idx")
        ]


class AgentToolCallState(VersionedModel):
    class Status(models.TextChoices):
        PENDING_APPROVAL = "PENDING_APPROVAL"
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        SUCCEEDED = "SUCCEEDED"
        DENIED = "DENIED"
        FAILED = "FAILED"
        EXPIRED = "EXPIRED"

    public_id = public_id_field()
    tool_call = models.OneToOneField(AgentToolCall, on_delete=models.PROTECT, related_name="state")
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PENDING_APPROVAL
    )
    output_masked = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True, default="")
    executed_at = models.DateTimeField(null=True, blank=True)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "agents_tool_call_state"
        indexes = [
            models.Index(fields=("status", "updated_at"), name="agents_tool_state_status_idx")
        ]


class AgentApproval(AppendOnlyModel):
    class Decision(models.TextChoices):
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"

    public_id = public_id_field()
    tool_call = models.ForeignKey(AgentToolCall, on_delete=models.PROTECT, related_name="approvals")
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="agent_approvals")
    decision = models.CharField(max_length=16, choices=Decision.choices)
    arguments_digest = models.CharField(max_length=64, db_collation="ascii_bin")
    expires_at = models.DateTimeField()
    reason = models.CharField(max_length=255, blank=True, default="")
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "agents_approval"
        indexes = [
            models.Index(fields=("tool_call", "created_at"), name="agents_approval_call_idx")
        ]


class EvalSuite(VersionedModel):
    public_id = public_id_field()
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, null=True, blank=True, related_name="agent_eval_suites"
    )
    name = models.CharField(max_length=180)
    platform_managed = models.BooleanField(default=False)
    threshold = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default="ACTIVE")

    class Meta:
        db_table = "agents_eval_suite"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "name"), name="agents_eval_suite_scope_name_uniq"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(platform_managed=True, course__isnull=True)
                    | models.Q(platform_managed=False, course__isnull=False)
                ),
                name="agents_eval_suite_scope_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "RETIRED")),
                name="agents_eval_suite_status_ck",
            ),
        ]


class EvalCase(AppendOnlyModel):
    public_id = public_id_field()
    suite = models.ForeignKey(EvalSuite, on_delete=models.PROTECT, related_name="cases")
    key = models.CharField(max_length=128)
    category = models.CharField(max_length=64)
    prompt = models.TextField()
    expected = models.JSONField(default=dict)
    mandatory = models.BooleanField(default=False)

    class Meta:
        db_table = "agents_eval_case"
        constraints = [
            models.UniqueConstraint(fields=("suite", "key"), name="agents_eval_case_key_uniq")
        ]


class EvalRun(VersionedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        PASSED = "PASSED"
        FAILED = "FAILED"

    public_id = public_id_field()
    suite = models.ForeignKey(EvalSuite, on_delete=models.PROTECT, related_name="runs")
    profile = models.ForeignKey(
        CourseAgentProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="eval_runs",
    )
    definition_version = models.CharField(max_length=128)
    profile_version = models.PositiveIntegerField(null=True, blank=True)
    prompt_version = models.CharField(max_length=128, blank=True, default="")
    knowledge_version = models.CharField(max_length=128, blank=True, default="")
    tool_policy_version = models.CharField(max_length=128, blank=True, default="")
    model_route_row_version = models.PositiveIntegerField(null=True, blank=True)
    tool_policy_row_version = models.PositiveIntegerField(null=True, blank=True)
    model_route = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    scores = models.JSONField(default=dict)
    passed = models.BooleanField(default=False)
    trace_id = models.CharField(max_length=32)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "agents_eval_run"
        indexes = [
            models.Index(fields=("suite", "status", "created_at"), name="agents_eval_run_suite_idx")
        ]


class EvalResult(AppendOnlyModel):
    public_id = public_id_field()
    run = models.ForeignKey(EvalRun, on_delete=models.PROTECT, related_name="results")
    case = models.ForeignKey(EvalCase, on_delete=models.PROTECT, related_name="results")
    dimension = models.CharField(max_length=64)
    passed = models.BooleanField(default=False)
    score = models.FloatField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    token_count = models.PositiveIntegerField(default=0)
    cost_minor = models.PositiveIntegerField(default=0)
    detail_masked = models.JSONField(default=dict)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "agents_eval_result"
        constraints = [
            models.UniqueConstraint(
                fields=("run", "case", "dimension"), name="agents_eval_result_case_dim_uniq"
            )
        ]


class SessionFeedback(AppendOnlyModel):
    class Rating(models.TextChoices):
        USEFUL = "USEFUL"
        NOT_USEFUL = "NOT_USEFUL"

    public_id = public_id_field()
    session = models.ForeignKey(AgentSession, on_delete=models.PROTECT, related_name="feedback")
    message = models.ForeignKey(AgentMessage, on_delete=models.PROTECT, related_name="feedback")
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="agent_feedback")
    rating = models.CharField(max_length=16, choices=Rating.choices)
    issue_type = models.CharField(max_length=64, blank=True, default="")
    note = models.CharField(max_length=1000, blank=True, default="")

    class Meta:
        db_table = "agents_session_feedback"
        constraints = [
            models.UniqueConstraint(
                fields=("message", "student"), name="agents_feedback_message_student_uniq"
            )
        ]
        indexes = [
            models.Index(fields=("session", "created_at"), name="agents_feedback_session_idx")
        ]


class SessionFeedbackTriage(VersionedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN"
        TRIAGED = "TRIAGED"
        CLOSED = "CLOSED"

    public_id = public_id_field()
    feedback = models.OneToOneField(
        SessionFeedback, on_delete=models.PROTECT, related_name="triage"
    )
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="agent_feedback_triage")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    note = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "agents_session_feedback_triage"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("OPEN", "TRIAGED", "CLOSED")),
                name="agents_feedback_triage_status_ck",
            )
        ]
        indexes = [models.Index(fields=("status", "updated_at"), name="agents_feedback_triage_idx")]

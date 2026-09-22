from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import AppendOnlyModel, VersionedModel


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class Course(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"
        CLOSED = "CLOSED"
        ARCHIVED = "ARCHIVED"

    class Visibility(models.TextChoices):
        PUBLIC = "PUBLIC"
        UNLISTED = "UNLISTED"

    class EnrollmentMode(models.TextChoices):
        OPEN = "OPEN"
        APPROVAL = "APPROVAL"

    public_id = public_id_field()
    code = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=160)
    summary = models.CharField(max_length=500, blank=True, default="")
    description = models.TextField(blank=True, default="")
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="owned_courses")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
    )
    enrollment_mode = models.CharField(
        max_length=16,
        choices=EnrollmentMode.choices,
        default=EnrollmentMode.OPEN,
    )
    capacity = models.PositiveIntegerField(null=True, blank=True)
    enrollment_start = models.DateTimeField(null=True, blank=True)
    enrollment_end = models.DateTimeField(null=True, blank=True)
    teaching_start = models.DateTimeField(null=True, blank=True)
    teaching_end = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "courses_course"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "PUBLISHED", "CLOSED", "ARCHIVED")),
                name="courses_course_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(visibility__in=("PUBLIC", "UNLISTED")),
                name="courses_course_visibility_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(enrollment_mode__in=("OPEN", "APPROVAL")),
                name="courses_course_enroll_mode_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity__isnull=True) | models.Q(capacity__gt=0),
                name="courses_course_capacity_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(enrollment_start__isnull=True)
                    | models.Q(enrollment_end__isnull=True)
                    | models.Q(enrollment_end__gt=models.F("enrollment_start"))
                ),
                name="courses_course_enroll_window_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(teaching_start__isnull=True)
                    | models.Q(teaching_end__isnull=True)
                    | models.Q(teaching_end__gt=models.F("teaching_start"))
                ),
                name="courses_course_teach_window_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("status", "enrollment_start", "enrollment_end"),
                name="courses_course_window_idx",
            ),
            models.Index(
                fields=("owner", "status", "updated_at"),
                name="courses_course_owner_idx",
            ),
        ]


class CourseStaff(VersionedModel):
    class Role(models.TextChoices):
        OWNER = "OWNER"
        ASSISTANT = "ASSISTANT"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        REVOKED = "REVOKED"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="staff")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="course_staff")
    role = models.CharField(max_length=16, choices=Role.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    appointed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="appointed_course_staff",
    )
    appointed_at = models.DateTimeField()
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_course_staff",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    owner_slot = models.GeneratedField(
        expression=models.Case(
            models.When(role="OWNER", status="ACTIVE", then=models.Value(1)),
            default=models.Value(None),
        ),
        output_field=models.PositiveSmallIntegerField(null=True),
        db_persist=True,
    )

    class Meta:
        db_table = "courses_course_staff"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "user"),
                name="courses_staff_course_user_uniq",
            ),
            models.UniqueConstraint(
                fields=("course", "owner_slot"),
                name="courses_staff_owner_slot_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=("OWNER", "ASSISTANT")),
                name="courses_staff_role_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "REVOKED")),
                name="courses_staff_status_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "status", "course"),
                name="courses_staff_user_idx",
            ),
            models.Index(
                fields=("course", "role", "status"),
                name="courses_staff_role_idx",
            ),
        ]


class CourseStaffEvent(AppendOnlyModel):
    staff = models.ForeignKey(CourseStaff, on_delete=models.PROTECT, related_name="events")
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="staff_events")
    from_role = models.CharField(max_length=16, blank=True, default="")
    to_role = models.CharField(max_length=16)
    from_status = models.CharField(max_length=16, blank=True, default="")
    to_status = models.CharField(max_length=16)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "courses_course_staff_event"
        indexes = [
            models.Index(fields=("staff", "created_at"), name="courses_staff_event_idx"),
            models.Index(fields=("course", "created_at"), name="courses_staff_course_evt_idx"),
        ]


class CourseStaffGrant(VersionedModel):
    class Capability(models.TextChoices):
        MANAGE_ENROLLMENT = "MANAGE_ENROLLMENT"
        MANAGE_CONTENT = "MANAGE_CONTENT"
        MODERATE_QA = "MODERATE_QA"
        MANAGE_TEMPLATE = "MANAGE_TEMPLATE"
        PUBLISH_EXPERIMENT = "PUBLISH_EXPERIMENT"
        MANAGE_EXTENSION = "MANAGE_EXTENSION"
        VIEW_PROGRESS = "VIEW_PROGRESS"
        REVIEW_SUBMISSION = "REVIEW_SUBMISSION"
        EXPORT_RESULT = "EXPORT_RESULT"
        MANAGE_AGENT = "MANAGE_AGENT"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        REVOKED = "REVOKED"

    public_id = public_id_field()
    course_staff = models.ForeignKey(
        CourseStaff,
        on_delete=models.PROTECT,
        related_name="grants",
    )
    capability = models.CharField(max_length=32, choices=Capability.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="granted_course_capabilities",
    )
    granted_at = models.DateTimeField()
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_course_capabilities",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "courses_course_staff_grant"
        constraints = [
            models.UniqueConstraint(
                fields=("course_staff", "capability"),
                name="courses_staff_capability_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "REVOKED")),
                name="courses_grant_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "expires_at"), name="courses_grant_expiry_idx"),
        ]


class CourseStaffGrantEvent(AppendOnlyModel):
    grant = models.ForeignKey(
        CourseStaffGrant,
        on_delete=models.PROTECT,
        related_name="events",
    )
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="grant_events")
    from_status = models.CharField(max_length=16, blank=True, default="")
    to_status = models.CharField(max_length=16)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "courses_course_staff_grant_event"
        indexes = [
            models.Index(fields=("grant", "created_at"), name="courses_grant_event_idx"),
            models.Index(fields=("course", "created_at"), name="courses_grant_course_evt_idx"),
        ]


class Enrollment(VersionedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        ACTIVE = "ACTIVE"
        REJECTED = "REJECTED"
        WITHDRAWN = "WITHDRAWN"
        DROPPED = "DROPPED"
        REMOVED = "REMOVED"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="enrollments")
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="enrollments")
    cycle_no = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices)
    application_message = models.TextField(blank=True, default="")
    applied_at = models.DateTimeField()
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_enrollments",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True, default="")
    end_reason = models.CharField(max_length=500, blank=True, default="")
    live_slot = models.GeneratedField(
        expression=models.Case(
            models.When(status__in=("PENDING", "ACTIVE"), then=models.Value(1)),
            default=models.Value(None),
        ),
        output_field=models.PositiveSmallIntegerField(null=True),
        db_persist=True,
    )

    class Meta:
        db_table = "courses_enrollment"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "student", "cycle_no"),
                name="courses_enroll_cycle_uniq",
            ),
            models.UniqueConstraint(
                fields=("course", "student", "live_slot"),
                name="courses_enroll_live_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(cycle_no__gt=0),
                name="courses_enroll_cycle_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "PENDING",
                        "ACTIVE",
                        "REJECTED",
                        "WITHDRAWN",
                        "DROPPED",
                        "REMOVED",
                    )
                ),
                name="courses_enroll_status_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("course", "status", "applied_at"),
                name="courses_enroll_course_idx",
            ),
            models.Index(
                fields=("student", "status", "updated_at"),
                name="courses_enroll_student_idx",
            ),
        ]


class EnrollmentEvent(AppendOnlyModel):
    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        related_name="events",
    )
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="enrollment_events")
    from_status = models.CharField(max_length=16, blank=True, default="")
    to_status = models.CharField(max_length=16)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    reason_code = models.CharField(max_length=64)
    blockers_snapshot = models.JSONField(default=list)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "courses_enrollment_event"
        indexes = [
            models.Index(
                fields=("enrollment", "created_at"),
                name="courses_enroll_event_idx",
            ),
            models.Index(
                fields=("course", "created_at"),
                name="courses_enroll_course_evt_idx",
            ),
        ]


class Chapter(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"
        WITHDRAWN = "WITHDRAWN"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="chapters")
    title = models.CharField(max_length=180)
    summary = models.CharField(max_length=500, blank=True, default="")
    position = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "courses_chapter"
        constraints = [
            models.UniqueConstraint(fields=("course", "position"), name="courses_chapter_pos_uniq"),
            models.CheckConstraint(
                condition=models.Q(position__gt=0), name="courses_chapter_pos_ck"
            ),
        ]
        indexes = [
            models.Index(fields=("course", "status", "position"), name="courses_chapter_list_idx")
        ]


class Material(VersionedModel):
    class Kind(models.TextChoices):
        FILE = "FILE"
        LINK = "LINK"
        TEXT = "TEXT"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="materials")
    chapter = models.ForeignKey(Chapter, on_delete=models.PROTECT, related_name="materials")
    title = models.CharField(max_length=180)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    current_version = models.ForeignKey(
        "MaterialVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_for",
    )

    class Meta:
        db_table = "courses_material"
        constraints = [
            models.UniqueConstraint(fields=("course", "title"), name="courses_material_title_uniq")
        ]
        indexes = [models.Index(fields=("course", "chapter"), name="courses_material_course_idx")]


class MaterialVersion(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"
        WITHDRAWN = "WITHDRAWN"

    public_id = public_id_field()
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    text_content = models.TextField(blank=True, default="")
    link_url = models.URLField(max_length=1000, blank=True, default="")
    object_asset = models.ForeignKey(
        "core.ObjectAsset",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="material_versions",
    )
    digest_sha256 = models.CharField(max_length=64, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_material_versions"
    )

    class Meta:
        db_table = "courses_material_version"
        constraints = [
            models.UniqueConstraint(
                fields=("material", "version_no"), name="courses_material_ver_uniq"
            )
        ]
        indexes = [models.Index(fields=("material", "status"), name="courses_material_ver_idx")]


class Announcement(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"
        WITHDRAWN = "WITHDRAWN"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="announcements")
    title = models.CharField(max_length=180)
    body = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    pinned = models.BooleanField(default=False)
    publish_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_announcements"
    )

    class Meta:
        db_table = "courses_announcement"
        indexes = [
            models.Index(fields=("course", "status", "publish_at"), name="courses_announce_idx")
        ]


class CalendarEvent(VersionedModel):
    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="calendar_events")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default="")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=16, default="ACTIVE")
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_calendar_events"
    )

    class Meta:
        db_table = "courses_calendar_event"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="courses_calendar_time_ck",
            )
        ]
        indexes = [models.Index(fields=("course", "starts_at"), name="courses_calendar_idx")]


class CoursePrerequisite(AppendOnlyModel):
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="prerequisites")
    prerequisite_course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="required_by_courses"
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "courses_course_prerequisite"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "prerequisite_course"), name="courses_course_prereq_uniq"
            )
        ]


class ChapterPrerequisite(AppendOnlyModel):
    chapter = models.ForeignKey(Chapter, on_delete=models.PROTECT, related_name="prerequisites")
    prerequisite_chapter = models.ForeignKey(
        Chapter, on_delete=models.PROTECT, related_name="required_by_chapters"
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "courses_chapter_prerequisite"
        constraints = [
            models.UniqueConstraint(
                fields=("chapter", "prerequisite_chapter"), name="courses_chapter_prereq_uniq"
            )
        ]


class Question(VersionedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN"
        ANSWERED = "ANSWERED"
        HIDDEN = "HIDDEN"
        LOCKED = "LOCKED"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="questions")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="course_questions")
    title = models.CharField(max_length=180)
    body = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    pinned = models.BooleanField(default=False)

    class Meta:
        db_table = "courses_question"
        indexes = [
            models.Index(fields=("course", "status", "created_at"), name="courses_question_idx")
        ]


class Answer(VersionedModel):
    public_id = public_id_field()
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="answers")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="course_answers")
    body = models.TextField()
    status = models.CharField(max_length=16, default="VISIBLE")

    class Meta:
        db_table = "courses_answer"
        indexes = [models.Index(fields=("question", "created_at"), name="courses_answer_idx")]


class ModerationEvent(AppendOnlyModel):
    question = models.ForeignKey(
        Question, on_delete=models.PROTECT, related_name="moderation_events"
    )
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    from_status = models.CharField(max_length=16)
    to_status = models.CharField(max_length=16)
    reason = models.CharField(max_length=500)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "courses_moderation_event"


class Invitation(VersionedModel):
    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="invitations")
    code_digest = models.CharField(max_length=64, unique=True)
    code_masked = models.CharField(max_length=32)
    max_uses = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=16, default="ACTIVE")
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_invitations"
    )

    class Meta:
        db_table = "courses_invitation"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_uses__gt=0), name="courses_invite_max_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(used_count__lte=models.F("max_uses")),
                name="courses_invite_used_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("course", "status", "expires_at"), name="courses_invite_idx")
        ]


class EnrollmentImportJob(VersionedModel):
    class Status(models.TextChoices):
        PRECHECKING = "PRECHECKING"
        READY = "READY"
        RUNNING = "RUNNING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    public_id = public_id_field()
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="enrollment_import_jobs"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PRECHECKING)
    filename = models.CharField(max_length=255, blank=True, default="")
    source_csv = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="enrollment_import_jobs"
    )
    summary = models.JSONField(default=dict)

    class Meta:
        db_table = "courses_enrollment_import_job"


class EnrollmentImportItem(VersionedModel):
    job = models.ForeignKey(EnrollmentImportJob, on_delete=models.PROTECT, related_name="items")
    row_no = models.PositiveIntegerField()
    normalized_identity = models.CharField(max_length=320)
    status = models.CharField(max_length=16, default="PENDING")
    error_code = models.CharField(max_length=64, blank=True, default="")
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        db_table = "courses_enrollment_import_item"
        constraints = [
            models.UniqueConstraint(fields=("job", "row_no"), name="courses_import_row_uniq")
        ]


class CourseCopyJob(VersionedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    public_id = public_id_field()
    source_course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="copy_jobs")
    target_course = models.ForeignKey(
        Course, on_delete=models.PROTECT, null=True, blank=True, related_name="copied_from_jobs"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    options = models.JSONField(default=dict)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="course_copy_jobs")
    error_code = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "courses_copy_job"


class CourseCopyItem(AppendOnlyModel):
    job = models.ForeignKey(CourseCopyJob, on_delete=models.PROTECT, related_name="items")
    item_type = models.CharField(max_length=32)
    source_ref = models.CharField(max_length=64)
    target_ref = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, default="PENDING")
    error_code = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "courses_copy_item"

from django.db import models

from apps.core.identifiers import new_ulid
from apps.core.models import AppendOnlyModel, ObjectAsset, VersionedModel


class User(VersionedModel):
    class RegistrationRole(models.TextChoices):
        STUDENT = "STUDENT"
        TEACHER = "TEACHER"

    class AccountStatus(models.TextChoices):
        ACTIVE = "ACTIVE"
        DISABLED = "DISABLED"

    public_id = models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )
    email = models.EmailField(max_length=254, unique=True)
    username = models.CharField(max_length=32, unique=True)
    display_name = models.CharField(max_length=64)
    registration_role = models.CharField(
        max_length=16, choices=RegistrationRole.choices, default=RegistrationRole.STUDENT
    )
    account_status = models.CharField(
        max_length=16,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
    )
    password = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    last_login_at = models.DateTimeField(null=True, blank=True)
    security_version = models.PositiveBigIntegerField(default=1, editable=False)

    def __str__(self) -> str:
        return self.username

    class Meta:
        db_table = "accounts_user"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(account_status__in=("ACTIVE", "DISABLED")),
                name="accounts_user_status_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(account_status="ACTIVE", is_active=True)
                    | models.Q(account_status="DISABLED", is_active=False)
                ),
                name="accounts_user_active_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("account_status",), name="accounts_user_status_idx"),
        ]

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_username(self) -> str:
        return self.username


class IdentityVerification(VersionedModel):
    class IdentityType(models.TextChoices):
        SCHOOL = "SCHOOL"
        ENTERPRISE = "ENTERPRISE"

    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        SUBMITTED = "SUBMITTED"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"

    public_id = models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )
    user = models.OneToOneField(
        User,
        on_delete=models.PROTECT,
        related_name="identity_verification",
    )
    identity_type = models.CharField(
        max_length=16,
        choices=IdentityType.choices,
        default=IdentityType.SCHOOL,
    )
    organization_name = models.CharField(max_length=128, blank=True, default="")
    identity_number_hmac = models.CharField(max_length=64, blank=True, default="")
    identity_number_masked = models.CharField(max_length=64, blank=True, default="")
    material_asset = models.ForeignKey(
        ObjectAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="identity_verifications",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_identity_verifications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "accounts_identity_verification"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(identity_type__in=("SCHOOL", "ENTERPRISE")),
                name="accounts_identity_type_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")),
                name="accounts_identity_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "updated_at"), name="accounts_identity_status_idx"),
        ]


class TeacherQualification(VersionedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        ACTIVE = "ACTIVE"
        REJECTED = "REJECTED"
        SUSPENDED = "SUSPENDED"
        REVOKED = "REVOKED"

    public_id = models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )
    user = models.OneToOneField(
        User,
        on_delete=models.PROTECT,
        related_name="teacher_qualification",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="granted_teacher_qualifications",
    )
    granted_at = models.DateTimeField(null=True, blank=True)
    suspended_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suspended_teacher_qualifications",
    )
    suspended_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_teacher_qualifications",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=255)

    class Meta:
        db_table = "accounts_teacher_qualification"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("PENDING", "ACTIVE", "REJECTED", "SUSPENDED", "REVOKED")
                ),
                name="accounts_teacher_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "updated_at"), name="accounts_teacher_status_idx"),
        ]


class TeacherQualificationEvent(AppendOnlyModel):
    qualification = models.ForeignKey(
        TeacherQualification,
        on_delete=models.PROTECT,
        related_name="events",
    )
    from_status = models.CharField(max_length=16, blank=True, default="")
    to_status = models.CharField(max_length=16)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    reason = models.CharField(max_length=255)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "accounts_teacher_qualification_event"
        indexes = [
            models.Index(
                fields=("qualification", "created_at"),
                name="accounts_teacher_event_idx",
            ),
        ]


class PlatformAdminAssignment(VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        REVOKED = "REVOKED"

    public_id = models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )
    user = models.OneToOneField(User, on_delete=models.PROTECT, related_name="admin_assignment")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="granted_admin_assignments",
    )
    granted_at = models.DateTimeField()
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_admin_assignments",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=255)

    class Meta:
        db_table = "accounts_platform_admin_assignment"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "REVOKED")),
                name="accounts_admin_status_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "updated_at"), name="accounts_admin_status_idx"),
        ]


class PlatformAdminAssignmentEvent(AppendOnlyModel):
    assignment = models.ForeignKey(
        PlatformAdminAssignment,
        on_delete=models.PROTECT,
        related_name="events",
    )
    from_status = models.CharField(max_length=16, blank=True, default="")
    to_status = models.CharField(max_length=16)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    reason = models.CharField(max_length=255)
    trace_id = models.CharField(max_length=32)

    class Meta:
        db_table = "accounts_platform_admin_assignment_event"
        indexes = [
            models.Index(
                fields=("assignment", "created_at"),
                name="accounts_admin_event_idx",
            ),
        ]


class PendingRegistration(models.Model):
    email = models.EmailField(max_length=254, unique=True)
    username = models.CharField(max_length=32)
    display_name = models.CharField(max_length=64)
    password_hash = models.CharField(max_length=128)
    role = models.CharField(max_length=16, choices=User.RegistrationRole.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_pending_registration"

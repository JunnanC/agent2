from rest_framework import serializers

from .models import IdentityVerification, PlatformAdminAssignment, TeacherQualification, User


class AccountTraceMetaSerializer(serializers.Serializer):
    trace_id = serializers.CharField()


class AccountPageMetaSerializer(AccountTraceMetaSerializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()


class LoginInputSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class CsrfDataSerializer(serializers.Serializer):
    csrf = serializers.CharField()


class CsrfResponseSerializer(serializers.Serializer):
    data = CsrfDataSerializer()
    meta = AccountTraceMetaSerializer()


class ProfileUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=64)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class UserCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    username = serializers.RegexField(r"^[A-Za-z0-9._-]{3,32}$", max_length=32)
    display_name = serializers.CharField(max_length=64)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class UserStatusUpdateSerializer(serializers.Serializer):
    account_status = serializers.ChoiceField(choices=User.AccountStatus.choices)
    reason = serializers.CharField(max_length=255)


class QualificationGrantSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class TeacherQualificationUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=(TeacherQualification.Status.SUSPENDED, TeacherQualification.Status.REVOKED)
    )
    reason = serializers.CharField(max_length=255)


class AdminAssignmentUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=(PlatformAdminAssignment.Status.REVOKED,))
    reason = serializers.CharField(max_length=255)


class IdentityVerificationUpdateSerializer(serializers.Serializer):
    identity_type = serializers.ChoiceField(choices=IdentityVerification.IdentityType.choices)
    organization_name = serializers.CharField(max_length=128)
    identity_number = serializers.CharField(min_length=4, max_length=64, write_only=True)
    material_asset_id = serializers.CharField(max_length=26, allow_blank=True, required=False)
    submit = serializers.BooleanField(default=False)


class IdentityReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=("APPROVE", "REJECT"))
    reason = serializers.CharField(max_length=255, allow_blank=True, required=False)

    def validate(self, attrs: dict) -> dict:
        if attrs["decision"] == "REJECT" and not attrs.get("reason", "").strip():
            raise serializers.ValidationError({"reason": "拒绝时必须填写原因"})
        return attrs


class UserDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    email = serializers.EmailField()
    username = serializers.CharField()
    display_name = serializers.CharField()
    account_status = serializers.CharField()
    row_version = serializers.IntegerField()


class MeDataSerializer(UserDataSerializer):
    portal = serializers.CharField()
    eligible_portals = serializers.ListField(child=serializers.CharField())
    teacher_qualification = serializers.CharField(allow_null=True)
    platform_admin_assignment = serializers.CharField(allow_null=True)
    permissions = serializers.ListField(child=serializers.CharField())
    course_scopes = serializers.ListField(child=serializers.DictField())


class VerificationDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    user_id = serializers.CharField()
    identity_type = serializers.CharField()
    organization_name = serializers.CharField()
    identity_number_masked = serializers.CharField()
    material_asset_id = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    submitted_at = serializers.DateTimeField(allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)
    review_reason = serializers.CharField()
    row_version = serializers.IntegerField()


class QualificationDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    user_id = serializers.CharField()
    display_name = serializers.CharField()
    status = serializers.CharField()
    reason = serializers.CharField()
    granted_at = serializers.DateTimeField()
    suspended_at = serializers.DateTimeField(allow_null=True)
    revoked_at = serializers.DateTimeField(allow_null=True)
    row_version = serializers.IntegerField()


class AdminAssignmentDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    user_id = serializers.CharField()
    display_name = serializers.CharField()
    status = serializers.CharField()
    reason = serializers.CharField()
    granted_at = serializers.DateTimeField()
    revoked_at = serializers.DateTimeField(allow_null=True)
    row_version = serializers.IntegerField()


class MeResponseSerializer(serializers.Serializer):
    data = MeDataSerializer()
    meta = AccountTraceMetaSerializer()


class UserResponseSerializer(serializers.Serializer):
    data = UserDataSerializer()
    meta = AccountTraceMetaSerializer()


class VerificationResponseSerializer(serializers.Serializer):
    data = VerificationDataSerializer()
    meta = AccountTraceMetaSerializer()


class QualificationResponseSerializer(serializers.Serializer):
    data = QualificationDataSerializer()
    meta = AccountTraceMetaSerializer()


class AdminAssignmentResponseSerializer(serializers.Serializer):
    data = AdminAssignmentDataSerializer()
    meta = AccountTraceMetaSerializer()


class UserListResponseSerializer(serializers.Serializer):
    data = UserDataSerializer(many=True)
    meta = AccountPageMetaSerializer()


class QualificationListResponseSerializer(serializers.Serializer):
    data = QualificationDataSerializer(many=True)
    meta = AccountPageMetaSerializer()


class AdminAssignmentListResponseSerializer(serializers.Serializer):
    data = AdminAssignmentDataSerializer(many=True)
    meta = AccountPageMetaSerializer()


class VerificationListResponseSerializer(serializers.Serializer):
    data = VerificationDataSerializer(many=True)
    meta = AccountPageMetaSerializer()


def user_data(user: User) -> dict[str, object]:
    return {
        "public_id": user.public_id,
        "email": user.email,
        "username": user.username,
        "display_name": user.display_name,
        "account_status": user.account_status,
        "row_version": user.row_version,
    }


def verification_data(verification: IdentityVerification) -> dict[str, object]:
    return {
        "public_id": verification.public_id,
        "user_id": verification.user.public_id,
        "identity_type": verification.identity_type,
        "organization_name": verification.organization_name,
        "identity_number_masked": verification.identity_number_masked,
        "material_asset_id": (
            str(verification.material_asset.public_id) if verification.material_asset else ""
        ),
        "status": verification.status,
        "submitted_at": verification.submitted_at,
        "reviewed_at": verification.reviewed_at,
        "review_reason": verification.review_reason,
        "row_version": verification.row_version,
    }


def qualification_data(qualification: TeacherQualification) -> dict[str, object]:
    return {
        "public_id": qualification.public_id,
        "user_id": qualification.user.public_id,
        "display_name": qualification.user.display_name,
        "status": qualification.status,
        "reason": qualification.reason,
        "granted_at": qualification.granted_at,
        "suspended_at": qualification.suspended_at,
        "revoked_at": qualification.revoked_at,
        "row_version": qualification.row_version,
    }


def admin_assignment_data(assignment: PlatformAdminAssignment) -> dict[str, object]:
    return {
        "public_id": assignment.public_id,
        "user_id": assignment.user.public_id,
        "display_name": assignment.user.display_name,
        "status": assignment.status,
        "reason": assignment.reason,
        "granted_at": assignment.granted_at,
        "revoked_at": assignment.revoked_at,
        "row_version": assignment.row_version,
    }

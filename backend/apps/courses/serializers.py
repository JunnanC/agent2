from rest_framework import serializers

from .models import Course, CourseStaff, CourseStaffGrant, Enrollment
from .ports import Blocker


class CourseCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64, required=False, allow_blank=True)
    title = serializers.CharField(max_length=160)
    summary = serializers.CharField(max_length=500, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    visibility = serializers.ChoiceField(choices=Course.Visibility.choices)
    enrollment_mode = serializers.ChoiceField(
        choices=Course.EnrollmentMode.choices, required=False, default="APPROVAL"
    )
    capacity = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    enrollment_start = serializers.DateTimeField(required=False, allow_null=True)
    enrollment_end = serializers.DateTimeField(required=False, allow_null=True)
    teaching_start = serializers.DateTimeField(required=False, allow_null=True)
    teaching_end = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        for start_name, end_name in (
            ("enrollment_start", "enrollment_end"),
            ("teaching_start", "teaching_end"),
        ):
            start = attrs.get(start_name)
            end = attrs.get(end_name)
            if start is not None and end is not None and end <= start:  # type: ignore[operator]
                raise serializers.ValidationError({end_name: "结束时间必须晚于开始时间"})
        return attrs


class CourseUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160, required=False)
    summary = serializers.CharField(max_length=500, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    visibility = serializers.ChoiceField(choices=Course.Visibility.choices, required=False)
    enrollment_mode = serializers.ChoiceField(
        choices=Course.EnrollmentMode.choices,
        required=False,
    )
    capacity = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    enrollment_start = serializers.DateTimeField(required=False, allow_null=True)
    enrollment_end = serializers.DateTimeField(required=False, allow_null=True)
    teaching_start = serializers.DateTimeField(required=False, allow_null=True)
    teaching_end = serializers.DateTimeField(required=False, allow_null=True)

    def validate_enrollment_mode(self, value):
        return Course.EnrollmentMode.APPROVAL


class OwnershipTransferSerializer(serializers.Serializer):
    new_owner_id = serializers.CharField(max_length=26)
    reason = serializers.CharField(max_length=255)


class StaffCreateSerializer(serializers.Serializer):
    user_id = serializers.CharField(max_length=26)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class GrantCreateSerializer(serializers.Serializer):
    capability = serializers.ChoiceField(choices=CourseStaffGrant.Capability.choices)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


class EnrollmentApplySerializer(serializers.Serializer):
    application_message = serializers.CharField(
        max_length=2000,
        required=False,
        allow_blank=True,
    )
    invitation_code = serializers.CharField(max_length=128, required=False, allow_blank=True)


class EnrollmentReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=("APPROVE", "REJECT"))
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)


class CourseTraceMetaSerializer(serializers.Serializer):
    trace_id = serializers.CharField()


class ContextCourseDataSerializer(serializers.Serializer):
    id = serializers.CharField()
    code = serializers.CharField()
    title = serializers.CharField()
    status = serializers.CharField()
    staff_role = serializers.CharField(required=False)
    enrollment_role = serializers.CharField(required=False)


class ContextTermDataSerializer(serializers.Serializer):
    id = serializers.CharField()
    code = serializers.CharField()
    name = serializers.CharField()
    status = serializers.CharField()


class ContextDataSerializer(serializers.Serializer):
    user_role = serializers.ChoiceField(choices=("TEACHER", "STUDENT", "PLATFORM_ADMIN"))
    current_term = ContextTermDataSerializer()
    courses = ContextCourseDataSerializer(many=True)


class CoursePageMetaSerializer(CourseTraceMetaSerializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()


class CourseDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    code = serializers.CharField()
    title = serializers.CharField()
    summary = serializers.CharField()
    description = serializers.CharField()
    owner_id = serializers.CharField()
    owner_name = serializers.CharField()
    status = serializers.CharField()
    visibility = serializers.CharField()
    enrollment_mode = serializers.CharField()
    capacity = serializers.IntegerField(allow_null=True)
    active_enrollment_count = serializers.IntegerField()
    enrollment_start = serializers.DateTimeField(allow_null=True)
    enrollment_end = serializers.DateTimeField(allow_null=True)
    teaching_start = serializers.DateTimeField(allow_null=True)
    teaching_end = serializers.DateTimeField(allow_null=True)
    row_version = serializers.IntegerField()


class GrantDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    capability = serializers.CharField()
    status = serializers.CharField()
    expires_at = serializers.DateTimeField(allow_null=True)
    row_version = serializers.IntegerField()


class StaffDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    user_id = serializers.CharField()
    display_name = serializers.CharField()
    role = serializers.CharField()
    status = serializers.CharField()
    grants = GrantDataSerializer(many=True)
    row_version = serializers.IntegerField()


class EnrollmentEventDataSerializer(serializers.Serializer):
    from_status = serializers.CharField()
    to_status = serializers.CharField()
    reason_code = serializers.CharField()
    blockers = serializers.ListField(child=serializers.DictField())
    created_at = serializers.DateTimeField()


class EnrollmentDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    course_id = serializers.CharField()
    course_code = serializers.CharField()
    course_title = serializers.CharField()
    student_id = serializers.CharField()
    student_name = serializers.CharField()
    cycle_no = serializers.IntegerField()
    status = serializers.CharField()
    application_message = serializers.CharField()
    applied_at = serializers.DateTimeField()
    reviewed_at = serializers.DateTimeField(allow_null=True)
    activated_at = serializers.DateTimeField(allow_null=True)
    ended_at = serializers.DateTimeField(allow_null=True)
    decision_note = serializers.CharField()
    end_reason = serializers.CharField()
    row_version = serializers.IntegerField()
    events = EnrollmentEventDataSerializer(many=True, required=False)


class BlockerDataSerializer(serializers.Serializer):
    type = serializers.CharField()
    count = serializers.IntegerField()
    refs = serializers.ListField(child=serializers.CharField())
    message = serializers.CharField()


class CheckDataSerializer(serializers.Serializer):
    allowed = serializers.BooleanField()
    blockers = BlockerDataSerializer(many=True)


class CourseResponseSerializer(serializers.Serializer):
    data = CourseDataSerializer()
    meta = CourseTraceMetaSerializer()


class ContextResponseSerializer(serializers.Serializer):
    data = ContextDataSerializer()
    meta = CourseTraceMetaSerializer()


class CourseListResponseSerializer(serializers.Serializer):
    data = CourseDataSerializer(many=True)
    meta = CoursePageMetaSerializer()


class StaffResponseSerializer(serializers.Serializer):
    data = StaffDataSerializer()
    meta = CourseTraceMetaSerializer()


class StaffListResponseSerializer(serializers.Serializer):
    data = StaffDataSerializer(many=True)
    meta = CourseTraceMetaSerializer()


class GrantResponseSerializer(serializers.Serializer):
    data = GrantDataSerializer()
    meta = CourseTraceMetaSerializer()


class GrantListResponseSerializer(serializers.Serializer):
    data = GrantDataSerializer(many=True)
    meta = CourseTraceMetaSerializer()


class EnrollmentResponseSerializer(serializers.Serializer):
    data = EnrollmentDataSerializer()
    meta = CourseTraceMetaSerializer()


class EnrollmentListResponseSerializer(serializers.Serializer):
    data = EnrollmentDataSerializer(many=True)
    meta = CoursePageMetaSerializer()


class CheckResponseSerializer(serializers.Serializer):
    data = CheckDataSerializer()
    meta = CourseTraceMetaSerializer()


def course_data(course: Course) -> dict[str, object]:
    active_count = course.enrollments.filter(status=Enrollment.Status.ACTIVE).count()
    return {
        "public_id": course.public_id,
        "code": course.code,
        "title": course.title,
        "summary": course.summary,
        "description": course.description,
        "owner_id": course.owner.public_id,
        "owner_name": course.owner.display_name,
        "status": course.status,
        "visibility": course.visibility,
        "enrollment_mode": course.enrollment_mode,
        "capacity": course.capacity,
        "active_enrollment_count": active_count,
        "enrollment_start": course.enrollment_start,
        "enrollment_end": course.enrollment_end,
        "teaching_start": course.teaching_start,
        "teaching_end": course.teaching_end,
        "row_version": course.row_version,
    }


def grant_data(grant: CourseStaffGrant) -> dict[str, object]:
    return {
        "public_id": grant.public_id,
        "capability": grant.capability,
        "status": grant.status,
        "expires_at": grant.expires_at,
        "row_version": grant.row_version,
    }


def staff_data(staff: CourseStaff) -> dict[str, object]:
    return {
        "public_id": staff.public_id,
        "user_id": staff.user.public_id,
        "display_name": staff.user.display_name,
        "role": staff.role,
        "status": staff.status,
        "grants": [grant_data(item) for item in staff.grants.all().order_by("capability")],
        "row_version": staff.row_version,
    }


def enrollment_data(enrollment: Enrollment, *, include_events: bool = False) -> dict[str, object]:
    result: dict[str, object] = {
        "public_id": enrollment.public_id,
        "course_id": enrollment.course.public_id,
        "course_code": enrollment.course.code,
        "course_title": enrollment.course.title,
        "student_id": enrollment.student.public_id,
        "student_name": enrollment.student.display_name,
        "cycle_no": enrollment.cycle_no,
        "status": enrollment.status,
        "application_message": enrollment.application_message,
        "applied_at": enrollment.applied_at,
        "reviewed_at": enrollment.reviewed_at,
        "activated_at": enrollment.activated_at,
        "ended_at": enrollment.ended_at,
        "decision_note": enrollment.decision_note,
        "end_reason": enrollment.end_reason,
        "row_version": enrollment.row_version,
    }
    if include_events:
        result["events"] = [
            {
                "from_status": event.from_status,
                "to_status": event.to_status,
                "reason_code": event.reason_code,
                "blockers": event.blockers_snapshot,
                "created_at": event.created_at,
            }
            for event in enrollment.events.all().order_by("id")
        ]
    return result


def check_data(blockers: list[Blocker]) -> dict[str, object]:
    return {
        "allowed": not blockers,
        "blockers": [item.as_dict() for item in blockers],
    }

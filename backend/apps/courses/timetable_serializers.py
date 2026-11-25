from rest_framework import serializers


class TimetableUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    term_id = serializers.CharField(max_length=26, required=False, allow_blank=True)


class TimetableMappingSerializer(serializers.Serializer):
    mapping = serializers.DictField(child=serializers.CharField())


class AdministrativeClassWriteSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=160)
    department = serializers.CharField(max_length=160, required=False, allow_blank=True)
    year_of_entry = serializers.IntegerField(min_value=1900, max_value=2200, required=False)


class AdministrativeClassMemberWriteSerializer(serializers.Serializer):
    student_id = serializers.CharField(max_length=26)


class GenericTimetableResponseSerializer(serializers.Serializer):
    data = serializers.JSONField()
    meta = serializers.DictField(child=serializers.JSONField(), required=False)


class TimetableCalendarSerializer(serializers.Serializer):
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()


class TimetableTermSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    code = serializers.CharField()
    name = serializers.CharField()
    calendar = TimetableCalendarSerializer(allow_null=True)


class TimetableClassSerializer(serializers.Serializer):
    course_id = serializers.CharField()
    course_code = serializers.CharField()
    course_title = serializers.CharField()
    instructor_name = serializers.CharField(allow_blank=True)


class TimetableScheduleSerializer(TimetableClassSerializer):
    source = serializers.ChoiceField(choices=["PLATFORM"])
    class_type = serializers.ChoiceField(choices=["TEACHING"])
    term_id = serializers.CharField()
    weekday = serializers.IntegerField()
    start_period = serializers.IntegerField()
    end_period = serializers.IntegerField()
    week_start = serializers.IntegerField(allow_null=True)
    week_end = serializers.IntegerField(allow_null=True)
    week_parity = serializers.ChoiceField(choices=["ALL", "ODD", "EVEN"])
    classroom = serializers.CharField(allow_blank=True)


class TermTimetableDataSerializer(serializers.Serializer):
    term = TimetableTermSerializer()
    terms = TimetableTermSerializer(many=True)
    classes = TimetableClassSerializer(many=True)
    total = serializers.IntegerField(required=False)
    schedules = TimetableScheduleSerializer(many=True)


class TermTimetableResponseSerializer(GenericTimetableResponseSerializer):
    data = TermTimetableDataSerializer()


class TeachingCourseTimetableDataSerializer(serializers.Serializer):
    course_id = serializers.CharField()
    class_type = serializers.ChoiceField(choices=["TEACHING"])
    term = TimetableTermSerializer()
    schedules = TimetableScheduleSerializer(many=True)


class TeachingCourseTimetableResponseSerializer(GenericTimetableResponseSerializer):
    data = TeachingCourseTimetableDataSerializer()

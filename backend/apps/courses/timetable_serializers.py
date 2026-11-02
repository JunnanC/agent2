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

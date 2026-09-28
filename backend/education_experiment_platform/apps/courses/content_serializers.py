from rest_framework import serializers


class ContentWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180, required=False)
    summary = serializers.CharField(max_length=500, required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)
    position = serializers.IntegerField(required=False, min_value=1)
    kind = serializers.ChoiceField(choices=("FILE", "LINK", "TEXT"), required=False)
    text_content = serializers.CharField(required=False, allow_blank=True)
    link_url = serializers.URLField(required=False, allow_blank=True)
    object_asset_id = serializers.CharField(max_length=26, required=False, allow_blank=True)
    pinned = serializers.BooleanField(required=False)


class StatusActionSerializer(serializers.Serializer):
    status = serializers.CharField(max_length=16)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class CalendarWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180)
    description = serializers.CharField(required=False, allow_blank=True)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class QuestionWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180)
    body = serializers.CharField()


class AnswerWriteSerializer(serializers.Serializer):
    body = serializers.CharField()


class InvitationWriteSerializer(serializers.Serializer):
    max_uses = serializers.IntegerField(min_value=1, max_value=1000000)
    expires_at = serializers.DateTimeField()


class ImportRowSerializer(serializers.Serializer):
    csv = serializers.CharField(required=False)


class CopyWriteSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64, required=False, allow_blank=True)
    title = serializers.CharField(max_length=160, required=False, allow_blank=True)
    include_announcements = serializers.BooleanField(required=False, default=True)
    include_calendar = serializers.BooleanField(required=False, default=True)
    include_templates = serializers.BooleanField(required=False, default=True)
    include_rubrics = serializers.BooleanField(required=False, default=True)
    include_agents = serializers.BooleanField(required=False, default=True)


class CourseContentResponseSerializer(serializers.Serializer):
    data = serializers.DictField()
    meta = serializers.DictField()


class CourseContentListResponseSerializer(serializers.Serializer):
    data = serializers.ListField(child=serializers.DictField())
    meta = serializers.DictField()

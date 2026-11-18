from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.core.idempotency import StoredResponse

from .permissions import IsPlatformPortal
from .student_imports import import_students
from .views import _context, _idempotent_response, _meta


class StudentImportInputSerializer(serializers.Serializer):
    csv = serializers.CharField(max_length=1024 * 1024, trim_whitespace=False, write_only=True)


class StudentImportRowSerializer(serializers.Serializer):
    row_number = serializers.IntegerField()
    student_number = serializers.CharField()
    status = serializers.ChoiceField(choices=["CREATED", "FAILED"])
    user_id = serializers.CharField(required=False)
    error = serializers.CharField(required=False)


class StudentImportDataSerializer(serializers.Serializer):
    rows = StudentImportRowSerializer(many=True)


class StudentImportResponseSerializer(serializers.Serializer):
    data = StudentImportDataSerializer()
    meta = serializers.DictField()


class PlatformStudentImportView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_student_import",
        request=StudentImportInputSerializer,
        responses={200: StudentImportResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request):
        serializer = StudentImportInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation():
            rows = import_students(
                csv_payload=serializer.validated_data["csv"], context=_context(request)
            )
            return StoredResponse(200, {"data": {"rows": rows}, "meta": _meta(request)}, {})

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)

from typing import Any

from rest_framework import serializers

from apps.core.models import CompensationTask

from .models import ArchiveJob


class ArchiveDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    course_id = serializers.CharField()
    student_id = serializers.CharField()
    student_name = serializers.CharField()
    status = serializers.CharField()
    terminal_target = serializers.CharField()
    task_status = serializers.CharField()
    attempt_count = serializers.IntegerField()
    max_attempts = serializers.IntegerField()
    row_version = serializers.IntegerField()
    failure = serializers.DictField(allow_null=True)
    compensation = serializers.DictField(allow_null=True)
    manifest = serializers.DictField(allow_null=True)
    verifications = serializers.ListField(child=serializers.DictField())
    recycle = serializers.DictField()


class ArchiveResponseSerializer(serializers.Serializer):
    data = ArchiveDataSerializer()
    meta = serializers.DictField()


class ArchiveListResponseSerializer(serializers.Serializer):
    data = ArchiveDataSerializer(many=True)
    meta = serializers.DictField()


class ArchiveExportResponseSerializer(serializers.Serializer):
    data = serializers.DictField()
    meta = serializers.DictField()


class CompensationRetrySerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000)
    compensation_id = serializers.CharField(max_length=26)


class CompensationDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_type = serializers.CharField()
    subject_type = serializers.CharField()
    subject_ref = serializers.CharField()
    status = serializers.CharField()
    attempt_count = serializers.IntegerField()
    max_attempts = serializers.IntegerField()
    next_attempt_at = serializers.DateTimeField(allow_null=True)
    error_code = serializers.CharField()
    trace_id = serializers.CharField()
    row_version = serializers.IntegerField()


class CompensationListResponseSerializer(serializers.Serializer):
    data = CompensationDataSerializer(many=True)
    meta = serializers.DictField()


class CompensationResponseSerializer(serializers.Serializer):
    data = CompensationDataSerializer()
    meta = serializers.DictField()


def archive_data(job: ArchiveJob) -> dict[str, Any]:
    manifest = getattr(job, "manifest", None)
    failure = job.failure_record
    compensation = job.compensation_task
    return {
        "public_id": job.public_id,
        "task_id": job.task.public_id,
        "course_id": job.course.public_id,
        "student_id": job.task.student.public_id,
        "student_name": job.task.student.display_name,
        "status": job.status,
        "terminal_target": job.terminal_target,
        "task_status": job.task.status,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "row_version": job.row_version,
        "failure": (
            {
                "error_code": failure.error_code,
                "message": failure.message_masked,
                "retryable": failure.retryable,
                "trace_id": failure.trace_id,
            }
            if failure
            else None
        ),
        "compensation": (
            {
                "public_id": compensation.public_id,
                "status": compensation.status,
                "attempt_count": compensation.attempt_count,
                "max_attempts": compensation.max_attempts,
            }
            if compensation
            else None
        ),
        "manifest": (
            {
                "public_id": manifest.public_id,
                "manifest_digest": manifest.manifest_digest,
                "package_digest": manifest.package_digest,
                "object_count": manifest.object_count,
                "total_size_bytes": manifest.total_size_bytes,
                "retention_until": manifest.retention_until,
                "entries": manifest.entries,
                "asset": {
                    "public_id": manifest.package_asset.public_id,
                    "original_name": manifest.package_asset.original_name,
                    "media_type": manifest.package_asset.media_type,
                    "size_bytes": manifest.package_asset.size_bytes,
                },
            }
            if manifest
            else None
        ),
        "verifications": [
            {
                "public_id": item.public_id,
                "attempt_no": item.attempt_no,
                "result": item.result,
                "checks": item.checks,
                "expected_digest": item.expected_digest,
                "actual_digest": item.actual_digest,
                "error_code": item.error_code,
                "verified_at": item.verified_at,
                "trace_id": item.trace_id,
            }
            for item in sorted(
                job.verifications.all(), key=lambda value: (value.created_at, value.pk)
            )
        ],

    }


def compensation_data(item: CompensationTask) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "task_type": item.task_type,
        "subject_type": item.subject_type,
        "subject_ref": item.subject_ref,
        "status": item.status,
        "attempt_count": item.attempt_count,
        "max_attempts": item.max_attempts,
        "next_attempt_at": item.next_attempt_at,
        "error_code": item.last_failure.error_code if item.last_failure else "",
        "trace_id": item.trace_id,
        "row_version": item.row_version,
    }

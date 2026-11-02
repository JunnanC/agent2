from rest_framework import serializers

from .models import ProvisioningJob, ProvisioningStageEvent


class ProvisioningStageEventSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    stage = serializers.ChoiceField(choices=ProvisioningJob.Stage.choices)
    status = serializers.ChoiceField(choices=ProvisioningStageEvent.Status.choices)
    attempt_no = serializers.IntegerField()
    detail = serializers.DictField()
    error_code = serializers.CharField()
    trace_id = serializers.CharField()
    started_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)


class ProvisioningJobSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    course_id = serializers.CharField()
    status = serializers.ChoiceField(choices=ProvisioningJob.Status.choices)
    current_stage = serializers.CharField()
    attempt_no = serializers.IntegerField()
    attempt_count = serializers.IntegerField()
    retryable = serializers.BooleanField()
    trace_id = serializers.CharField()
    reservation = serializers.DictField()
    instance = serializers.DictField(allow_null=True)
    stages = ProvisioningStageEventSerializer(many=True)
    failure = serializers.DictField(allow_null=True)
    events_channel = serializers.CharField()
    row_version = serializers.IntegerField()


class ProvisioningActionResponseSerializer(serializers.Serializer):
    job_id = serializers.CharField()
    subject_id = serializers.CharField()
    status = serializers.ChoiceField(choices=ProvisioningJob.Status.choices)
    events_channel = serializers.CharField()


def stage_data(item: ProvisioningStageEvent) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "stage": item.stage,
        "status": item.status,
        "attempt_no": item.attempt_no,
        "detail": item.detail_masked,
        "error_code": item.error_code,
        "trace_id": item.trace_id,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
    }


def job_data(job: ProvisioningJob) -> dict[str, object]:
    instance = getattr(job.task, "provisioning_instance", None)
    failure = None
    if job.failure_record is not None:
        failure = {
            "error_code": job.failure_record.error_code,
            "message": job.failure_record.message_masked,
            "detail": job.failure_record.detail_masked,
            "retryable": job.failure_record.retryable,
            "trace_id": job.failure_record.trace_id,
        }
    return {
        "public_id": job.public_id,
        "task_id": job.task.public_id,
        "course_id": job.course.public_id,
        "status": job.status,
        "current_stage": job.current_stage,
        "attempt_no": job.attempt_no,
        "attempt_count": job.attempt_count,
        "retryable": job.retryable,
        "trace_id": job.trace_id,
        "reservation": {
            "public_id": job.reservation.public_id,
            "status": job.reservation.status,
            "instance_count": job.reservation.instance_count,
            "cpu_millicores": job.reservation.cpu_millicores,
            "memory_mb": job.reservation.memory_mb,
            "disk_gb": job.reservation.disk_gb,
        },
        "instance": (
            {
                "public_id": instance.public_id,
                "status": instance.status,
                "runtime_type": instance.runtime_type,
                "external_id": instance.external_id or None,
                "endpoint": instance.endpoint if instance.status == "READY" else "",
            }
            if instance is not None
            else None
        ),
        "stages": [
            stage_data(event) for event in job.stage_events.all().order_by("created_at", "id")
        ],
        "failure": failure,
        "events_channel": f"task:{job.task.public_id}",
        "row_version": job.row_version,
    }


def action_data(job: ProvisioningJob) -> dict[str, object]:
    return {
        "job_id": job.public_id,
        "subject_id": job.task.public_id,
        "status": job.status,
        "events_channel": f"task:{job.task.public_id}",
    }

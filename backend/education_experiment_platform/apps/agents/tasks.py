import hashlib
from typing import Any

from celery import shared_task
from django.utils import timezone

from apps.core.concurrency import compare_and_swap

from .services import execute_eval_run, execute_tool_call, process_agent_message


@shared_task(bind=True, acks_late=True, queue="q_content")
def run_ingestion(self: Any, run_id: str, trace_id: str = "") -> str:
    from .adapters import KeywordKnowledgeRetriever
    from .models import AgentSourceVersion, IngestionRun

    run = IngestionRun.objects.select_related("source_version").get(public_id=run_id)
    running = compare_and_swap(
        IngestionRun,
        pk=run.pk,
        expected_version=run.row_version,
        changes={"status": IngestionRun.Status.RUNNING, "started_at": timezone.now()},
    )
    try:
        count = KeywordKnowledgeRetriever().rebuild(
            source_version_id=running.source_version.public_id
        )
        completed = compare_and_swap(
            IngestionRun,
            pk=running.pk,
            expected_version=running.row_version,
            changes={
                "status": IngestionRun.Status.SUCCEEDED,
                "chunk_count": count,
                "indexed_count": count,
                "completed_at": timezone.now(),
            },
        )
        source_version = AgentSourceVersion.objects.get(pk=completed.source_version_id)
        compare_and_swap(
            AgentSourceVersion,
            pk=source_version.pk,
            expected_version=source_version.row_version,
            changes={"status": AgentSourceVersion.Status.INDEXED, "indexed_at": timezone.now()},
        )
        source = source_version.source
        compare_and_swap(
            type(source),
            pk=source.pk,
            expected_version=source.row_version,
            changes={"status": source.Status.ACTIVE},
        )
        knowledge_base = source.knowledge_base
        if knowledge_base.status == knowledge_base.Status.DRAFT:
            compare_and_swap(
                type(knowledge_base),
                pk=knowledge_base.pk,
                expected_version=knowledge_base.row_version,
                changes={"status": knowledge_base.Status.ACTIVE},
            )
    except Exception:
        current_run = IngestionRun.objects.get(pk=run.pk)
        compare_and_swap(
            IngestionRun,
            pk=current_run.pk,
            expected_version=current_run.row_version,
            changes={
                "status": IngestionRun.Status.FAILED,
                "error_code": "AGENT_INGESTION_FAILED",
                "completed_at": timezone.now(),
            },
        )
        current_version = AgentSourceVersion.objects.get(pk=run.source_version_id)
        compare_and_swap(
            AgentSourceVersion,
            pk=current_version.pk,
            expected_version=current_version.row_version,
            changes={"status": AgentSourceVersion.Status.FAILED},
        )
        raise
    return run.public_id


@shared_task(bind=True, acks_late=True, queue="q_content")
def scan_agent_source_asset(self: Any, asset_id: str, trace_id: str = "") -> str:
    from .assets import scan_source_asset

    return scan_source_asset(asset_id=asset_id, trace_id=trace_id).public_id


@shared_task(bind=True, acks_late=True, queue="q_agent")
def run_agent_message(self: Any, message_id: str, trace_id: str = "") -> str:
    try:
        return process_agent_message(message_id=message_id, trace_id=trace_id).public_id
    except Exception:
        from .models import AgentMessage

        source = AgentMessage.objects.select_related("session").get(
            public_id=message_id, role=AgentMessage.Role.USER
        )
        failure = AgentMessage.objects.filter(
            reply_to=source, role=AgentMessage.Role.ASSISTANT
        ).first()
        if failure is None:
            body = "Agent 服务暂时不可用，请稍后重试。"
            failure = AgentMessage.objects.create(
                session=source.session,
                reply_to=source,
                role=AgentMessage.Role.ASSISTANT,
                body=body,
                body_digest=hashlib.sha256(body.encode()).hexdigest(),
                status=AgentMessage.Status.FAILED,
                error_code="AGENT_MODEL_UNAVAILABLE",
                trace_id=trace_id,
            )
        raise


@shared_task(bind=True, acks_late=True, queue="q_agent")
def execute_agent_tool(self: Any, call_id: str, trace_id: str = "") -> str:
    return execute_tool_call(call_id=call_id, trace_id=trace_id).public_id


@shared_task(bind=True, acks_late=True, queue="q_agent")
def run_agent_eval(self: Any, run_id: str, trace_id: str = "") -> str:
    return execute_eval_run(run_id=run_id, trace_id=trace_id).public_id

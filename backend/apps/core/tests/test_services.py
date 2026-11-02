from typing import Any

from django.db import transaction
from django.test import TestCase

from apps.core.audit import append_audit, append_failure
from apps.core.compensation import (
    claim_compensations,
    create_compensation,
    register_compensation_handler,
    run_compensation,
)
from apps.core.errors import IdempotencyKeyReused
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.identifiers import normalize_trace_id
from apps.core.models import (
    AuditLog,
    CompensationTask,
    FailureRecord,
    IdempotencyRecord,
    OutboxDelivery,
    OutboxEvent,
)
from apps.core.outbox import (
    append_outbox_event,
    consume_once,
    deliver_claimed,
    enqueue_relay_after_commit,
)
from apps.core.redaction import REDACTED, redact
from apps.core.tasks import TraceTask
from education_experiment_platform.logging import trace_id_var


class FakeRedis:
    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, str]]] = []

    def xadd(
        self,
        stream: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        self.entries.append((stream, fields))
        return "1-0"


class FailingRedis:
    def xadd(self, *args: object, **kwargs: object) -> str:
        raise RuntimeError("token=private-value")


class CaptureTraceTask(TraceTask):
    name = "tests.capture_trace"

    def run(self, *, trace_id: str = "") -> str:
        return trace_id_var.get()


class CoreServiceTests(TestCase):
    def test_trace_ids_longer_than_storage_contract_are_hashed_deterministically(self) -> None:
        oversized = "runtime-failure-" + "x" * 64

        self.assertEqual(len(normalize_trace_id(oversized)), 32)
        self.assertEqual(normalize_trace_id(oversized), normalize_trace_id(oversized))

        audit = append_audit(
            actor_ref="actor-1",
            actor_portal="WORKER",
            actor_context={},
            action="test.trace",
            target_type="test",
            target_ref="trace",
            result="SUCCEEDED",
            trace_id=oversized,
        )
        event = append_outbox_event(
            event_type="test.trace",
            aggregate_type="test",
            aggregate_ref="trace",
            payload={},
            trace_id=oversized,
        )

        self.assertEqual(audit.trace_id, normalize_trace_id(oversized))
        self.assertEqual(event.trace_id, normalize_trace_id(oversized))

    def test_idempotency_replays_exact_response_without_repeating_operation(self) -> None:
        calls = 0

        def operation() -> StoredResponse:
            nonlocal calls
            calls += 1
            return StoredResponse(201, {"data": {"id": "opaque-1"}}, {"ETag": '"1"'})

        arguments: dict[str, Any] = {
            "principal": PrincipalScope("actor-1", "SESSION", "USER"),
            "method": "POST",
            "endpoint": "/api/v2/things",
            "key": "intent-1",
            "payload": {"name": "one"},
            "operation": operation,
        }
        first = execute_idempotent(**arguments)
        second = execute_idempotent(**arguments)

        self.assertEqual(calls, 1)
        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(second.body, first.body)
        self.assertEqual(second.headers, {"ETag": '"1"'})
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_idempotency_rejects_same_scope_and_key_with_different_digest(self) -> None:
        arguments: dict[str, Any] = {
            "principal": PrincipalScope("actor-1", "SESSION", "USER"),
            "method": "POST",
            "endpoint": "/api/v2/things",
            "key": "intent-1",
            "payload": {"name": "one"},
            "operation": lambda: StoredResponse(201, {}, {}),
        }
        execute_idempotent(**arguments)
        arguments["payload"] = {"name": "two"}

        with self.assertRaises(IdempotencyKeyReused):
            execute_idempotent(**arguments)

    def test_transaction_rollback_does_not_leave_outbox_facts(self) -> None:
        with self.assertRaises(RuntimeError), transaction.atomic():
            append_outbox_event(
                event_type="test.created",
                aggregate_type="test",
                aggregate_ref="opaque-1",
                payload={},
                trace_id="c" * 32,
            )
            raise RuntimeError("rollback")

        self.assertEqual(OutboxEvent.objects.count(), 0)
        self.assertEqual(OutboxDelivery.objects.count(), 0)

    def test_relay_serializes_minimal_event_and_marks_delivery(self) -> None:
        event = append_outbox_event(
            event_type="test.created",
            aggregate_type="test",
            aggregate_ref="opaque-1",
            payload={"safe": "visible", "token": "private"},
            trace_id="d" * 32,
        )
        delivery = event.deliveries.get()
        from apps.core.concurrency import compare_and_swap

        delivery = compare_and_swap(
            OutboxDelivery,
            pk=delivery.pk,
            expected_version=1,
            changes={"status": OutboxDelivery.Status.IN_FLIGHT, "attempt_count": 1},
        )
        client = FakeRedis()

        deliver_claimed(delivery.pk, client=client)  # type: ignore[arg-type]

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboxDelivery.Status.DELIVERED)
        self.assertEqual(len(client.entries), 1)
        self.assertIn(str(event.pk), client.entries[0][1]["event_id"])
        self.assertEqual(event.payload["token"], REDACTED)

    def test_consumer_duplicate_delivery_runs_handler_once(self) -> None:
        event = append_outbox_event(
            event_type="test.created",
            aggregate_type="test",
            aggregate_ref="opaque-1",
            payload={},
            trace_id="e" * 32,
        )
        handled: list[str] = []

        first = consume_once(
            event_id=event.pk,
            consumer="test-projection",
            handler=lambda current: handled.append(str(current.pk)),
        )
        second = consume_once(
            event_id=event.pk,
            consumer="test-projection",
            handler=lambda current: handled.append(str(current.pk)),
        )

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(handled, [str(event.pk)])

    def test_relay_failure_records_masked_failure_and_retry_schedule(self) -> None:
        event = append_outbox_event(
            event_type="test.failed",
            aggregate_type="test",
            aggregate_ref="opaque-1",
            payload={},
            trace_id="1" * 32,
        )
        delivery = event.deliveries.get()
        from apps.core.concurrency import compare_and_swap

        delivery = compare_and_swap(
            OutboxDelivery,
            pk=delivery.pk,
            expected_version=1,
            changes={"status": OutboxDelivery.Status.IN_FLIGHT, "attempt_count": 1},
        )

        with self.assertRaises(RuntimeError):
            deliver_claimed(delivery.pk, client=FailingRedis())  # type: ignore[arg-type]

        delivery.refresh_from_db()
        failure = FailureRecord.objects.get(subject_ref=str(event.pk))
        self.assertEqual(delivery.status, OutboxDelivery.Status.RETRY)
        self.assertIsNotNone(delivery.next_attempt_at)
        self.assertNotIn("private-value", failure.message_masked)

    def test_compensation_base_handles_success_and_dead_failure(self) -> None:
        successful_type = "TEST_SUCCESS_HANDLER"
        failed_type = "TEST_FAILED_HANDLER"
        handled: list[str] = []
        register_compensation_handler(
            successful_type,
            lambda task: handled.append(task.subject_ref),
        )
        register_compensation_handler(
            failed_type,
            lambda _task: (_ for _ in ()).throw(RuntimeError("password=private")),
        )
        successful = create_compensation(
            task_type=successful_type,
            subject_type="test",
            subject_ref="opaque-success",
            payload={},
            trace_id="2" * 32,
        )
        failed = create_compensation(
            task_type=failed_type,
            subject_type="test",
            subject_ref="opaque-failed",
            payload={},
            trace_id="3" * 32,
            max_attempts=1,
        )

        claimed = claim_compensations()
        self.assertEqual(set(claimed), {successful.pk, failed.pk})
        for task_id in claimed:
            run_compensation(task_id)

        successful.refresh_from_db()
        failed.refresh_from_db()
        self.assertEqual(successful.status, CompensationTask.Status.COMPLETED)
        self.assertEqual(failed.status, CompensationTask.Status.DEAD)
        self.assertEqual(handled, ["opaque-success"])
        self.assertNotIn("private", failed.last_failure.message_masked)

    def test_relay_is_not_enqueued_until_transaction_commit(self) -> None:
        from unittest.mock import patch

        with patch("apps.core.tasks.relay_outbox.apply_async") as apply_async:  # noqa: SIM117
            with (
                self.captureOnCommitCallbacks(execute=False) as callbacks,
                transaction.atomic(),
            ):
                enqueue_relay_after_commit(trace_id="4" * 32)
                apply_async.assert_not_called()
            for callback in callbacks:
                callback()
            apply_async.assert_called_once_with(kwargs={"trace_id": "4" * 32})

    def test_celery_task_uses_request_trace_context(self) -> None:
        from education_experiment_platform.celery import app

        CaptureTraceTask.bind(app)
        task = CaptureTraceTask()
        task.push_request(headers={})
        try:
            result = task(trace_id="5" * 32)
        finally:
            task.pop_request()
        self.assertEqual(result, "5" * 32)

    def test_audit_failure_and_free_text_are_recursively_redacted(self) -> None:
        audit = append_audit(
            actor_ref="actor-1",
            actor_portal="PLATFORM",
            actor_context={"role": "ADMIN", "cookie": "private"},
            action="test.change",
            target_type="test",
            target_ref="opaque-1",
            before={"nested": {"password": "private"}},
            after={"safe": "visible"},
            result="SUCCEEDED",
            trace_id="f" * 32,
        )
        failure = append_failure(
            failure_type="TEST",
            subject_type="test",
            subject_ref="opaque-1",
            error_code="TEST_FAILED",
            message="token=private-value",
            detail={"client_ip": "127.0.0.1", "safe": "visible"},
            retryable=True,
            trace_id="f" * 32,
        )

        self.assertEqual(audit.actor_context["cookie"], REDACTED)
        self.assertEqual(audit.before_masked["nested"]["password"], REDACTED)
        self.assertNotIn("private-value", failure.message_masked)
        self.assertEqual(failure.detail_masked["client_ip"], REDACTED)
        self.assertEqual(redact({"signed_url": "private"})["signed_url"], REDACTED)
        self.assertEqual(AuditLog.objects.count(), 1)
        self.assertEqual(FailureRecord.objects.count(), 1)

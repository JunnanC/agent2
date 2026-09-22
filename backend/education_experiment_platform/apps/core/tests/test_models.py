from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.core.assets import register_asset, set_scan_result
from apps.core.concurrency import compare_and_swap, etag_for_version, parse_if_match
from apps.core.errors import ImmutableRecordError, PreconditionRequired, RowVersionConflict
from apps.core.models import AuditLog, ObjectAsset, OutboxDelivery, OutboxEvent


class CoreModelTests(TestCase):
    def test_append_only_rows_reject_save_update_and_delete(self) -> None:
        event = OutboxEvent.objects.create(
            event_type="test.created",
            aggregate_type="test",
            aggregate_ref="opaque-1",
            payload={},
            trace_id="a" * 32,
        )

        event.payload = {"changed": True}
        with self.assertRaises(ImmutableRecordError):
            event.save()
        with self.assertRaises(ImmutableRecordError):
            OutboxEvent.objects.filter(pk=event.pk).update(payload={"changed": True})
        with self.assertRaises(ImmutableRecordError):
            OutboxEvent.objects.filter(pk=event.pk).delete()
        with self.assertRaises(ImmutableRecordError):
            event.delete()

    def test_all_append_only_core_tables_use_protected_manager(self) -> None:
        audit = AuditLog.objects.create(
            actor_ref="actor-1",
            action="test",
            target_type="test",
            target_ref="opaque-1",
            result="SUCCEEDED",
            trace_id="b" * 32,
        )

        with self.assertRaises(ImmutableRecordError):
            AuditLog.objects.filter(pk=audit.pk).update(result="CHANGED")

    def test_compare_and_swap_increments_once_and_rejects_stale_version(self) -> None:
        asset = self._asset()

        changed = compare_and_swap(
            ObjectAsset,
            pk=asset.pk,
            expected_version=1,
            changes={"scan_status": ObjectAsset.ScanStatus.CLEAN},
        )

        self.assertEqual(changed.row_version, 2)
        self.assertEqual(changed.scan_status, ObjectAsset.ScanStatus.CLEAN)
        with self.assertRaises(RowVersionConflict):
            compare_and_swap(
                ObjectAsset,
                pk=asset.pk,
                expected_version=1,
                changes={"scan_status": ObjectAsset.ScanStatus.FAILED},
            )

    def test_versioned_instance_cannot_bypass_compare_and_swap(self) -> None:
        asset = self._asset()
        asset.media_type = "text/plain"

        with self.assertRaises(RuntimeError):
            asset.save()
        with self.assertRaises(RuntimeError):
            asset.delete()

    def test_etag_contract_is_quoted_and_requires_if_match(self) -> None:
        self.assertEqual(etag_for_version(4), '"4"')
        self.assertEqual(parse_if_match('"4"'), 4)
        self.assertEqual(parse_if_match('W/"4"'), 4)
        with self.assertRaises(PreconditionRequired):
            parse_if_match(None)

    def test_database_check_constraints_reject_invalid_delivery_state(self) -> None:
        event = OutboxEvent.objects.create(
            event_type="test.created",
            aggregate_type="test",
            aggregate_ref="opaque-1",
            payload={},
            trace_id="a" * 32,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            OutboxDelivery.objects.create(
                event=event,
                destination="invalid",
                status="NOT_A_STATE",
            )

    def test_asset_registration_validates_digest_and_scan_transition(self) -> None:
        asset = self._asset()
        changed = set_scan_result(
            asset_id=asset.pk,
            expected_version=1,
            scan_status=ObjectAsset.ScanStatus.INFECTED,
        )
        self.assertEqual(changed.scan_status, ObjectAsset.ScanStatus.INFECTED)

        with self.assertRaises(ValueError):
            register_asset(
                bucket="test",
                object_key="bad",
                object_version="v1",
                digest_sha256="not-a-digest",
                size_bytes=1,
                owner_type="test",
                owner_ref="opaque-1",
                purpose="TEST",
            )

    @staticmethod
    def _asset() -> ObjectAsset:
        return register_asset(
            bucket="test",
            object_key="object/one",
            object_version="v1",
            digest_sha256="0" * 64,
            size_bytes=42,
            owner_type="test",
            owner_ref="opaque-1",
            purpose="TEST",
        )

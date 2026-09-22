import threading
import time
from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from apps.core.assets import register_asset
from apps.core.concurrency import compare_and_swap
from apps.core.errors import RowVersionConflict
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.models import ObjectAsset


class Command(BaseCommand):
    help = "Run the P01 CAS and idempotency probes using independent database connections."

    def handle(self, *args: object, **options: object) -> None:
        self._verify_cas()
        self._verify_idempotency()
        self.stdout.write(self.style.SUCCESS("P01 MySQL concurrency verification passed."))

    @staticmethod
    def _verify_cas() -> None:
        asset = register_asset(
            bucket="verify",
            object_key="concurrent-cas",
            object_version="v1",
            digest_sha256="1" * 64,
            size_bytes=1,
            owner_type="verify",
            owner_ref="opaque-cas",
            purpose="VERIFY",
        )
        barrier = threading.Barrier(2)

        def update(status: str) -> str:
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                compare_and_swap(
                    ObjectAsset,
                    pk=asset.pk,
                    expected_version=1,
                    changes={"scan_status": status},
                )
                return "SUCCESS"
            except RowVersionConflict:
                return "ROW_VERSION_CONFLICT"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    update,
                    (ObjectAsset.ScanStatus.CLEAN, ObjectAsset.ScanStatus.FAILED),
                )
            )
        if sorted(results) != ["ROW_VERSION_CONFLICT", "SUCCESS"]:
            raise CommandError(f"Unexpected CAS results: {results}")

    @staticmethod
    def _verify_idempotency() -> None:
        barrier = threading.Barrier(2)
        calls = 0
        calls_lock = threading.Lock()

        def operation() -> StoredResponse:
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.1)
            return StoredResponse(201, {"data": {"id": "opaque-idempotent"}}, {})

        def execute() -> str:
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                response = execute_idempotent(
                    principal=PrincipalScope("actor-concurrent", "SESSION", "USER"),
                    method="POST",
                    endpoint="/api/v2/verify-concurrency",
                    key="concurrent-intent",
                    payload={"name": "same"},
                    operation=operation,
                )
                return "REPLAY" if response.replayed else "SUCCESS"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: execute(), range(2)))
        if sorted(results) != ["REPLAY", "SUCCESS"] or calls != 1:
            raise CommandError(f"Unexpected idempotency results: {results}, calls={calls}")

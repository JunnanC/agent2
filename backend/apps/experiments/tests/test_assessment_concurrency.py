from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings

from apps.core.errors import RowVersionConflict
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent

from ..assessment import read_draft, save_draft, submit_choices
from ..models import SectionSubmission


@skipUnless(connection.vendor == "mysql", "requires real MySQL row locks")
@override_settings(AUTO_PROVISION_ON_ASSIGNMENT=False)
class AssessmentConcurrencyTests(TransactionTestCase):
    def setUp(self) -> None:
        from .test_assessment import AssessmentTests

        relay = patch("apps.core.tasks.relay_outbox.apply_async")
        relay.start()
        self.addCleanup(relay.stop)
        AssessmentTests.setUp(self)

    def test_conflicting_saves_and_duplicate_submission_are_serialized(self) -> None:
        draft = read_draft(
            actor=self.student, task_id=self.task.public_id, question_id=self.question.public_id,
        )
        gate = Barrier(2)

        def save() -> str:
            close_old_connections()
            try:
                gate.wait(timeout=10)
                save_draft(
                    actor=self.student, task_id=self.task.public_id,
                    question_id=self.question.public_id, expected_version=draft["row_version"],
                    data={"selected_option_ids": ["b"]},
                )
                return "saved"
            except RowVersionConflict:
                return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: save(), range(2))) == ["conflict", "saved"]
        gate = Barrier(2)

        def submit() -> int:
            close_old_connections()
            try:
                gate.wait(timeout=10)

                def operation() -> StoredResponse:
                    submission = submit_choices(
                        actor=self.student, task_id=self.task.public_id,
                        versions={self.question.public_id: 2}, trace_id="concurrent",
                    )
                    return StoredResponse(201, {"version": submission.version_no}, {})

                response = execute_idempotent(
                    principal=PrincipalScope(self.student.public_id, "SESSION", "USER"),
                    method="POST", endpoint="/assessment/concurrent", key="one-command",
                    payload={"version": 2}, operation=operation,
                )
                return response.body["version"]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(lambda _: submit(), range(2))) == [1, 1]
        assert SectionSubmission.objects.filter(section__task=self.task).count() == 1

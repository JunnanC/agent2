from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from typing import Any
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings

from apps.core.errors import RowVersionConflict, StateConflict
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent

from ..assessment import read_draft, save_draft, submit_choices
from ..models import SectionSubmission, TaskPublication


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

    def test_withdrawal_and_draft_save_use_the_same_lock_order(self) -> None:
        from ..services import withdraw_publication
        from .helpers import context

        draft = read_draft(
            actor=self.student, task_id=self.task.public_id, question_id=self.question.public_id,
        )
        waiting = Event()

        def save() -> str:
            close_old_connections()

            def observe(
                execute: Any, sql: str, params: Any, many: bool, context: Any,
            ) -> Any:
                if "FOR UPDATE" in sql and TaskPublication._meta.db_table in sql:
                    waiting.set()
                return execute(sql, params, many, context)

            try:
                with connection.execute_wrapper(observe):
                    save_draft(
                        actor=self.student, task_id=self.task.public_id,
                        question_id=self.question.public_id, expected_version=draft["row_version"],
                        data={"selected_option_ids": ["b"]},
                    )
                return "saved"
            except StateConflict:
                return "closed"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                publication = TaskPublication.objects.select_for_update().get(
                    pk=self.publication.pk,
                )
                pending = pool.submit(save)
                assert waiting.wait(timeout=10), "save did not reach the publication lock"
                withdraw_publication(
                    course_id=self.course.public_id, publication_id=publication.public_id,
                    actor=self.owner, expected_version=publication.row_version,
                    context=context(self.owner),
                )
            assert pending.result(timeout=15) == "closed"

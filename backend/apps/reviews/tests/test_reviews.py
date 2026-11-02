import hashlib
import os
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.tests.helpers import create_user, grant_admin, grant_teacher
from apps.core.errors import ImmutableRecordError, RowVersionConflict
from apps.core.models import FailureRecord, ObjectAsset, OutboxEvent
from apps.courses.models import Course, CourseStaff
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.experiments.services import publish_publication
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.labtemplates.models import AutoCheckRule
from apps.provisioning.adapters import DockerLocalAdapter
from apps.provisioning.models import ProvisioningInstance
from apps.provisioning.ports import RuntimeExecutionResult
from apps.reports.models import ReportDraft, ReportVersion
from apps.reports.services import submit_report, update_report_draft
from apps.workspaces.models import WorkspaceSession, WorkspaceSnapshot

from ..checkers import AutoCheckResult, DockerLocalAutoCheckExecutor
from ..errors import AutoCheckPending, ReviewStateConflict
from ..models import (
    AnnotationRevision,
    AutoCheckRun,
    CriterionScoreEvent,
    Review,
    ReviewAnnotation,
    ReviewDecision,
    RubricCriterion,
    SimilarityMatch,
)
from ..serializers import review_result_data
from ..services import (
    add_review_annotation,
    create_review_for_submission,
    decide_review,
    execute_auto_check,
    execute_similarity_run,
    revise_review_annotation,
    score_review_criteria,
    start_similarity_run,
)


class ReviewServiceTests(TestCase):
    password = "ValidPassword!234"

    def setUp(self) -> None:
        self.teacher, self.course, self.template_version, self.rubric_version = create_domain(
            suffix="reviews"
        )
        self.criteria = [
            RubricCriterion.objects.create(
                rubric_version=self.rubric_version,
                position=1,
                position_key="1",
                title="Correctness",
                max_score=Decimal("60"),
                weight_basis_points=6000,
            ),
            RubricCriterion.objects.create(
                rubric_version=self.rubric_version,
                position=2,
                position_key="2",
                title="Quality",
                max_score=Decimal("40"),
                weight_basis_points=4000,
            ),
        ]
        self.enrollment = create_enrollment(self.course, suffix="reviews-student")
        self.other_enrollment = create_enrollment(self.course, suffix="reviews-peer")
        publication = create_draft_publication(
            owner=self.teacher,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="reviews",
        )
        self.publication, _job = publish_publication(
            course_id=self.course.public_id,
            publication_id=publication.public_id,
            actor=self.teacher,
            expected_version=publication.row_version,
            selected_ids=[],
            context=self.context(self.teacher),
        )
        self.task = self.publication.tasks.get(student=self.enrollment.student)
        self.peer_task = self.publication.tasks.get(student=self.other_enrollment.student)
        self.review = self._submitted_review(self.task, "Shared report body for reviews checking")
        self.peer_review = self._submitted_review(
            self.peer_task, "Shared report body for reviews checking and comparison"
        )

    def context(self, actor: object, portal: str = "TEACHING") -> ActorContext:
        return ActorContext(actor.public_id, portal, "a" * 32)  # type: ignore[attr-defined]

    def _client(self, *, identifier: str, portal: str) -> tuple[Client, str]:
        client = Client(enforce_csrf_checks=True)
        proxy = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}
        client.get("/api/v2/auth/csrf", HTTP_X_PORTAL=portal, **proxy)
        csrf = client.cookies["csrftoken"].value
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            response = client.post(
                "/api/v2/auth/login",
                {"identifier": identifier, "password": self.password},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL=portal,
                **proxy,
            )
        self.assertEqual(response.status_code, 200, response.content)
        return client, csrf

    def _snapshot(self, task: ExperimentTask, body: str) -> WorkspaceSnapshot:
        payload = body.encode()
        digest = hashlib.sha256(payload).hexdigest()
        asset = ObjectAsset.objects.create(
            bucket="edu-platform",
            object_key=f"workspaces/{task.public_id}/{digest}",
            object_version=f"version-{task.public_id}",
            digest_sha256=digest,
            size_bytes=len(payload),
            media_type="text/plain",
            owner_type="WORKSPACE_TASK",
            owner_ref=task.public_id,
            purpose="WORKSPACE_SNAPSHOT",
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )
        instance = ProvisioningInstance.objects.create(
            task=task,
            course=self.course,
            runtime_adapter=self.template_version.runtime_adapter,
            image=self.template_version.image,
            resource_profile=self.template_version.resource_profile,
            runtime_type=self.template_version.runtime_type,
            status=ProvisioningInstance.Status.READY,
            external_id=f"fake-{task.public_id}",
            created_trace_id="i" * 32,
        )
        session = WorkspaceSession.objects.create(
            task=task,
            student=task.student,
            instance=instance,
            course=self.course,
            jti=f"jti-{task.public_id}",
            token_hash=hashlib.sha256(task.public_id.encode()).hexdigest(),
            active_marker=f"active-{task.public_id}",
            capabilities={"snapshot": True},
            expires_at=timezone.now() + timezone.timedelta(minutes=10),
        )
        return WorkspaceSnapshot.objects.create(
            task=task,
            session=session,
            asset=asset,
            version_no=1,
            client_seq=1,
            digest_sha256=digest,
            size_bytes=len(payload),
            media_type="text/plain",
            saved_at=timezone.now(),
            trace_id="s" * 32,
        )

    def _submitted_review(self, task: ExperimentTask, body: str) -> Review:
        snapshot = self._snapshot(task, body)
        ExperimentTask.objects.filter(pk=task.pk).update(status=ExperimentTask.Status.UNDER_REVIEW)
        task.refresh_from_db()
        draft = ReportDraft.objects.create(
            task=task,
            student=task.student,
            body_markdown=body,
            workspace_snapshot=snapshot,
            snapshot_digest=snapshot.digest_sha256,
            status=ReportDraft.Status.SUBMITTED,
            submitted_at=timezone.now(),
        )
        version = ReportVersion.objects.create(
            task=task,
            draft=draft,
            student=task.student,
            version_no=1,
            body_markdown=body,
            body_digest=hashlib.sha256(body.encode()).hexdigest(),
            workspace_snapshot=snapshot,
            snapshot_digest=snapshot.digest_sha256,
            submitted_by=task.student,
            submitted_at=timezone.now(),
            trace_id="r" * 32,
        )
        return create_review_for_submission(
            task=task,
            report_version=version,
            context=self.context(task.student, "USER"),
        )

    def _score(self, review: Review | None = None) -> Review:
        item = review or self.review
        return score_review_criteria(
            course_id=self.course.public_id,
            review_id=item.public_id,
            actor=self.teacher,
            expected_version=item.row_version,
            scores=[
                {"criterion_id": self.criteria[0].public_id, "score": "55", "note": "good"},
                {"criterion_id": self.criteria[1].public_id, "score": "35", "note": "clear"},
            ],
            context=self.context(self.teacher),
        )

    def test_scoring_uses_parent_cas_and_appends_events(self) -> None:
        stale_version = self.review.row_version
        changed = self._score()
        self.assertEqual(changed.status, Review.Status.IN_REVIEW)
        self.assertEqual(CriterionScoreEvent.objects.filter(review=self.review).count(), 2)
        with self.assertRaises(RowVersionConflict):
            score_review_criteria(
                course_id=self.course.public_id,
                review_id=self.review.public_id,
                actor=self.teacher,
                expected_version=stale_version,
                scores=[{"criterion_id": self.criteria[0].public_id, "score": "50"}],
                context=self.context(self.teacher),
            )

    def test_annotations_keep_revision_history_and_freeze_after_decision(self) -> None:
        annotation, changed_review = add_review_annotation(
            course_id=self.course.public_id,
            review_id=self.review.public_id,
            actor=self.teacher,
            expected_version=self.review.row_version,
            target_type=ReviewAnnotation.TargetType.REPORT_TEXT,
            target_ref=self.review.report_version.public_id,
            anchor={"kind": "TEXT_RANGE", "start": 0, "end": 6},
            body="Explain this result.",
            context=self.context(self.teacher),
        )
        revised = revise_review_annotation(
            course_id=self.course.public_id,
            review_id=self.review.public_id,
            annotation_id=annotation.public_id,
            actor=self.teacher,
            expected_version=annotation.row_version,
            body="Explain this result with evidence.",
            revoke=False,
            context=self.context(self.teacher),
        )
        self.assertEqual(revised.current_revision_no, 2)
        self.assertEqual(AnnotationRevision.objects.filter(annotation=annotation).count(), 2)
        changed_review = self._score(changed_review)
        decide_review(
            course_id=self.course.public_id,
            review_id=self.review.public_id,
            actor=self.teacher,
            expected_version=changed_review.row_version,
            decision=ReviewDecision.Decision.APPROVE,
            requested_score=Decimal("90"),
            feedback="Approved",
            context=self.context(self.teacher),
        )
        revised.refresh_from_db()
        with self.assertRaises(ReviewStateConflict):
            revise_review_annotation(
                course_id=self.course.public_id,
                review_id=self.review.public_id,
                annotation_id=annotation.public_id,
                actor=self.teacher,
                expected_version=revised.row_version,
                body="late edit",
                revoke=False,
                context=self.context(self.teacher),
            )

    def test_reject_reopens_draft_and_resubmission_creates_second_round(self) -> None:
        changed = self._score()
        decision, _review, reopened = decide_review(
            course_id=self.course.public_id,
            review_id=self.review.public_id,
            actor=self.teacher,
            expected_version=changed.row_version,
            decision=ReviewDecision.Decision.REJECT,
            requested_score=None,
            feedback="Please revise",
            context=self.context(self.teacher),
        )
        self.assertEqual(decision.decision, ReviewDecision.Decision.REJECT)
        self.assertEqual(reopened.status, ExperimentTask.Status.REPORT_DRAFT)
        draft = ReportDraft.objects.get(task=self.task)
        self.assertEqual(draft.status, ReportDraft.Status.DRAFT)
        updated = update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# Revised report",
            expected_version=draft.row_version,
            context=self.context(self.task.student, "USER"),
        )
        self.assertEqual(updated.status, ReportDraft.Status.DRAFT)
        reopened.refresh_from_db()
        _version, submitted = submit_report(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_task_version=reopened.row_version,
            context=self.context(self.task.student, "USER"),
        )
        self.assertEqual(submitted.status, ExperimentTask.Status.UNDER_REVIEW)
        self.assertEqual(Review.objects.filter(task=self.task).count(), 2)
        self.assertEqual(Review.objects.filter(task=self.task).latest("round_no").round_no, 2)

    def test_auto_check_blocks_decision_until_terminal_and_never_decides(self) -> None:
        self.publication.__class__.objects.filter(pk=self.publication.pk).update(
            review_mode="MANUAL_WITH_AUTO_CHECK"
        )
        self.publication.refresh_from_db()
        rule = AutoCheckRule.objects.create(
            template_version=self.template_version,
            position=1,
            position_key="reviews",
            checker_type="PYTEST",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            timeout_seconds=30,
            resource_limit={},
            network_policy={"mode": "DENY_ALL"},
            display_policy={"show_score": True},
            failure_semantics={"on_failure": "FAIL_CHECK"},
            rule_digest="f" * 64,
        )
        extra_task = self.publication.tasks.create(
            course=self.course,
            enrollment=create_enrollment(self.course, suffix="reviews-auto"),
            student=create_user(email="unused-auto@example.edu", username="unused-auto"),
            template_version=self.template_version,
            runtime_type=self.template_version.runtime_type,
            status=ExperimentTask.Status.UNDER_REVIEW,
        )
        # Keep the fixture's cross-table invariant explicit despite direct model construction.
        extra_task.student = extra_task.enrollment.student
        ExperimentTask.objects.filter(pk=extra_task.pk).update(student=extra_task.enrollment.student)
        review = self._submitted_review(extra_task, "Auto-check report")
        run = review.auto_check_runs.get(rule=rule)
        changed = self._score(review)
        with self.assertRaises(AutoCheckPending):
            decide_review(
                course_id=self.course.public_id,
                review_id=review.public_id,
                actor=self.teacher,
                expected_version=changed.row_version,
                decision=ReviewDecision.Decision.APPROVE,
                requested_score=Decimal("90"),
                feedback="",
                context=self.context(self.teacher),
            )
        with patch("apps.reviews.services.auto_check_executor") as executor_factory:
            executor_factory.return_value.execute.side_effect = RuntimeError("temporary")
            retry = execute_auto_check(run_id=run.public_id)
        self.assertEqual(retry.status, AutoCheckRun.Status.QUEUED)
        self.assertEqual(retry.attempt_count, 1)
        self.assertTrue(
            FailureRecord.objects.filter(subject_ref=run.public_id, retryable=True).exists()
        )
        completed = execute_auto_check(run_id=run.public_id)
        self.assertEqual(completed.status, AutoCheckRun.Status.PASSED)
        self.assertEqual(completed.attempt_count, 2)
        self.assertFalse(ReviewDecision.objects.filter(review=review).exists())

    def test_docker_local_judge_uses_frozen_contract_and_hidden_tests(self) -> None:
        rule = AutoCheckRule.objects.create(
            template_version=self.template_version,
            position=9,
            position_key="auto-check-real",
            checker_type="PYTEST",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            timeout_seconds=30,
            resource_limit={"cpu_millicores": 250, "memory_mb": 128},
            network_policy={"mode": "DENY_ALL"},
            failure_semantics={"on_failure": "FAIL_CHECK"},
            rule_digest="e" * 64,
        )
        task = self.review.task
        type(task).objects.filter(pk=task.pk).update(
            runtime_adapter_driver="DOCKER_LOCAL",
            runtime_adapter_config_ref="runtime/local-algorithm",
        )
        task.refresh_from_db()
        contract = {
            "language": "python",
            "entrypoint": "main.py",
            "timeout_seconds": 5,
            "memory_mb": 256,
            "cpu_millicores": 500,
            "comparator": "token",
            "network_mode": "DENY_ALL",
            "tests_asset": self.template_version.execution_spec["tests_asset"],
            "command": ["python", "main.py"],
        }
        run = AutoCheckRun.objects.create(
            review=self.review,
            rule=rule,
            input_asset=self.review.report_version.workspace_snapshot.asset,
            checker_type=rule.checker_type,
            rule_digest=rule.rule_digest,
            artifact_digest=self.review.report_version.snapshot_digest,
            execution_rule_summary=contract,
            execution_rule_digest="",
            trace_id="j" * 32,
        )
        captured: dict[str, object] = {}
        destroyed: list[tuple[str, str]] = []

        class JudgeAdapter:
            def execute_judge(self, **kwargs: object) -> RuntimeExecutionResult:
                captured.update(kwargs)
                return RuntimeExecutionResult(
                    status="TIMEOUT",
                    error_code="JUDGE_TIMEOUT",
                    result_summary="judge timed out",
                    duration_ms=5000,
                )

            def destroy_judge(self, judge_id: str, idempotency_key: str = "") -> None:
                destroyed.append((judge_id, idempotency_key))

        executor = DockerLocalAutoCheckExecutor(
            runtime_factory=lambda _driver, config_ref: JudgeAdapter(),
        )
        with patch("apps.reviews.checkers._read_asset", side_effect=[b"student", b"hidden"]):
            result = executor.execute(run)
        self.assertEqual(result.status, AutoCheckRun.Status.TIMEOUT)
        self.assertFalse(result.passed)
        self.assertEqual(captured["source"], b"student")
        self.assertEqual(captured["tests"], b"hidden")
        self.assertEqual(captured["network_mode"], "DENY_ALL")
        self.assertEqual(captured["command"], ["python", "main.py"])
        self.assertEqual(captured["memory_mb"], 128)
        self.assertEqual(captured["cpu_millicores"], 250)
        self.assertEqual(destroyed, [(run.public_id, f"judge-destroy:{run.public_id}")])

    @skipUnless(
        os.environ.get(
            "LOCAL_DOCKER_INTEGRATION", os.environ.get("T10_DOCKER_INTEGRATION", "")
        ) == "1",
        "requires the local Docker Engine and local-runtime workspace image",
    )
    def test_local_runtime_real_docker_judge_completes_report_review_flow(self) -> None:
        rule = AutoCheckRule.objects.create(
            template_version=self.template_version,
            position=99,
            position_key="local-runtime-real-docker",
            checker_type="PYTHON_IO",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            timeout_seconds=3,
            resource_limit={"cpu_millicores": 250, "memory_mb": 64},
            network_policy={"mode": "DENY_ALL"},
            failure_semantics={"on_failure": "FAIL_CHECK"},
            rule_digest="d" * 64,
        )
        task = self.review.task
        type(task).objects.filter(pk=task.pk).update(
            runtime_adapter_driver="DOCKER_LOCAL",
            runtime_adapter_config_ref="runtime/local-docker",
        )
        task.refresh_from_db()
        contract = {
            "language": "python",
            "entrypoint": "main.py",
            "timeout_seconds": 3,
            "memory_mb": 64,
            "cpu_millicores": 250,
            "comparator": "token",
            "network_mode": "DENY_ALL",
            "tests_asset": self.template_version.execution_spec["tests_asset"],
            "command": ["python", "main.py"],
        }
        run = AutoCheckRun.objects.create(
            review=self.review,
            rule=rule,
            input_asset=self.review.report_version.workspace_snapshot.asset,
            checker_type=rule.checker_type,
            rule_digest=rule.rule_digest,
            artifact_digest=self.review.report_version.snapshot_digest,
            execution_rule_summary=contract,
            execution_rule_digest="",
            trace_id="t" * 32,
        )
        adapter = DockerLocalAdapter(
            config={"image": "experimental-platform-workspace:local"},
            config_ref="runtime/local-docker",
        )
        executor = DockerLocalAutoCheckExecutor(
            runtime_factory=lambda _driver, config_ref: adapter,
        )
        source = b"value = int(input())\nprint(value * 2)\n"
        hidden_tests = b'{"cases":[{"input":"3\\n","expected":"6\\n"}]}'
        with (
            patch("apps.reviews.checkers._read_asset", side_effect=[source, hidden_tests]),
            patch("apps.reviews.services.auto_check_executor", return_value=executor),
        ):
            completed = execute_auto_check(run_id=run.public_id)

        self.assertEqual(completed.status, AutoCheckRun.Status.PASSED)
        self.assertEqual(completed.result_summary["executor"], "DOCKER_LOCAL_JUDGE")
        self.assertEqual(completed.evidence[0]["status"], AutoCheckRun.Status.PASSED)
        changed = self._score(self.review)
        decision, _review, _task = decide_review(
            course_id=self.course.public_id,
            review_id=self.review.public_id,
            actor=self.teacher,
            expected_version=changed.row_version,
            decision=ReviewDecision.Decision.APPROVE,
            requested_score=Decimal("90"),
            feedback="Real local Docker judge passed.",
            context=self.context(self.teacher),
        )
        self.assertEqual(decision.decision, ReviewDecision.Decision.APPROVE)
        self.assertEqual(adapter.inventory_resources(), [])

    def test_auto_check_result_status_is_audit_fact_and_teacher_can_override(self) -> None:
        rule = AutoCheckRule.objects.create(
            template_version=self.template_version,
            position=10,
            position_key="auto-check-timeout",
            checker_type="PYTEST",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            timeout_seconds=30,
            resource_limit={},
            network_policy={"mode": "DENY_ALL"},
            failure_semantics={"on_failure": "FAIL_CHECK"},
            rule_digest="t" * 64,
        )
        run = AutoCheckRun.objects.create(
            review=self.review,
            rule=rule,
            input_asset=self.review.report_version.workspace_snapshot.asset,
            checker_type=rule.checker_type,
            rule_digest=rule.rule_digest,
            artifact_digest=self.review.report_version.snapshot_digest,
            execution_rule_summary={"command": ["python", "main.py"], "network_mode": "DENY_ALL"},
            execution_rule_digest="q" * 64,
            trace_id="k" * 32,
        )
        with patch(
            "apps.reviews.services.auto_check_executor",
            return_value=Mock(
                execute=Mock(
                    return_value=AutoCheckResult(
                        passed=False,
                        status=AutoCheckRun.Status.TIMEOUT,
                        error_code="JUDGE_TIMEOUT",
                        summary={"executor": "DOCKER_LOCAL_JUDGE"},
                        evidence=[{"rule_digest": rule.rule_digest}],
                    )
                )
            ),
        ):
            completed = execute_auto_check(run_id=run.public_id)
        self.assertEqual(completed.status, AutoCheckRun.Status.TIMEOUT)
        self.assertEqual(completed.error_code, "JUDGE_TIMEOUT")
        self.assertEqual(completed.evidence[0]["rule_digest"], rule.rule_digest)
        changed = self._score(self.review)
        decision, _review, _task = decide_review(
            course_id=self.course.public_id,
            review_id=self.review.public_id,
            actor=self.teacher,
            expected_version=changed.row_version,
            decision=ReviewDecision.Decision.APPROVE,
            requested_score=Decimal("90"),
            feedback="Manual override after timeout",
            context=self.context(self.teacher),
        )
        self.assertEqual(decision.decision, ReviewDecision.Decision.APPROVE)

    def test_student_result_hides_teacher_drafts_until_decision(self) -> None:
        changed = self._score()
        self.review = Review.objects.prefetch_related(
            "rubric_version__criteria", "criterion_scores__criterion", "annotations__revisions"
        ).get(pk=self.review.pk)
        draft_round = review_result_data([self.review])["rounds"][0]
        self.assertIsNone(draft_round["scores"])
        self.assertEqual(draft_round["annotations"], [])

        decide_review(
            course_id=self.course.public_id,
            review_id=self.review.public_id,
            actor=self.teacher,
            expected_version=changed.row_version,
            decision=ReviewDecision.Decision.APPROVE,
            requested_score=Decimal("90"),
            feedback="Approved",
            context=self.context(self.teacher),
        )
        decided = Review.objects.select_related("task").prefetch_related(
            "rubric_version__criteria", "criterion_scores__criterion", "annotations__revisions"
        ).get(pk=self.review.pk)
        decided_round = review_result_data([decided])["rounds"][0]
        self.assertIsNotNone(decided_round["scores"])

    def test_similarity_is_scoped_idempotent_and_does_not_change_task(self) -> None:
        before_status = self.task.status
        run = start_similarity_run(
            course_id=self.course.public_id,
            review_id=self.review.public_id,
            actor=self.teacher,
            expected_version=self.review.row_version,
            context=self.context(self.teacher),
        )
        replay = start_similarity_run(
            course_id=self.course.public_id,
            review_id=self.review.public_id,
            actor=self.teacher,
            expected_version=self.review.row_version,
            context=self.context(self.teacher),
        )
        self.assertEqual(replay.pk, run.pk)
        completed = execute_similarity_run(run_id=run.public_id)
        self.assertEqual(completed.status, "COMPLETED")
        match = SimilarityMatch.objects.get(run=run)
        self.assertEqual(match.candidate_report_version.task_id, self.peer_task.pk)
        self.assertGreaterEqual(match.score, Decimal("0.30"))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, before_status)

    def test_platform_context_and_database_constraint_both_reject_decision(self) -> None:
        changed = self._score()
        with self.assertRaises(Exception) as service_error:
            decide_review(
                course_id=self.course.public_id,
                review_id=self.review.public_id,
                actor=self.teacher,
                expected_version=changed.row_version,
                decision=ReviewDecision.Decision.APPROVE,
                requested_score=Decimal("90"),
                feedback="",
                context=self.context(self.teacher, "PLATFORM"),
            )
        self.assertEqual(getattr(service_error.exception, "code", ""), "PORTAL_ACCESS_DENIED")
        staff = self.course.staff.get(user=self.teacher)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReviewDecision.objects.create(
                review=self.review,
                decision=ReviewDecision.Decision.APPROVE,
                score=Decimal("90"),
                decided_by=self.teacher,
                decided_by_staff=staff,
                actor_portal="PLATFORM",
                criterion_snapshot=[],
                trace_id="p" * 32,
            )

    def test_platform_session_cannot_call_teacher_decide_route(self) -> None:
        admin = create_user(
            email="reviews-admin@example.edu", username="reviews-admin", password=self.password
        )
        grant_admin(admin)
        client = Client(enforce_csrf_checks=True)
        proxy = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}
        client.get("/api/v2/auth/csrf", HTTP_X_PORTAL="PLATFORM", **proxy)
        csrf = client.cookies["csrftoken"].value
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            login = client.post(
                "/api/v2/auth/login",
                {"identifier": admin.email, "password": self.password},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL="PLATFORM",
                **proxy,
            )
        self.assertEqual(login.status_code, 200, login.content)
        response = client.post(
            f"/api/v2/teaching/courses/{self.course.public_id}/reviews/{self.review.public_id}/decide",
            {"decision": "APPROVE", "score": "90"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IF_MATCH=f'"{self.review.row_version}"',
            HTTP_IDEMPOTENCY_KEY="platform-must-not-decide",
            **proxy,
        )
        self.assertEqual(response.status_code, 403, response.content)
        self.assertFalse(ReviewDecision.objects.filter(review=self.review).exists())

    def test_student_result_scope_hides_another_students_review(self) -> None:
        client, _csrf = self._client(identifier=self.peer_task.student.email, portal="USER")
        response = client.get(
            f"/api/v2/tasks/{self.task.public_id}/review-result",
            HTTP_X_PORTAL="USER",
            HTTP_X_PROXY_CONTEXT="ingress-v1",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 404, response.content)

    def test_cross_course_is_hidden_and_assistant_without_grant_is_forbidden(self) -> None:
        other_course = Course.objects.create(
            owner=self.teacher,
            code="reviews-OTHER",
            title="reviews Other Course",
            visibility=Course.Visibility.UNLISTED,
            enrollment_mode=Course.EnrollmentMode.OPEN,
        )
        other_client, _csrf = self._client(
            identifier=self.teacher.email, portal="TEACHING"
        )
        hidden = other_client.get(
            f"/api/v2/teaching/courses/{other_course.public_id}/reviews/{self.review.public_id}",
            HTTP_X_PORTAL="TEACHING",
            HTTP_X_PROXY_CONTEXT="ingress-v1",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(hidden.status_code, 404, hidden.content)

        assistant = create_user(
            email="reviews-assistant@example.edu",
            username="reviews-assistant",
            password=self.password,
        )
        grant_teacher(assistant, self.teacher)
        CourseStaff.objects.create(
            course=self.course,
            user=assistant,
            role=CourseStaff.Role.ASSISTANT,
            status=CourseStaff.Status.ACTIVE,
            appointed_by=self.teacher,
            appointed_at=timezone.now(),
        )
        assistant_client, _csrf = self._client(
            identifier=assistant.email, portal="TEACHING"
        )
        forbidden = assistant_client.get(
            f"/api/v2/teaching/courses/{self.course.public_id}/reviews",
            HTTP_X_PORTAL="TEACHING",
            HTTP_X_PROXY_CONTEXT="ingress-v1",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.content)

    def test_score_api_rejects_stale_etag(self) -> None:
        client, csrf = self._client(identifier=self.teacher.email, portal="TEACHING")
        url = (
            f"/api/v2/teaching/courses/{self.course.public_id}/reviews/"
            f"{self.review.public_id}/criterion-scores"
        )
        body = {
            "scores": [
                {"criterion_id": self.criteria[0].public_id, "score": "55", "note": "good"},
                {"criterion_id": self.criteria[1].public_id, "score": "35", "note": "clear"},
            ]
        }
        headers = {
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_X_PORTAL": "TEACHING",
            "HTTP_IF_MATCH": f'"{self.review.row_version}"',
            "HTTP_X_PROXY_CONTEXT": "ingress-v1",
            "REMOTE_ADDR": "127.0.0.1",
        }
        first = client.put(
            url,
            body,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="reviews-score-first-key",
            **headers,
        )
        stale = client.put(
            url,
            body,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="reviews-score-stale-key",
            **headers,
        )
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(stale.status_code, 412, stale.content)

    def test_decision_api_exact_replay_and_key_reuse_conflict(self) -> None:
        changed = self._score()
        client, csrf = self._client(identifier=self.teacher.email, portal="TEACHING")
        url = (
            f"/api/v2/teaching/courses/{self.course.public_id}/reviews/"
            f"{self.review.public_id}/decide"
        )
        headers = {
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_X_PORTAL": "TEACHING",
            "HTTP_IF_MATCH": f'"{changed.row_version}"',
            "HTTP_IDEMPOTENCY_KEY": "reviews-decision-once",
            "HTTP_X_PROXY_CONTEXT": "ingress-v1",
            "REMOTE_ADDR": "127.0.0.1",
        }
        body = {"decision": "APPROVE", "score": "90", "feedback": "Approved"}
        first = client.post(url, body, content_type="application/json", **headers)
        replay = client.post(url, body, content_type="application/json", **headers)
        conflict = client.post(
            url,
            {**body, "feedback": "Different payload"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(first.json(), replay.json())
        self.assertEqual(conflict.status_code, 422, conflict.content)
        self.assertEqual(ReviewDecision.objects.filter(review=self.review).count(), 1)

    def test_decision_and_events_are_append_only(self) -> None:
        changed = self._score()
        decision, _review, _task = decide_review(
            course_id=self.course.public_id,
            review_id=self.review.public_id,
            actor=self.teacher,
            expected_version=changed.row_version,
            decision=ReviewDecision.Decision.APPROVE,
            requested_score=Decimal("90"),
            feedback="Approved",
            context=self.context(self.teacher),
        )
        with self.assertRaises(ImmutableRecordError):
            decision.save()
        with self.assertRaises(ImmutableRecordError):
            ReviewDecision.objects.filter(pk=decision.pk).delete()
        event = OutboxEvent.objects.filter(event_type="review.decided").latest("created_at")
        self.assertEqual(event.payload["user_id"], self.task.student.public_id)

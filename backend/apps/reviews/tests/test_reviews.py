import hashlib
import json
import os
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.tests.helpers import create_user, grant_admin, grant_teacher
from apps.core.errors import ImmutableRecordError, ResourceNotFound, RowVersionConflict
from apps.core.models import AuditLog, FailureRecord, ObjectAsset, OutboxEvent
from apps.core.project_archive import bundle
from apps.courses.models import Course, CourseStaff
from apps.courses.services import ActorContext
from apps.experiments.grades import capped_retake_score, task_grades
from apps.experiments.models import ExperimentRetakeLink, ExperimentTask, TaskPublication
from apps.experiments.services import (
    create_retake_publication,
    publish_publication,
    student_learning_history,
    teaching_progress,
)
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.labtemplates.models import AutoCheckRule
from apps.labtemplates.services import _normalize_execution_spec
from apps.provisioning.adapters import DockerLocalAdapter
from apps.provisioning.models import ProvisioningInstance
from apps.provisioning.ports import RuntimeExecutionResult
from apps.reports.models import ReportDraft, ReportVersion, SystemArtifact
from apps.reports.services import submit_report, update_report_draft
from apps.workspaces.models import WorkspaceSession, WorkspaceSnapshot

from ..checkers import AutoCheckRejected, AutoCheckResult, DockerLocalAutoCheckExecutor
from ..errors import AutoCheckPending, ReviewStateConflict
from ..models import (
    AIScoreBatch,
    AIScoreSuggestion,
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
    accept_ai_score_batch,
    accept_ai_score_suggestion,
    add_review_annotation,
    create_review_for_submission,
    decide_review,
    execute_ai_score_suggestion,
    execute_auto_check,
    execute_similarity_run,
    revise_review_annotation,
    score_review_criteria,
    start_ai_score_batch,
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

    def _snapshot(
        self, task: ExperimentTask, body: str | bytes, *, language: str = "python",
    ) -> WorkspaceSnapshot:
        payload = body.encode() if isinstance(body, str) else body
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
            language=language,
        )

    def _submitted_review(
        self, task: ExperimentTask, body: str, *, source: bytes | None = None,
        language: str = "python",
    ) -> Review:
        snapshot = self._snapshot(task, source if source is not None else body, language=language)
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

    def _confirm_score(self, review: Review, score: str) -> ReviewDecision:
        total = Decimal(score)
        changed = score_review_criteria(
            course_id=self.course.public_id,
            review_id=review.public_id,
            actor=self.teacher,
            expected_version=review.row_version,
            scores=[
                {"criterion_id": self.criteria[0].public_id, "score": min(total, Decimal("60"))},
                {
                    "criterion_id": self.criteria[1].public_id,
                    "score": max(total - 60, Decimal("0")),
                },
            ],
            context=self.context(self.teacher),
        )
        decision, _, _ = decide_review(
            course_id=self.course.public_id,
            review_id=review.public_id,
            actor=self.teacher,
            expected_version=changed.row_version,
            decision="APPROVE",
            requested_score=total,
            feedback="Confirmed",
            context=self.context(self.teacher),
        )
        return decision

    def _assert_retake_grade(self, first: str | None, second: str, expected: str) -> None:
        if first is not None:
            self._confirm_score(self.review, first)
        retake, _ = create_retake_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            selected_enrollment_ids=[self.enrollment.public_id],
            window_start=timezone.now() + timezone.timedelta(hours=1),
            window_end=timezone.now() + timezone.timedelta(days=2),
            actor=self.teacher,
            context=self.context(self.teacher),
        )
        retake_task = retake.tasks.get(student=self.task.student)
        pending_grade = task_grades([self.task])[self.task.pk]["score"]
        if first is None:
            self.assertIsNone(pending_grade)
        else:
            self.assertEqual(Decimal(str(pending_grade)), Decimal(first))
        review = self._submitted_review(retake_task, "Retake report")
        decision = self._confirm_score(review, second)
        link = ExperimentRetakeLink.objects.get(source_task=self.task)
        capped = capped_retake_score(Decimal(second))
        self.assertEqual(link.registered_score, capped)
        self.assertEqual(decision.score, capped)
        self.assertEqual(
            Decimal(str(task_grades([self.task])[self.task.pk]["score"])), Decimal(expected)
        )
        client, _ = self._client(identifier=self.teacher.email, portal="TEACHING")
        response = client.get(
            f"/api/v2/teaching/courses/{self.course.public_id}/tasks",
            HTTP_X_PORTAL="TEACHING",
            HTTP_X_PROXY_CONTEXT="ingress-v1",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 200, response.content)
        rows = {item["public_id"]: item for item in response.json()["data"]}
        self.assertEqual(Decimal(rows[self.task.public_id]["score"]), Decimal(expected))
        self.assertEqual(rows[retake_task.public_id]["retake_of_task_id"], self.task.public_id)
        progress = teaching_progress(course_id=self.course.public_id, actor=self.teacher)
        self.assertEqual(progress["total"], 2)
        students = progress["experiments"][0]["students"]
        student = next(item for item in students if item["task_id"] == self.task.public_id)
        self.assertEqual(Decimal(student["score"]), Decimal(expected))
        history = student_learning_history(actor=self.task.student)
        experiments = [item for year in history["years"] for term in year["terms"]
                       for course in term["courses"] for item in course["experiments"]]
        self.assertEqual(len(experiments), 1)
        self.assertEqual(Decimal(experiments[0]["score"]), Decimal(expected))

    def test_retake_caps_80_and_uses_it_when_original_is_45(self) -> None:
        self._assert_retake_grade("45", "80", "60")

    def test_retake_registers_59_without_rounding_to_60(self) -> None:
        self._assert_retake_grade("45", "59", "59")

    def test_retake_does_not_lower_a_higher_original_grade(self) -> None:
        self._assert_retake_grade("80", "40", "80")

    def test_retake_uses_its_score_when_original_has_no_decision(self) -> None:
        self._assert_retake_grade(None, "52.50", "52.50")

    def test_retake_registers_exactly_60(self) -> None:
        self._assert_retake_grade("45", "60", "60")

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

    def _v2_auto_review(
        self, language: str, source: bytes, *, system_artifact: bool = False,
        student_select: bool = False,
    ) -> AutoCheckRun:
        TaskPublication.objects.filter(pk=self.publication.pk).update(
            review_mode="MANUAL_WITH_AUTO_CHECK"
        )
        self.publication.refresh_from_db()
        if not self.template_version.auto_check_rules.exists():
            AutoCheckRule.objects.create(
                template_version=self.template_version, position=1, position_key="v2-review",
                checker_type="PYTHON_IO", input_schema={}, output_schema={},
                timeout_seconds=30, resource_limit={}, network_policy={"mode": "DENY_ALL"},
                failure_semantics={"on_failure": "FAIL_CHECK"}, rule_digest="v" * 64,
            )
        enrollment = create_enrollment(
            self.course, suffix=f"v2-{language}-{system_artifact}-{student_select}"
        )
        entrypoint = {"c": "src/main.c", "cpp": "src/main.cpp", "java": "src/Main.java",
                      "python": "src/main.py", "go": "src/main.go"}[language]
        spec = _normalize_execution_spec({
            "schema_version": 2, "language": None if student_select else language,
            "entrypoint": None if student_select else entrypoint,
            "timeout_seconds": 20, "memory_mb": 768, "cpu_millicores": 1000,
            "comparator": "numeric", "absolute_tolerance": 0, "relative_tolerance": 0,
            "tests_asset": self.template_version.execution_spec["tests_asset"],
            "network_mode": "DENY_ALL",
        })
        task = self.publication.tasks.create(
            course=self.course, enrollment=enrollment, student=enrollment.student,
            template_version=self.template_version, runtime_type="CONTAINER",
            runtime_adapter=self.template_version.runtime_adapter,
            runtime_adapter_driver="DOCKER_LOCAL",
            runtime_adapter_config_ref="runtime/local-docker",
            image=self.template_version.image,
            resource_profile=self.template_version.resource_profile,
            resource_profile_snapshot={"cpu_millicores": 1000, "memory_mb": 768, "disk_gb": 1},
            execution_spec=spec, template_spec_digest="a" * 64, status="UNDER_REVIEW",
        )
        if system_artifact:
            snapshot = self._snapshot(task, source, language=language)
            artifact = SystemArtifact.objects.create(
                task=task, student=task.student, workspace_snapshot=snapshot, asset=snapshot.asset,
                kind="WORKSPACE_SNAPSHOT", digest_sha256=snapshot.digest_sha256, trace_id="s" * 32,
            )
            review = create_review_for_submission(
                task=task, system_artifact=artifact, context=self.context(task.student, "USER"),
            )
        else:
            review = self._submitted_review(
                task, "Submitted report", source=source, language=language
            )
        return review.auto_check_runs.get()

    def test_v2_review_freezes_submission_language_plan_and_numeric_rules(self) -> None:
        source = bundle({"main.py": b"print(42)"}, max_bytes=1024)
        for language in ("c", "cpp", "java", "python", "go"):
            with self.subTest(language=language):
                run = self._v2_auto_review(language, source)
                summary = run.execution_rule_summary
                self.assertEqual(summary["language"], language)
                self.assertTrue(summary["execution_plan"]["run"])
                self.assertEqual(summary["absolute_tolerance"], 0)
                captured = {}
                adapter = SimpleNamespace(
                    execute_judge=lambda captured=captured, **kwargs: (
                        captured.update(kwargs) or RuntimeExecutionResult(status="PASSED")
                    ), destroy_judge=lambda *_args: None,
                )
                tests = b'{"comparator":"token","absolute_tolerance":99,"cases":[]}'
                with patch("apps.reviews.checkers._read_asset", side_effect=[source, tests]):
                    result = DockerLocalAutoCheckExecutor(
                        runtime_factory=Mock(return_value=adapter)
                    ).execute(run)
                self.assertTrue(result.passed)
                self.assertEqual(captured["execution_plan"], summary["execution_plan"])
                self.assertEqual(captured["source"], source)
                actual_tests = json.loads(captured["tests"])
                self.assertEqual(actual_tests["comparator"], "numeric")
                self.assertEqual(actual_tests["absolute_tolerance"], 0)
                self.assertEqual(actual_tests["relative_tolerance"], 0)

    def test_v2_system_artifact_review_uses_frozen_snapshot_not_live_session_language(self) -> None:
        run = self._v2_auto_review("java", b"source", system_artifact=True, student_select=True)
        WorkspaceSession.objects.filter(task=run.review.task).update(language="python")
        self.assertEqual(run.execution_rule_summary["language"], "java")
        adapter = SimpleNamespace(execute_judge=Mock(return_value=RuntimeExecutionResult(
            status="PASSED"
        )), destroy_judge=Mock())
        with patch("apps.reviews.checkers._read_asset", side_effect=[b"source", b'{"cases":[]}']):
            result = DockerLocalAutoCheckExecutor(
                runtime_factory=lambda *_args, **_kwargs: adapter
            ).execute(run)
        self.assertTrue(result.passed)
        self.assertEqual(
            adapter.execute_judge.call_args.kwargs["command"], ["python", "Main.java"]
        )

    def test_v2_review_rejects_changed_plan_digest_and_submission(self) -> None:
        run = self._v2_auto_review("c", b"source")
        executor = DockerLocalAutoCheckExecutor(runtime_factory=Mock())
        for field, value in (
            ("execution_rule_summary", {**run.execution_rule_summary, "execution_plan": {
                "compile": [], "run": ["sh", "-c", "id"],
            }}),
            ("execution_rule_digest", "0" * 64),
            ("input_asset_id", self.peer_review.report_version.workspace_snapshot.asset_id),
            ("artifact_digest", "0" * 64),
        ):
            with self.subTest(field=field):
                original = getattr(run, field)
                setattr(run, field, value)
                with patch("apps.reviews.checkers._read_asset") as read, self.assertRaises(
                    AutoCheckRejected
                ):
                    executor.execute(run)
                read.assert_not_called()
                setattr(run, field, original)
        legacy_adapter = SimpleNamespace(execute=Mock())
        with (
            patch("apps.reviews.checkers._read_asset", side_effect=[b"source", b'{"cases":[]}']),
            self.assertRaises(AutoCheckRejected) as rejected,
        ):
            DockerLocalAutoCheckExecutor(
                runtime_factory=Mock(return_value=legacy_adapter)
            ).execute(run)
        self.assertEqual(rejected.exception.code, "AUTO_CHECK_EXECUTION_PLAN_UNSUPPORTED")
        legacy_adapter.execute.assert_not_called()

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

    @skipUnless(os.environ.get("LOCAL_DOCKER_INTEGRATION") == "1", "requires local Docker")
    def test_v2_real_docker_reviews_compile_five_languages(self) -> None:
        import docker

        projects = {
            "c": {
                "src/main.c": '#include <stdio.h>\n#include "answer.h"\n'
                'int main(void){printf("%d\\n",answer());}\n',
                "src/answer.h": "static int answer(void){return 42;}\n",
            },
            "cpp": {
                "src/main.cpp": '#include <iostream>\n#include "answer.hpp"\n'
                'int main(){std::cout<<answer()<<"\\n";}\n',
                "src/answer.hpp": "inline int answer(){return 42;}\n",
            },
            "java": {
                "src/Main.java": "import helper.Answer;\npublic class Main{"
                "public static void main(String[]args){System.out.println(Answer.value());}}\n",
                "helper/Answer.java": "package helper;\npublic class Answer{"
                "public static int value(){return 42;}}\n",
            },
            "python": {
                "src/main.py": "from helper import answer\nprint(answer())\n",
                "src/helper.py": "def answer(): return 42\n",
            },
            "go": {
                "src/main.go": 'package main\nimport("fmt";"example.local/review/helper")\n'
                "func main(){fmt.Println(helper.Answer())}\n",
                "go.mod": "module example.local/review\n\ngo 1.25\n",
                "helper/answer.go": "package helper\nfunc Answer()int{return 42}\n",
            },
        }
        tests = json.dumps({
            "comparator": "token", "absolute_tolerance": 99,
            "cases": [{"input": "", "expected": "42.0"} for _ in range(4)],
        }).encode()
        tests_asset = ObjectAsset.objects.get(
            public_id=self.template_version.execution_spec["tests_asset"]
        )
        ObjectAsset.objects.filter(pk=tests_asset.pk).update(
            digest_sha256=hashlib.sha256(tests).hexdigest(), size_bytes=len(tests)
        )
        client = docker.from_env()
        image = client.images.get("experimental-platform-workspace:local")
        adapter = DockerLocalAdapter(
            client=client.api, config={"image": image.id}, config_ref="runtime/review-v2-test"
        )
        executor = DockerLocalAutoCheckExecutor(runtime_factory=Mock(return_value=adapter))
        try:
            for language, files in projects.items():
                with self.subTest(language=language):
                    source = bundle(
                        {path: value.encode() for path, value in files.items()}, max_bytes=65536
                    )
                    run = self._v2_auto_review(language, source, system_artifact=language == "go")
                    with (
                        patch("apps.reviews.checkers.object_storage") as storage,
                        patch("apps.reviews.services.auto_check_executor", return_value=executor),
                    ):
                        storage.return_value.open_object.side_effect = [
                            SimpleNamespace(body=BytesIO(source)),
                            SimpleNamespace(body=BytesIO(tests)),
                        ]
                        completed = execute_auto_check(run_id=run.public_id)
                    self.assertEqual(completed.status, "PASSED", completed.error_code)
                    self.assertFalse(ReviewDecision.objects.filter(review=run.review).exists())
                    changed = self._score(run.review)
                    decision, _review, _task = decide_review(
                        course_id=self.course.public_id, review_id=run.review.public_id,
                        actor=self.teacher, expected_version=changed.row_version,
                        decision="APPROVE", requested_score=Decimal("90"),
                        feedback="Reviewed after real multi-language auto-check",
                        context=self.context(self.teacher),
                    )
                    self.assertEqual(decision.score, Decimal("90"))
                    self.assertEqual(adapter.inventory_resources(), [])
            source = bundle({"main.py": b"print(42.1)\n"}, max_bytes=1024)
            run = self._v2_auto_review(
                "python", source, system_artifact=True, student_select=True
            )
            with (
                patch("apps.reviews.checkers.object_storage") as storage,
                patch("apps.reviews.services.auto_check_executor", return_value=executor),
            ):
                storage.return_value.open_object.side_effect = [
                    SimpleNamespace(body=BytesIO(source)), SimpleNamespace(body=BytesIO(tests)),
                ]
                completed = execute_auto_check(run_id=run.public_id)
            self.assertEqual(completed.status, "FAILED")
            self.assertFalse(ReviewDecision.objects.filter(review=run.review).exists())
            self.assertEqual(adapter.inventory_resources(), [])
        finally:
            client.close()

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

        # Source preview must apply the same course/staff boundary before reading objects.
        with patch("apps.reviews.checkers._read_asset") as read_asset:
            for scoped_client, course, expected_status in (
                (other_client, other_course, 404),
                (assistant_client, self.course, 403),
            ):
                response = scoped_client.get(
                    f"/api/v2/teaching/courses/{course.public_id}/reviews/"
                    f"{self.review.public_id}?include_source=1",
                    HTTP_X_PORTAL="TEACHING",
                    HTTP_X_PROXY_CONTEXT="ingress-v1",
                    REMOTE_ADDR="127.0.0.1",
                )
                self.assertEqual(response.status_code, expected_status, response.content)
            read_asset.assert_not_called()

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

    def _ready_ai_score_batch(self) -> AIScoreBatch:
        TaskPublication.objects.filter(pk=self.publication.pk).update(
            status=TaskPublication.Status.CLOSED,
            closed_at=timezone.now(),
            closed_by=self.teacher,
        )
        batch = start_ai_score_batch(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.teacher,
            context=self.context(self.teacher),
        )

        from apps.agents.rubric_agent import CriterionAssessment, RubricAssessment

        def assessment(**_kwargs: object) -> RubricAssessment:
            return RubricAssessment(
                criteria=[
                    CriterionAssessment(
                        criterion_id=self.criteria[0].public_id,
                        score=Decimal("50"),
                        rationale="The report supports this score.",
                        evidence="Shared report body",
                    ),
                    CriterionAssessment(
                        criterion_id=self.criteria[1].public_id,
                        score=Decimal("30"),
                        rationale="The explanation is incomplete.",
                        evidence="reviews checking",
                    ),
                ]
            )

        with (
            patch("apps.agents.rubric_agent.assess_submission", side_effect=assessment),
            patch("apps.reviews.checkers._read_asset", return_value=b"Submitted source"),
        ):
            for item in batch.suggestions.order_by("id"):
                execute_ai_score_suggestion(suggestion_id=item.public_id)
        batch.refresh_from_db()
        return batch

    def test_ai_scores_need_teacher_confirmation_and_do_not_approve_reports(self) -> None:
        batch = self._ready_ai_score_batch()
        self.assertEqual(batch.status, AIScoreBatch.Status.REVIEW_REQUIRED)
        self.assertEqual(batch.suggestions.filter(status=AIScoreSuggestion.Status.READY).count(), 2)
        self.assertEqual(AuditLog.objects.filter(action="review.ai_score.generate").count(), 2)

        changed = accept_ai_score_batch(
            course_id=self.course.public_id,
            batch_id=batch.public_id,
            actor=self.teacher,
            expected_batch_version=batch.row_version,
            context=self.context(self.teacher),
        )

        self.assertEqual(changed.status, AIScoreBatch.Status.COMPLETED)
        self.assertEqual(
            batch.suggestions.filter(status=AIScoreSuggestion.Status.ACCEPTED).count(), 2
        )
        self.assertEqual(
            CriterionScoreEvent.objects.filter(
                review__in=[self.review, self.peer_review]
            ).count(),
            4,
        )
        self.assertFalse(
            ReviewDecision.objects.filter(review__in=[self.review, self.peer_review]).exists()
        )
        self.assertEqual(self.task.status, ExperimentTask.Status.UNDER_REVIEW)
        self.assertEqual(self.peer_task.status, ExperimentTask.Status.UNDER_REVIEW)

    def test_ai_reads_frozen_multifile_source_with_bounded_masked_input(self) -> None:
        from apps.agents.rubric_agent import CriterionAssessment, RubricAssessment
        from apps.core.project_archive import bundle

        batch = self._ready_ai_score_batch()
        suggestion = batch.suggestions.get(review=self.review)
        assessment = RubricAssessment(criteria=[
            CriterionAssessment(**item) for item in suggestion.criteria
        ])
        AIScoreSuggestion.objects.filter(pk=suggestion.pk).update(status="QUEUED")
        value = bundle({
            "main.py": b"from helper import answer\nprint(answer())",
            "helper.py": b"password=private-value\ndef answer(): return 42",
        }, max_bytes=1024 * 1024)
        asset = self.review.report_version.workspace_snapshot.asset
        ObjectAsset.objects.filter(pk=asset.pk).update(
            media_type="application/gzip", size_bytes=len(value),
            digest_sha256=hashlib.sha256(value).hexdigest(),
        )
        stream = BytesIO(value)
        storage = Mock()
        storage.open_object.return_value = SimpleNamespace(body=stream)
        with (
            patch("apps.reviews.checkers.object_storage", return_value=storage),
            patch("apps.agents.rubric_agent.assess_submission", return_value=assessment) as ai,
        ):
            result = execute_ai_score_suggestion(suggestion_id=suggestion.public_id)
        self.assertEqual(result.status, "READY")
        prompt = ai.call_args.kwargs["report"]
        self.assertIn("FILE: helper.py", prompt)
        self.assertIn("FILE: main.py", prompt)
        self.assertIn("Shared report body", prompt)
        self.assertIn("[REDACTED]", prompt)
        self.assertNotIn("private-value", prompt)
        self.assertLessEqual(len(prompt), 100_000)
        self.assertTrue(stream.closed)
        storage.open_object.assert_called_once_with(
            bucket=asset.bucket, object_key=asset.object_key, version_id=asset.object_version,
        )
        from apps.reviews.serializers import review_detail_data

        asset.refresh_from_db()
        with (
            patch("apps.reviews.checkers._read_asset", return_value=value),
            patch("apps.workspaces.workbench._content_data", return_value={"manual": None}),
        ):
            preview = review_detail_data(self.review, include_source=True)["project"]
        self.assertEqual(preview["snapshot_id"],
                         self.review.report_version.workspace_snapshot.public_id)
        self.assertEqual([item["path"] for item in preview["files"]], ["helper.py", "main.py"])
        self.assertEqual(preview["error_code"], "")
        self.assertFalse(CriterionScoreEvent.objects.filter(review=self.review).exists())

    def test_ai_source_failure_keeps_manual_scoring_available(self) -> None:
        batch = self._ready_ai_score_batch()
        suggestion = batch.suggestions.get(review=self.review)
        AIScoreSuggestion.objects.filter(pk=suggestion.pk).update(status="QUEUED")
        asset = self.review.report_version.workspace_snapshot.asset
        ObjectAsset.objects.filter(pk=asset.pk).update(size_bytes=21 * 1024 * 1024)
        with (
            patch("apps.reviews.checkers.object_storage") as storage,
            patch("apps.agents.rubric_agent.assess_submission") as ai,
        ):
            result = execute_ai_score_suggestion(suggestion_id=suggestion.public_id)
        self.assertEqual(result.status, "FAILED")
        storage.assert_not_called()
        ai.assert_not_called()
        self._score()
        self.assertEqual(CriterionScoreEvent.objects.filter(review=self.review).count(), 2)

    def test_ai_suggestion_cannot_be_applied_to_another_submission(self) -> None:
        batch = self._ready_ai_score_batch()
        suggestion = batch.suggestions.get(review=self.review)
        with self.assertRaises(ResourceNotFound):
            accept_ai_score_suggestion(
                course_id=self.course.public_id, review_id=self.peer_review.public_id,
                suggestion_id=suggestion.public_id, actor=self.teacher,
                expected_review_version=self.peer_review.row_version,
                context=self.context(self.teacher),
            )
        self.assertFalse(CriterionScoreEvent.objects.exists())

    def test_ai_batch_acceptance_rolls_back_when_any_review_changed(self) -> None:
        batch = self._ready_ai_score_batch()
        self._score(self.peer_review)

        with self.assertRaises(RowVersionConflict):
            accept_ai_score_batch(
                course_id=self.course.public_id,
                batch_id=batch.public_id,
                actor=self.teacher,
                expected_batch_version=batch.row_version,
                context=self.context(self.teacher),
            )

        self.assertFalse(CriterionScoreEvent.objects.filter(review=self.review).exists())
        self.assertEqual(
            batch.suggestions.filter(status=AIScoreSuggestion.Status.READY).count(), 2
        )

    def test_ai_batch_api_creates_lists_and_accepts_suggestions(self) -> None:
        TaskPublication.objects.filter(pk=self.publication.pk).update(
            status=TaskPublication.Status.CLOSED,
            closed_at=timezone.now(),
            closed_by=self.teacher,
        )
        client, csrf = self._client(identifier=self.teacher.email, portal="TEACHING")
        url = f"/api/v2/teaching/courses/{self.course.public_id}/ai-score-batches"
        headers = {
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_X_PORTAL": "TEACHING",
            "HTTP_X_PROXY_CONTEXT": "ingress-v1",
            "REMOTE_ADDR": "127.0.0.1",
        }
        with (
            patch("apps.reviews.tasks.run_ai_score_suggestion.apply_async") as enqueue,
            self.captureOnCommitCallbacks(execute=True),
        ):
            created = client.post(
                url,
                {"publication_id": self.publication.public_id},
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="reviews-ai-batch-api",
                **headers,
            )
        self.assertEqual(created.status_code, 202, created.content)
        self.assertEqual(enqueue.call_count, 2)
        batch_id = created.json()["data"]["public_id"]

        detail = client.get(
            f"{url}/{batch_id}?page_size=100",
            HTTP_X_PORTAL="TEACHING",
            HTTP_X_PROXY_CONTEXT="ingress-v1",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(len(detail.json()["data"]["suggestions"]), 2)

        from apps.agents.rubric_agent import CriterionAssessment, RubricAssessment

        def assessment(**_kwargs: object) -> RubricAssessment:
            return RubricAssessment(
                criteria=[
                    CriterionAssessment(
                        criterion_id=criterion.public_id,
                        score=Decimal("50" if index == 0 else "30"),
                        rationale="Evidence-based score.",
                        evidence="Shared report body",
                    )
                    for index, criterion in enumerate(self.criteria)
                ]
            )

        batch = AIScoreBatch.objects.get(public_id=batch_id)
        with (
            patch("apps.agents.rubric_agent.assess_submission", side_effect=assessment),
            patch("apps.reviews.checkers._read_asset", return_value=b"Submitted source"),
        ):
            for suggestion in batch.suggestions.order_by("id"):
                execute_ai_score_suggestion(suggestion_id=suggestion.public_id)
        batch.refresh_from_db()
        accepted = client.post(
            f"{url}/{batch_id}/accept",
            {},
            content_type="application/json",
            HTTP_IF_MATCH=f'"{batch.row_version}"',
            HTTP_IDEMPOTENCY_KEY="reviews-ai-batch-accept-api",
            **headers,
        )
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.assertEqual(accepted.json()["data"]["status"], AIScoreBatch.Status.COMPLETED)
        self.assertFalse(
            ReviewDecision.objects.filter(review__in=[self.review, self.peer_review]).exists()
        )

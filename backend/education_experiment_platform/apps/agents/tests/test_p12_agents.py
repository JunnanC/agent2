from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.tests.helpers import create_user
from apps.agents.models import (
    AgentDefinition,
    AgentMessage,
    AgentSession,
    AgentSource,
    AgentSourceVersion,
    AgentToolCall,
    AgentToolCallState,
    CourseAgentProfile,
    EvalCase,
    EvalSuite,
    KnowledgeBase,
    ModelRoute,
    SessionFeedback,
    SessionFeedbackTriage,
    ToolPolicy,
)
from apps.agents.services import (
    ActorContext,
    activate_profile,
    create_agent_session,
    decide_tool_call,
    evaluate_profile,
    execute_eval_run,
    execute_tool_call,
    request_tool,
    submit_agent_feedback,
    triage_feedback,
)
from apps.core.errors import StateConflict
from apps.courses.models import Enrollment
from apps.experiments.models import ExperimentTask
from apps.experiments.tests.helpers import create_domain, create_draft_publication


class AgentSafetyTests(TestCase):
    def setUp(self) -> None:
        (
            self.teacher,
            self.course,
            self.template_version,
            self.rubric_version,
        ) = create_domain(suffix="p12-owner")
        self.student = create_user(
            email="student-p12@example.test", username="student-p12", display_name="P12 Student"
        )
        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=self.student,
            cycle_no=1,
            status=Enrollment.Status.ACTIVE,
            applied_at=timezone.now(),
            activated_at=timezone.now(),
        )
        self.publication = create_draft_publication(
            owner=self.teacher,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="p12-agent",
        )
        self.task = ExperimentTask.objects.create(
            course=self.course,
            publication=self.publication,
            enrollment=self.enrollment,
            student=self.student,
            template_version=self.template_version,
            runtime_type=self.template_version.runtime_type,
            status=ExperimentTask.Status.READY,
        )
        self.route = ModelRoute.objects.create(
            key="local-rule-based",
            version_no=1,
            provider="LOCAL",
            model_name="rule-based",
            regions=["LOCAL"],
        )
        self.definition = AgentDefinition.objects.create(
            key="p12", version_no=1, model_route=self.route.public_id
        )
        self.knowledge = KnowledgeBase.objects.create(
            course=self.course, name="P12 KB", status=KnowledgeBase.Status.ACTIVE
        )
        self.policy = ToolPolicy.objects.create(
            key="workspace-draft",
            version_no=1,
            tool_name="workspace_draft",
            risk=ToolPolicy.Risk.HIGH,
            allowlist=["workspace_draft"],
            status=ToolPolicy.Status.ACTIVE,
            course=self.course,
        )
        self.profile = CourseAgentProfile.objects.create(
            course=self.course,
            definition=self.definition,
            version_no=1,
            status=CourseAgentProfile.Status.ACTIVE,
            modes=[AgentSession.Mode.KNOWLEDGE_QA, AgentSession.Mode.WORKSPACE_ASSIST],
            knowledge_base=self.knowledge,
            tool_policy=self.policy,
            model_route=self.route.public_id,
        )
        self.context = ActorContext(
            actor_ref=self.student.public_id, portal="USER", trace_id="p12-test"
        )

    def test_knowledge_session_freezes_profile_versions(self) -> None:
        session = create_agent_session(
            actor=self.student,
            course_id=self.course.public_id,
            mode=AgentSession.Mode.KNOWLEDGE_QA,
            context=self.context,
        )
        self.assertEqual(session.profile_version, 1)
        self.assertEqual(session.knowledge_base_id, self.knowledge.pk)
        self.assertEqual(session.tool_policy_id, self.policy.pk)

    def test_high_risk_tool_requires_matching_approval(self) -> None:
        session = AgentSession.objects.create(
            student=self.student,
            course=self.course,
            enrollment=self.enrollment,
            task=self.task,
            profile=self.profile,
            definition=self.definition,
            profile_version=1,
            mode=AgentSession.Mode.WORKSPACE_ASSIST,
            knowledge_base=self.knowledge,
            tool_policy=self.policy,
            model_route=self.route.public_id,
            trace_id="p12-test",
        )
        message = AgentMessage.objects.create(
            session=session,
            role=AgentMessage.Role.USER,
            body="create preview",
            body_digest="a" * 64,
            status=AgentMessage.Status.COMPLETE,
            trace_id="p12-test",
        )
        del message
        with patch("apps.agents.tasks.execute_agent_tool.apply_async"):
            call = request_tool(
                actor=self.student,
                session_id=session.public_id,
                tool_name="workspace_draft",
                arguments={"path": "draft.md"},
                context=self.context,
            )
            self.assertEqual(call.state.status, AgentToolCallState.Status.PENDING_APPROVAL)
            state = decide_tool_call(
                actor=self.student,
                call_id=call.public_id,
                decision="APPROVED",
                reason="student confirmed",
                expected_version=call.state.row_version,
                context=self.context,
            )
        self.assertEqual(state.status, AgentToolCallState.Status.QUEUED)
        self.assertEqual(AgentToolCall.objects.count(), 1)
        with patch("apps.agents.services._workspace_tool_scope_valid", return_value=True):
            completed = execute_tool_call(call_id=call.public_id, trace_id="p12-worker")
        self.assertEqual(completed.status, AgentToolCallState.Status.SUCCEEDED)
        self.assertTrue(completed.output_masked["preview"])

    def test_session_freezes_latest_knowledge_versions(self) -> None:
        source = AgentSource.objects.create(
            knowledge_base=self.knowledge,
            course=self.course,
            source_type=AgentSource.SourceType.STATIC,
            title="Versioned source",
            audience={"course_id": self.course.public_id},
            status=AgentSource.Status.ACTIVE,
        )
        old = AgentSourceVersion.objects.create(
            source=source,
            version_no=1,
            digest_sha256="1" * 64,
            audience=source.audience,
            status=AgentSourceVersion.Status.INDEXED,
        )
        current = AgentSourceVersion.objects.create(
            source=source,
            version_no=2,
            digest_sha256="2" * 64,
            audience=source.audience,
            status=AgentSourceVersion.Status.INDEXED,
        )
        session = create_agent_session(
            actor=self.student,
            course_id=self.course.public_id,
            mode=AgentSession.Mode.KNOWLEDGE_QA,
            context=self.context,
        )
        self.assertEqual(session.knowledge_snapshot, [current.public_id])
        self.assertNotIn(old.public_id, session.knowledge_snapshot)

    def test_feedback_fact_is_append_only_and_triage_is_projection(self) -> None:
        session = create_agent_session(
            actor=self.student,
            course_id=self.course.public_id,
            mode=AgentSession.Mode.KNOWLEDGE_QA,
            context=self.context,
        )
        message = AgentMessage.objects.create(
            session=session,
            role=AgentMessage.Role.ASSISTANT,
            body="answer",
            body_digest="b" * 64,
            status=AgentMessage.Status.COMPLETE,
            trace_id="p12-test",
        )
        feedback = submit_agent_feedback(
            actor=self.student,
            session_id=session.public_id,
            message_id=message.public_id,
            rating="USEFUL",
            issue_type="",
            note="helpful",
            context=self.context,
        )
        triage = SessionFeedbackTriage.objects.create(
            feedback=feedback, actor=self.teacher, status=SessionFeedbackTriage.Status.OPEN
        )
        teacher_context = ActorContext(
            actor_ref=self.teacher.public_id, portal="TEACHING", trace_id="p12-triage"
        )
        changed = triage_feedback(
            course_id=self.course.public_id,
            feedback_id=feedback.public_id,
            actor=self.teacher,
            expected_version=triage.row_version,
            status=SessionFeedbackTriage.Status.CLOSED,
            note="reviewed",
            context=teacher_context,
        )
        self.assertEqual(changed.status, SessionFeedbackTriage.Status.CLOSED)
        self.assertEqual(SessionFeedback.objects.get(pk=feedback.pk).note, "helpful")

    def test_profile_cannot_activate_directly_from_draft(self) -> None:
        draft = CourseAgentProfile.objects.create(
            course=self.course,
            definition=self.definition,
            version_no=2,
            modes=[AgentSession.Mode.KNOWLEDGE_QA],
            model_route=self.route.public_id,
        )
        teacher_context = ActorContext(
            actor_ref=self.teacher.public_id, portal="TEACHING", trace_id="p12-activate"
        )
        with self.assertRaises(StateConflict):
            activate_profile(
                course_id=self.course.public_id,
                profile_id=draft.public_id,
                actor=self.teacher,
                expected_version=draft.row_version,
                context=teacher_context,
            )

    def test_activation_requires_platform_and_course_eval_for_exact_snapshot(self) -> None:
        source = AgentSource.objects.create(
            knowledge_base=self.knowledge,
            course=self.course,
            source_type=AgentSource.SourceType.STATIC,
            title="Gate source",
            audience={"course_id": self.course.public_id},
            status=AgentSource.Status.ACTIVE,
        )
        AgentSourceVersion.objects.create(
            source=source,
            version_no=1,
            digest_sha256="3" * 64,
            audience=source.audience,
            status=AgentSourceVersion.Status.INDEXED,
        )
        suite = EvalSuite.objects.create(
            course=self.course,
            name="Course gate",
            threshold={"minimum_score": 1.0},
        )
        EvalCase.objects.create(
            suite=suite,
            key="course-no-source",
            category="no_source",
            prompt="unknown",
            expected={"citation_status": "NO_RELIABLE_SOURCE"},
            mandatory=True,
        )
        draft = CourseAgentProfile.objects.create(
            course=self.course,
            definition=self.definition,
            version_no=2,
            modes=[AgentSession.Mode.KNOWLEDGE_QA],
            knowledge_base=self.knowledge,
            tool_policy=self.policy,
            model_route=self.route.public_id,
        )
        teacher_context = ActorContext(
            actor_ref=self.teacher.public_id, portal="TEACHING", trace_id="p12-eval"
        )
        with patch("apps.agents.tasks.run_agent_eval.apply_async"):
            _, runs = evaluate_profile(
                course_id=self.course.public_id,
                profile_id=draft.public_id,
                actor=self.teacher,
                expected_version=draft.row_version,
                context=teacher_context,
            )
        self.assertEqual(len(runs), 2)
        for run in runs:
            self.assertTrue(execute_eval_run(run_id=run.public_id, trace_id="p12-eval").passed)
        draft.refresh_from_db()
        activated = activate_profile(
            course_id=self.course.public_id,
            profile_id=draft.public_id,
            actor=self.teacher,
            expected_version=draft.row_version,
            context=teacher_context,
        )
        self.assertEqual(activated.status, CourseAgentProfile.Status.ACTIVE)

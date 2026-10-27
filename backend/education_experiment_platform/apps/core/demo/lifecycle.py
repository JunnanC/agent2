"""Persona-driven demo task lifecycle: provisioning → workspace → report → review → archive."""

from __future__ import annotations

import contextlib
import os
import sys
from collections import Counter
from collections.abc import Callable
from decimal import Decimal
from functools import partial
from typing import Final

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import ActorContext
from apps.archives.models import ArchiveJob
from apps.archives.services import create_archive_export, execute_archive_job
from apps.experiments.models import (
    ExperimentTask,
    TaskExtensionDecision,
    TaskExtensionRequest,
    TaskPublication,
)
from apps.experiments.services import decide_extension, request_extension, transition_task
from apps.governance.models import Quota
from apps.provisioning.models import ProvisioningJob
from apps.provisioning.services import execute_provisioning_job, start_provisioning
from apps.reports.models import ReportDraft
from apps.reports.services import submit_report, update_report_draft
from apps.reviews.models import Review, RubricCriterion
from apps.reviews.services import (
    decide_review,
    execute_auto_check,
    execute_similarity_run,
    score_review_criteria,
)
from apps.workspaces.models import (
    WorkspaceAutosaveLog,
    WorkspaceExecutionRun,
    WorkspaceSession,
)
from apps.workspaces.services import (
    create_checkpoint,
    enter_task,
    execute_execution_run,
    record_operation,
    save_snapshot,
)

from .banks import (
    EXTENSION_REASONS,
    REPORT_BODIES,
    RESUBMIT_BODY,
    REVIEW_FEEDBACK_APPROVE,
    REVIEW_FEEDBACK_REJECT,
)
from .config import BuildContext, persona_for
from .stubs import stubbed_demo_environment

PERSONA_RANK: Final[dict[str, int]] = {
    "assigned": 0,
    "provisioning": 1,
    "ready": 2,
    "in_progress": 3,
    "report_draft": 4,
    "submitted": 5,
    "rejected_resubmit": 6,
    "approved": 7,
    "completed": 8,
}

_DEMO_DEBUG: Final[bool] = os.getenv("DEMO_DEBUG", "") == "1"


def _attempt(description: str, calls: Callable[[], object]) -> bool:
    try:
        calls()
        return True
    except Exception:
        if _DEMO_DEBUG:
            import traceback

            print(f"DEMO-FAIL {description}:", file=sys.stderr)
            traceback.print_exc()
        return False


def run_task_flows(
    ctx: BuildContext,
    admin: User,
    publications: list[TaskPublication],
    counts: Counter[str],
) -> dict[str, int]:
    """Advance every demo task toward its persona's target lifecycle state."""

    publication_ids = [item.public_id for item in publications]
    tasks = (
        ExperimentTask.objects.filter(publication__public_id__in=publication_ids)
        .select_related("student", "publication")
        .order_by("publication__public_id", "student__public_id")
    )
    task_list = list(tasks)
    with stubbed_demo_environment():
        for ord_index, task in enumerate(task_list):
            scaled = (ord_index * 100) // max(1, len(task_list))
            if not _attempt(
                f"flow {task.public_id}",
                partial(run_task_flow, ctx, admin, task, persona_for(scaled), counts),
            ):
                counts["flows.errors"] += 1
    statuses: Counter[str] = Counter()
    for task in ExperimentTask.objects.filter(publication__public_id__in=publication_ids):
        statuses[task.status] += 1
    return dict(statuses)


def run_task_flow(
    ctx: BuildContext,
    admin: User,
    task: ExperimentTask,
    persona: str,
    counts: Counter[str],
) -> None:
    student = task.student
    student_view = ActorContext(student.public_id, "USER", ctx.trace_id)
    rank = PERSONA_RANK.get(persona, 5)
    task.refresh_from_db()

    if task.status == ExperimentTask.Status.ASSIGNED:
        _seed_extension(ctx, task, student_view, counts)
        if rank == 0:
            return
        if persona == "cancelled":
            _transition(
                ctx,
                task,
                ExperimentTask.Status.CANCELLED,
                "CANCEL",
                actor=student,
                context=student_view,
            )
            return
        if persona == "expired":
            _transition(
                ctx,
                task,
                ExperimentTask.Status.EXPIRED,
                "EXPIRE",
                actor=None,
                context=ActorContext("demo-runtime", "WORKER", ctx.trace_id),
            )
            return
        _ensure_user_quota(ctx, admin, student, counts)
        task, _job = start_provisioning(
            task_id=task.public_id,
            actor=student,
            expected_version=task.row_version,
            context=student_view,
        )
        counts["provisioning.ProvisioningJob"] += 1
        if persona == "failed":
            _attempt(
                f"task {task.public_id} failed-transition",
                lambda: _transition(
                    ctx,
                    task,
                    ExperimentTask.Status.FAILED,
                    "PROVISION",
                    actor=None,
                    context=ActorContext("demo-runtime", "WORKER", ctx.trace_id),
                    reason="演示数据集：运行时不可用",
                ),
            )
            return
        if rank == 1:
            return

    task.refresh_from_db()
    if task.status == ExperimentTask.Status.PROVISIONING:
        if persona == "failed":
            _transition(
                ctx,
                task,
                ExperimentTask.Status.FAILED,
                "PROVISION",
                actor=None,
                context=ActorContext("demo-runtime", "WORKER", ctx.trace_id),
                reason="演示数据集：运行时不可用",
            )
            return
        if rank >= 2:
            _finish_provisioning(task)
            task.refresh_from_db()
        else:
            return
    if task.status not in {
        ExperimentTask.Status.READY,
        ExperimentTask.Status.IN_PROGRESS,
        ExperimentTask.Status.REPORT_DRAFT,
    }:
        return

    if rank >= 3:
        task, session_token = _enter_context(ctx, task, student_view)
        task.refresh_from_db()
        _workspace_ops(ctx, task, student_view, session_token, counts)
        if rank >= 4:
            _draft_and_submit(ctx, task, rank, student_view, counts)

    _review_path(ctx, task, persona, counts)
    task.refresh_from_db()
    if task.status == ExperimentTask.Status.UNDER_REVIEW:
        # second pass lets the resubmission persona finish its round-2 approval.
        _review_path(ctx, task, persona, counts)
    _decide_pending_extension(ctx, task, counts)


def _transition(
    ctx: BuildContext,
    task: ExperimentTask,
    status: str,
    trigger: str,
    *,
    actor: User | None,
    context: ActorContext,
    reason: str = "演示数据集状态演练",
) -> None:
    with contextlib.suppress(Exception):
        transition_task(
            task_id=task.public_id,
            to_status=status,
            actor=actor,
            expected_version=task.row_version,
            trigger=trigger,
            reason=reason,
            detail={"source": "demo-dataset"},
            context=context,
        )
        task.refresh_from_db()


def _finish_provisioning(task: ExperimentTask) -> None:
    job = task.provisioning_jobs.order_by("-attempt_no").first()
    if job is None:
        return
    if job.status in {ProvisioningJob.Status.QUEUED, ProvisioningJob.Status.RUNNING}:
        _attempt(
            f"job {job.public_id} execute",
            lambda: execute_provisioning_job(job_id=job.public_id),
        )
        task.refresh_from_db()


def _ensure_user_quota(
    ctx: BuildContext,
    admin: User,
    student: User,
    counts: Counter[str],
) -> None:
    key = f"USER:{student.public_id}"
    if Quota.objects.filter(scope_key=key).exists():
        return
    with contextlib.suppress(Exception):
        Quota.objects.create(
            scope_type=Quota.ScopeType.USER,
            scope_key=key,
            user=student,
            max_concurrent_instances=6,
            max_concurrent_starts=6,
            max_cpu_millicores=40000,
            max_memory_mb=80000,
            max_disk_gb=200,
            max_object_storage_bytes=50_000_000_000,
            max_agent_tokens_per_day=1_000_000,
            max_agent_requests_per_minute=200,
            updated_by=admin,
            change_reason="演示数据集用户配额",
        )
        counts["governance.Quota"] += 1


def _enter_context(
    ctx: BuildContext,
    task: ExperimentTask,
    student_view: ActorContext,
) -> tuple[ExperimentTask, str]:
    with contextlib.suppress(Exception):
        task, _session, token = enter_task(
            task_id=task.public_id,
            actor=task.student,
            expected_version=task.row_version,
            context=student_view,
        )
        task.refresh_from_db()
        return task, token
    session = WorkspaceSession.objects.filter(
        task=task, status=WorkspaceSession.Status.ACTIVE
    ).first()
    return task, "" if session is None else "demo-session"


def _workspace_ops(
    ctx: BuildContext,
    task: ExperimentTask,
    student_view: ActorContext,
    session_token: str,
    counts: Counter[str],
) -> None:
    if not session_token:
        return
    session = WorkspaceSession.objects.filter(
        task=task, status=WorkspaceSession.Status.ACTIVE
    ).first()
    if session is None:
        return
    saved = WorkspaceAutosaveLog.objects.filter(task=task).count()
    for seq in range(saved + 1, min(saved + 2, 2) + 1):
        fresh = WorkspaceSession.objects.get(pk=session.pk)
        _attempt(
            f"snapshot {task.public_id} seq {seq}",
            partial(
                _save_snapshot, seq, fresh, task, session_token, student_view
            ),
        )
        counts["workspaces.WorkspaceSnapshot"] += 1
    _ensure_checkpoint(ctx, task, student_view, session_token, counts)
    _ensure_execution_run(ctx, task, student_view, session_token, counts)


def _save_snapshot(
    seq: int,
    session: WorkspaceSession,
    task: ExperimentTask,
    session_token: str,
    student_view: ActorContext,
) -> None:
    save_snapshot(
        task_id=task.public_id,
        actor=task.student,
        token=session_token,
        client_seq=seq,
        base_version=session.current_version,
        upload=SimpleUploadedFile(
            f"demo-workspace-{seq}.txt",
            f"演示工作台输出，第 {seq} 次保存，任务 {task.public_id}".encode(),
            content_type="text/plain",
        ),
        context=student_view,
    )


def _ensure_checkpoint(
    ctx: BuildContext,
    task: ExperimentTask,
    student_view: ActorContext,
    session_token: str,
    counts: Counter[str],
) -> None:
    if not task.workspace_checkpoints.exists():
        with contextlib.suppress(Exception):
            create_checkpoint(
                task_id=task.public_id,
                actor=task.student,
                token=session_token,
                name="演示检查点",
                context=student_view,
            )
            counts["workspaces.WorkspaceCheckpoint"] += 1


def _ensure_execution_run(
    ctx: BuildContext,
    task: ExperimentTask,
    student_view: ActorContext,
    session_token: str,
    counts: Counter[str],
) -> None:
    del ctx
    if WorkspaceExecutionRun.objects.filter(task=task).exists():
        return
    session = WorkspaceSession.objects.filter(
        task=task, status=WorkspaceSession.Status.ACTIVE
    ).first()
    if session is None:
        return
    with contextlib.suppress(Exception):
        record_operation(
            session=session,
            token=session_token,
            actor=task.student,
            operation="RUN_CHECK",
            arguments={"source": "demo-dataset"},
            request_key=f"demo-run:{task.public_id}",
            context=student_view,
        )
        counts["workspaces.WorkspaceExecutionRun"] += 1
    pending = WorkspaceExecutionRun.objects.filter(
        task=task, status=WorkspaceExecutionRun.Status.QUEUED
    ).first()
    if pending is not None:
        with contextlib.suppress(Exception):
            execute_execution_run(
                execution_run_id=pending.public_id,
                trace_id=student_view.trace_id,
            )


def _draft_and_submit(
    ctx: BuildContext,
    task: ExperimentTask,
    rank: int,
    student_view: ActorContext,
    counts: Counter[str],
) -> None:
    task.refresh_from_db()
    draft = ReportDraft.objects.filter(task=task).first()
    if draft is None:
        return
    if draft.status == ReportDraft.Status.DRAFT and not draft.body_markdown:
        with contextlib.suppress(Exception):
            update_report_draft(
                task_id=task.public_id,
                actor=task.student,
                body_markdown=REPORT_BODIES[_student_index(task) % 2].format(
                    task=task.publication.title
                ),
                expected_version=draft.row_version,
                context=student_view,
            )
            counts["reports.ReportDraft"] += 1
    task.refresh_from_db()
    if rank >= 5 and task.status in {
        ExperimentTask.Status.IN_PROGRESS,
        ExperimentTask.Status.REPORT_DRAFT,
    }:
        refreshed = ReportDraft.objects.filter(task=task).first()
        if refreshed is None or refreshed.status != ReportDraft.Status.DRAFT:
            return
        if not refreshed.body_markdown:
            return
        if _attempt(
            f"submit {task.public_id}",
            lambda: submit_report(
                task_id=task.public_id,
                actor=task.student,
                expected_task_version=task.row_version,
                context=student_view,
            ),
        ):
            counts["experiments.SubmittedReports"] += 1
            task.refresh_from_db()


def _review_path(
    ctx: BuildContext,
    task: ExperimentTask,
    persona: str,
    counts: Counter[str],
) -> None:
    task.refresh_from_db()
    if task.status != ExperimentTask.Status.UNDER_REVIEW:
        return
    teacher = task.course.owner
    teaching = ActorContext(teacher.public_id, "TEACHING", ctx.trace_id)
    index = _student_index(task)
    review = Review.objects.filter(task=task).order_by("-round_no").first()
    if review is None:
        return

    if persona == "submitted":
        _execute_queued_checks(review, index, counts, require_all=False)
        return
    if persona == "rejected_resubmit":
        _rejected_resubmit_path(ctx, task, review, teacher, teaching, counts)
        return
    if persona not in {"approved", "completed"}:
        return

    _execute_queued_checks(review, index, counts)
    review.refresh_from_db()
    review = _score_and_decide(
        ctx, task, review, teacher, teaching, Decimal("1.00"), counts
    )
    task.refresh_from_db()
    if persona != "completed":
        return
    job = ArchiveJob.objects.filter(task=task).order_by("-created_at").first()
    if job is None:
        return
    if job.status not in {ArchiveJob.Status.PASSED, ArchiveJob.Status.FAILED}:
        try:
            finished = execute_archive_job(
                job_id=job.public_id,
                trace_id=ctx.trace_id,
                raise_on_failure=_DEMO_DEBUG,
            )
        except Exception:
            if _DEMO_DEBUG:
                import traceback

                traceback.print_exc()
            return
        counts["archives.ArchiveJob"] += 1
        if _DEMO_DEBUG:
            failure = getattr(finished, "failure_record", None)
            print(
                f"DBG archive task={task.public_id} status={finished.status} "
                f"error={getattr(failure, 'error_code', '')} "
                f"detail={getattr(failure, 'detail_masked', '')} "
                f"message={getattr(failure, 'message_masked', '')}",
                file=sys.stderr,
            )
    job.refresh_from_db()
    if index % 5 == 0 and job.status == ArchiveJob.Status.PASSED:
        with contextlib.suppress(Exception):
            create_archive_export(
                course_id=task.course.public_id,
                archive_id=job.public_id,
                actor=teacher,
                expected_version=job.row_version,
                token=f"demo-export-{task.public_id}-{index}",
                context=teaching,
            )
            counts["archives.ArchiveExportGrant"] += 1


def _rejected_resubmit_path(
    ctx: BuildContext,
    task: ExperimentTask,
    review: Review,
    teacher: User,
    teaching: ActorContext,
    counts: Counter[str],
) -> None:
    if review.round_no == 1:
        _execute_queued_checks(review, _student_index(task), counts, require_all=True)
        _score_and_decide(
            ctx,
            task,
            review,
            teacher,
            teaching,
            Decimal("0.6"),
            counts,
            decision="REJECT",
            feedback=REVIEW_FEEDBACK_REJECT,
        )
        task.refresh_from_db()
        if task.status != ExperimentTask.Status.REPORT_DRAFT:
            return
        draft = ReportDraft.objects.filter(task=task).first()
        if draft is not None and draft.status == ReportDraft.Status.DRAFT:
            with contextlib.suppress(Exception):
                update_report_draft(
                    task_id=task.public_id,
                    actor=task.student,
                    body_markdown=RESUBMIT_BODY,
                    expected_version=draft.row_version,
                    context=ActorContext(task.student.public_id, "USER", ctx.trace_id),
                )
                counts["reports.ReportDraft"] += 1
            task.refresh_from_db()
            with contextlib.suppress(Exception):
                submit_report(
                    task_id=task.public_id,
                    actor=task.student,
                    expected_task_version=task.row_version,
                    context=ActorContext(task.student.public_id, "USER", ctx.trace_id),
                )
                counts["experiments.SubmittedReports"] += 1
        return
    if review.round_no >= 2:
        _execute_queued_checks(review, _student_index(task), counts)
        review.refresh_from_db()
        _score_and_decide(
            ctx,
            task,
            review,
            teacher,
            teaching,
            Decimal("1.00"),
            counts,
        )
        task.refresh_from_db()


def _execute_queued_checks(
    review: Review,
    index: int,
    counts: Counter[str],
    *,
    require_all: bool = True,
) -> None:
    if not require_all and index % 2 == 1:
        return
    for run in review.auto_check_runs.filter(status="QUEUED"):
        if not _attempt(
            f"auto-check {run.public_id}",
            partial(execute_auto_check, run_id=run.public_id),
        ):
            continue
        counts["reviews.AutoCheckRun"] += 1
    if not require_all and index % 3 != 0:
        return
    for run in review.similarity_runs.filter(status="QUEUED"):
        if not _attempt(
            f"similarity {run.public_id}",
            partial(execute_similarity_run, run_id=run.public_id),
        ):
            continue
        counts["reviews.SimilarityRun"] += 1


def _score_and_decide(
    ctx: BuildContext,
    task: ExperimentTask,
    review: Review,
    teacher: User,
    teaching: ActorContext,
    factor: Decimal,
    counts: Counter[str],
    decision: str = "APPROVE",
    feedback: str = REVIEW_FEEDBACK_APPROVE,
) -> Review:
    del ctx
    criteria = list(
        RubricCriterion.objects.filter(rubric_version=review.rubric_version, is_active=True)
    )
    if not criteria:
        return review
    review.refresh_from_db()
    scores = [
        {
            "criterion_id": item.public_id,
            "score": str((item.max_score * factor).quantize(Decimal("0.01"))),
            "note": "演示数据集评阅",
        }
        for item in criteria
    ]
    if not _attempt(
        f"score {review.public_id}",
        lambda: score_review_criteria(
            course_id=task.course.public_id,
            review_id=review.public_id,
            actor=teacher,
            expected_version=review.row_version,
            scores=scores,
            context=teaching,
        ),
    ):
        return review
    counts["reviews.CriterionScore"] += 1
    review.refresh_from_db()
    total = Decimal("0")
    if decision == "APPROVE":
        for item in criteria:
            total += item.max_score
    if not _attempt(
        f"decide {review.public_id}",
        lambda: decide_review(
            course_id=task.course.public_id,
            review_id=review.public_id,
            actor=teacher,
            expected_version=review.row_version,
            decision=decision,
            requested_score=None if decision == "REJECT" else total,
            feedback=feedback,
            context=teaching,
        ),
    ):
        return review
    counts["reviews.ReviewDecision"] += 1
    return review


def _seed_extension(
    ctx: BuildContext,
    task: ExperimentTask,
    student_view: ActorContext,
    counts: Counter[str],
) -> None:
    offset = _student_index(task)
    deadline_base = task.publication.window_end
    if deadline_base is None or offset % 6 != 0:
        return
    if TaskExtensionRequest.objects.filter(task=task).exists():
        return
    with contextlib.suppress(Exception):
        request_extension(
            task_id=task.public_id,
            actor=task.student,
            data={
                "requested_deadline": deadline_base + timezone.timedelta(days=2),
                "reason": EXTENSION_REASONS[offset % 2],
            },
            context=student_view,
        )
        counts["experiments.TaskExtensionRequest"] += 1


def _decide_pending_extension(
    ctx: BuildContext,
    task: ExperimentTask,
    counts: Counter[str],
) -> None:
    offset = _student_index(task)
    request = TaskExtensionRequest.objects.filter(
        task=task, status=TaskExtensionRequest.Status.PENDING
    ).first()
    if request is None:
        return
    teacher = task.course.owner
    decision = (
        TaskExtensionDecision.Decision.REJECT
        if offset % 9 == 0
        else TaskExtensionDecision.Decision.APPROVE
    )
    with contextlib.suppress(Exception):
        decide_extension(
            course_id=task.course.public_id,
            request_id=request.public_id,
            actor=teacher,
            decision=decision,
            reason="演示数据集延期处理",
            expected_version=request.row_version,
            context=ActorContext(teacher.public_id, "TEACHING", ctx.trace_id),
        )
        counts["experiments.TaskExtensionDecided"] += 1


def _student_index(task: ExperimentTask) -> int:
    username = task.student.username
    tail = username.rsplit("-", 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return 0

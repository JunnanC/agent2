import { request, newIdempotencyKey } from "@edu/auth-client";
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { assessmentPartsApi, teachingApi } from "@edu/api-client";
import type { Chapter, Publication, Template } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  ConfirmDialog, EmptyState, Modal, Panel, RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import { RubricCreate } from "@/components/rubric-create";
import { LabDesignDialog } from "@/components/lab-design";
import { LabEnvironments, TestLabEnvironment } from "@/components/lab-environments";
import { PRECHECK_STATUS_LABEL, PUBLICATION_STATUS_LABEL, apiErrorMessage, formatDateTime } from "@/lib/format";
import { precheckFailureMessage } from "@/lib/precheck-errors";

interface PrecheckStage {
  status: string;
  message?: string;
}

function toIso(value: string): string {
  // datetime-local 值转 UTC ISO;浏览器时区解释,后端保存为 aware datetime
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}

const initialCreateForm = {
  chapterId: "",
  templateId: "",
  rubricId: "",
  title: "",
  description: "",
  window_start: "",
  window_end: "",
  score_release_at: "",
  assignment_deadline: "",
  report_required: true,
  review_mode: "MANUAL",
};

export function Publishing() {
  const { courseId = "" } = useParams();
  const toast = useToast();
  const [searchParams] = useSearchParams();
  const [withdrawTarget, setWithdrawTarget] = useState<Publication | null>(null);
  const [closeTarget, setCloseTarget] = useState<Publication | null>(null);
  const [createOpen, setCreateOpen] = useState(Boolean(searchParams.get("template")));
  const [designTarget, setDesignTarget] = useState<string | null>(null);
  const [environmentsOpen, setEnvironmentsOpen] = useState(false);
  const [createForm, setCreateForm] = useState({ ...initialCreateForm, templateId: searchParams.get("template") ?? "" });

  const publications = useQuery({
    queryKey: keys.publications(courseId, {}),
    queryFn: () => teachingApi.publications(courseId, {}),
  });

  const courseChapters = useQuery({ queryKey: keys.courseResource(courseId, "chapters"), queryFn: () => teachingApi.courseResource<Chapter>(courseId, "chapters") });
  const templates = useQuery({
    queryKey: keys.templates(courseId),
    queryFn: () => teachingApi.templates(courseId),
    enabled: createOpen,
  });
  const rubrics = useQuery({
    queryKey: keys.rubrics(courseId),
    queryFn: () => teachingApi.rubrics(courseId),
    enabled: createOpen,
  });

  const selectedTemplate: Template | undefined = (templates.data?.rows ?? [])
    .find((row) => row.public_id === createForm.templateId);
  const selectedRubric = (rubrics.data?.rows ?? []).find((row) => row.public_id === createForm.rubricId);
  const selectedVersion = useQuery({
    queryKey: keys.templateVersion(courseId, selectedTemplate?.current_version_id ?? ""),
    queryFn: () => teachingApi.templateVersion(courseId, selectedTemplate!.current_version_id!),
    enabled: Boolean(selectedTemplate?.current_version_id && createOpen),
  });
  const hasProgramming = selectedVersion.data?.chapters?.some((chapter) =>
    chapter.tasks.some((task) => task.task_type === "PROGRAMMING" || !["SINGLE_CHOICE", "MULTIPLE_CHOICE"].includes(task.task_type))) ?? true;

  const rows = useMemo(() => publications.data?.rows ?? [], [publications.data]);

  /** 预检面板：取第一门待处理发布（DRAFT/PRECHECK/READY）的最新预检运行 */
  const pendingPublication = rows.find((row) => row.template_version_id
    && ["DRAFT", "PRECHECK", "READY"].includes(row.status));
  const pendingVersionId = pendingPublication?.template_version_id ?? "";
  const precheckRuns = useQuery({
    queryKey: keys.precheckRuns(pendingVersionId),
    queryFn: () => teachingApi.precheckRuns(courseId, pendingVersionId),
    enabled: Boolean(pendingVersionId),
    refetchInterval: (query) => {
      const data = query.state.data as { rows?: Array<{ status?: string }> };
      const status = data?.rows?.[0]?.status;
      return ["QUEUED", "RUNNING", "RETRY"].includes(String(status ?? "")) ? 4000 : false;
    },
  });
  const latestPrecheck = precheckRuns.data?.rows?.[0];
  const precheckStages: PrecheckStage[] = (latestPrecheck?.stage_results ?? []).map((stage) => ({ message: stage.stage, status: stage.result === "PASSED" ? "SUCCEEDED" : stage.result }));
  const precheckPassed = precheckStages.filter((stage) => stage.status === "SUCCEEDED").length;
  const precheckTotal = precheckStages.length;

  const taskTotal = rows
    .filter((row) => row.status === "PUBLISHED")
    .reduce((sum, row) => sum + (row.audience_count ?? 0), 0);

  const invalidate = () => void publications.refetch();
  const templateUpload = useMutation({
    mutationFn: ({ publication, file }: { publication: Publication; file: File }) =>
      assessmentPartsApi.uploadTemplate(courseId, publication.public_id, file, publication.row_version),
    onSuccess: () => { toast.notify("报告模板已上传"); invalidate(); },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const publish = useMutation({
    mutationFn: (target: Publication) =>
      teachingApi.publishPublication(courseId, target.public_id, target.row_version),
    onSuccess: () => { toast.notify("发布作业已提交，可查看进度"); invalidate(); },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const withdraw = useMutation({
    mutationFn: (target: Publication) =>
      teachingApi.withdrawPublication(courseId, target.public_id, target.row_version),
    onSuccess: () => { toast.notify("实验已撤回"); setWithdrawTarget(null); invalidate(); },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const close = useMutation({
    mutationFn: (target: Publication) =>
      teachingApi.closePublication(courseId, target.public_id, target.row_version),
    onSuccess: () => { toast.notify("实验已关闭"); setCloseTarget(null); invalidate(); },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const runPrecheck = useMutation({
    mutationFn: async (versionId: string) => {
      // The precheck endpoint requires If-Match; refresh the version row first.
      const version = await teachingApi.templateVersion(courseId, versionId);
      if (["PUBLISHED", "PRECHECK_PASSED"].includes(version.status)) return { reused: true };
      return teachingApi.precheck(courseId, versionId, version.row_version);
    },
    onSuccess: (result) => { toast.notify("reused" in result ? "该模板版本已通过预检，可直接发布实验" : "预检作业已提交，进度见预检状态"); void precheckRuns.refetch(); },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const assignChapter = useMutation({
    mutationFn: ({publication, chapterId}: {publication: Publication; chapterId: string}) => request(`/teaching/courses/${courseId}/experiments/${publication.public_id}/course-chapter`, {method:"PATCH", body:{chapter_id:chapterId}, ifMatch:publication.row_version, idempotencyKey:newIdempotencyKey()}),
    onSuccess: () => { void publications.refetch(); toast.notify("实验所属章节已更新"); },
    onError: (error: Error) => toast.notify(apiErrorMessage(error), "error"),
  });
  const createPublication = useMutation({
    mutationFn: () => {
      const versionId = selectedTemplate?.current_version_id ?? "";
      const rubricVersionId = selectedRubric?.current_version_id ?? "";
      if (!versionId) {
        return Promise.reject(new Error("请选择已发布实验模板"));
      }
      return teachingApi.createPublication(courseId, {
        template_version_id: versionId,
        rubric_version_id: hasProgramming && createForm.report_required ? rubricVersionId || null : null,
        title: createForm.title.trim(),
        course_chapter_id: createForm.chapterId,
        description: createForm.description.trim(),
        audience_mode: "ALL_ACTIVE",
        late_enrollment_policy: "DO_NOT_ASSIGN",
        window_start: toIso(createForm.window_start),
        window_end: toIso(createForm.window_end),
        score_release_at: createForm.score_release_at ? toIso(createForm.score_release_at) : null,
        assignment_deadline: createForm.assignment_deadline ? toIso(createForm.assignment_deadline) : undefined,
        report_required: hasProgramming && createForm.report_required,
        review_mode: createForm.review_mode,
        prerequisites: [],
      });
    },
    onSuccess: () => {
      toast.notify("发布草稿已创建，运行预检通过后发布");
      setCreateOpen(false);
      setCreateForm({ ...initialCreateForm });
      invalidate();
    },
    onError: (error) => toast.notify(error instanceof Error ? error.message : apiErrorMessage(error), "error"),
  });

  const createReady = Boolean(
    createForm.chapterId && createForm.templateId && createForm.title.trim()
    && createForm.window_start && createForm.window_end,
  );

  return (
    <>
      <div className="tab-head">
        <h2>实验发布</h2>
        <div className="page-actions">
          <button type="button" className="btn" onClick={() => setEnvironmentsOpen(true)}>实验环境</button>
          <button type="button" className="btn primary" onClick={() => setDesignTarget("")}>新建实验</button>
        </div>
      </div>

      <Panel>
        <RequestStateView
          loading={publications.isLoading}
          error={publications.error}
          onRetry={() => invalidate()}
          empty={!rows.length}
          emptyState={(
            <EmptyState
              title="暂无实验发布"
              hint="设置实验指导、题目、分值和截止时间后发布给本教学班。"
              action={<button type="button" className="btn primary" onClick={() => setDesignTarget("")}>新建实验</button>}
            />
          )}
        >
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>实验发布</th><th>版本</th><th>对象</th><th>时间窗口</th><th>任务数</th><th>状态</th><th className="table-actions">操作</th></tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const allowed = row.allowed_actions ?? [];
                  const direct = !row.template_version_id;
                  const environmentId = "environment_id" in row && typeof row.environment_id === "string"
                    ? row.environment_id : "";
                  return (
                    <tr key={row.public_id}>
                      <td><strong>{row.title}</strong><small style={{ display: "block" }}>{row.template_name ?? row.template_version_id}</small>
                        {!direct && <select className="field" aria-label={`${row.title} 所属课程章节`} value={row.course_chapter_id ?? ""} disabled={assignChapter.isPending} onChange={event => assignChapter.mutate({publication:row,chapterId:event.target.value})}><option value="" disabled>尚未归入章节</option>{courseChapters.data?.rows.map(chapter => <option key={chapter.public_id} value={chapter.public_id}>{chapter.title}</option>)}</select>}
                      </td>
                      <td>{row.version_no ? `v${row.version_no}` : "—"}</td>
                      <td>
                        {row.audience_count
                          ? <span>{row.audience_count} 名学生</span>
                          : <span className="subtle">—</span>}
                      </td>
                      <td data-wrap>
                        {row.status === "PUBLISHED"
                          ? `${formatDateTime(row.window_start)} — ${formatDateTime(row.window_end)}`
                          : row.window_start ? `${formatDateTime(row.window_start)} — ${formatDateTime(row.window_end)}`
                            : "待设置"}
                      </td>
                      <td>{row.audience_count ?? "—"}</td>
                      <td>
                        <StatusBadge tone={row.status === "PUBLISHED" ? "good"
                          : row.status === "FAILED" ? "bad"
                            : row.status === "DRAFT" || row.status === "PRECHECK" || row.status === "READY" ? "warn"
                              : "neutral"}>
                          {PUBLICATION_STATUS_LABEL[row.status] ?? row.status}
                        </StatusBadge>
                        {row.status === "FAILED" && row.publication_error ? (
                          <small style={{ display: "block", color: "var(--red)" }}>
                            {row.publication_error.message ?? row.publication_error.code}
                          </small>
                        ) : null}
                      </td>
                      <td className="table-actions">
                        {(!direct || row.status !== "DRAFT") && <Link className="btn sm"
                          to={`/courses/${courseId}/publishing/${row.public_id}/reviews${direct ? "?tab=reports&direct=1" : ""}`}>报告与评审</Link>}
                        {direct && row.status === "DRAFT" && <button type="button" className="btn sm"
                          onClick={() => setDesignTarget(row.public_id)}>编辑草稿</button>}
                        {direct && environmentId && <TestLabEnvironment courseId={courseId}
                          environmentId={environmentId} publicationId={row.public_id} />}
                        {["DRAFT", "PUBLISH_FAILED"].includes(row.status) && (!direct || row.report_required) && <label className="btn sm" aria-label={`${row.title}的报告模板`}>
                          <span>{row.report_template ? "替换报告模板" : "上传报告模板"}</span>
                          <input type="file" accept={direct ? ".docx" : ".docx,.pdf,.md,.txt"} className="report-template-file-input"
                            aria-label={`上传 ${row.title} 的报告模板`} disabled={templateUpload.isPending}
                            onChange={(event) => {
                              const file = event.currentTarget.files?.[0];
                              event.currentTarget.value = "";
                              if (file) templateUpload.mutate({ publication: row, file });
                            }} />
                        </label>}
                        {row.report_template && <span className="subtle">{row.report_template.file_name}</span>}
                        {!direct && row.status === "DRAFT" ? (
                          <button type="button" className="btn sm" disabled={runPrecheck.isPending}
                            onClick={() => row.template_version_id && runPrecheck.mutate(row.template_version_id)}>
                            {runPrecheck.isPending ? "提交中…" : "检查预检状态"}
                          </button>
                        ) : null}
                        {allowed.includes("publish") ? (
                          <button type="button" className="btn sm primary" disabled={publish.isPending || templateUpload.isPending}
                            onClick={() => publish.mutate(row)}>
                            {publish.isPending && publish.variables === row ? "提交中…" : "发布"}
                          </button>
                        ) : null}
                        {allowed.includes("withdraw") ? (
                          <button type="button" className="btn sm" onClick={() => setWithdrawTarget(row)}>撤回</button>
                        ) : null}
                        {allowed.includes("close") ? (
                          <button type="button" className="btn sm" onClick={() => setCloseTarget(row)}>关闭</button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>

      <div className="grid three section">
        <Panel title={<><h2>预检状态</h2>
          {latestPrecheck ? (
            <StatusBadge tone={latestPrecheck.status === "PASSED" ? "good"
              : latestPrecheck.status === "FAILED" ? "bad" : "blue"}>
              {latestPrecheck.status === "FAILED" || precheckTotal === 0
                ? PRECHECK_STATUS_LABEL[latestPrecheck.status]
                : `${precheckPassed} / ${precheckTotal} 通过`}
            </StatusBadge>
          ) : pendingPublication ? <span className="status warn">尚未预检</span> : <span className="status neutral">无待发布</span>}
        </>}>
          {latestPrecheck?.status === "FAILED" && <p>{precheckFailureMessage(latestPrecheck)}</p>}
          {precheckStages.length > 0 ? (
            precheckStages.map((stage, index) => {
              const ok = stage.status === "SUCCEEDED";
              const failed = stage.status === "FAILED";
              return (
                <div key={index} className="status-line" style={{
                  background: ok ? "var(--green-soft)" : failed ? "var(--red-soft)" : "var(--amber-soft)",
                  color: ok ? "var(--green)" : failed ? "var(--red)" : "var(--amber)",
                  marginBottom: 4,
                }}>
                  {ok ? "✓" : failed ? "×" : "!"}　{stage.message ?? "阶段执行中"}
                </div>
              );
            })
          ) : !latestPrecheck ? (
            <div className="state-block">
              <strong>{pendingPublication ? "尚未运行预检" : "暂无待预检发布"}</strong>
              <p>预检运行后这里将展示镜像治理、运行时健康与章节任务校验结果。</p>
            </div>
          ) : null}
        </Panel>
        <Panel title={<><h2>任务对账</h2>{taskTotal > 0 ? <span className="status blue">{`${taskTotal} 个任务`}</span> : null}</>}>
          <div className="section">
            <p className="subtle" style={{ margin: 0 }}>按已发布实验的受众统计任务数。</p>
          </div>
        </Panel>
        <Panel title={<><h2>发布窗口</h2><span className="status blue">{`${rows.filter((row) => row.status === "PUBLISHED").length} 个进行中`}</span></>}>
          {rows.filter((row) => row.status === "PUBLISHED").length ? (
            rows.filter((row) => row.status === "PUBLISHED").map((row) => (
              <div className="status-line" key={row.public_id} style={{ marginBottom: 4 }}>
                <strong style={{ marginRight: 6 }}>{row.title}</strong>
                {formatDateTime(row.window_start)} — {formatDateTime(row.window_end)}
                {row.assignment_deadline ? ` · 分配截止 ${formatDateTime(row.assignment_deadline)}` : ""}
              </div>
            ))
          ) : (
            <p className="subtle" style={{ margin: 0 }}>暂无进行中的发布窗口。</p>
          )}
        </Panel>
      </div>

      {designTarget !== null && <LabDesignDialog courseId={courseId} publicationId={designTarget}
        onClose={() => setDesignTarget(null)} onSaved={() => { setDesignTarget(null); invalidate(); }} />}
      {environmentsOpen && <LabEnvironments courseId={courseId} onClose={() => setEnvironmentsOpen(false)} />}
      <Modal open={createOpen} onClose={() => setCreateOpen(false)} eyebrow="实验发布"
        title="创建发布草稿"
        wide
        actions={(
          <>
            <button type="button" className="btn" onClick={() => setCreateOpen(false)}>取消</button>
            <button type="button" className="btn primary" disabled={!createReady || createPublication.isPending}
              onClick={() => createPublication.mutate()}>
              {createPublication.isPending ? "创建中…" : "创建草稿"}
            </button>
          </>
        )}>
        <div style={{ display: "grid", gap: 10 }}>
          {createOpen && <RubricCreate key={courseId} courseId={courseId} onCreated={() => void rubrics.refetch()} />}
          <label className="form-label" htmlFor="pub-template">实验模板 <span>必选</span></label>
          <select id="pub-template" className="field" value={createForm.templateId}
            onChange={(event) => setCreateForm((prev) => ({ ...prev, templateId: event.target.value }))}>
            <option value="">选择模板</option>
            {(templates.data?.rows ?? []).map((template) => (
              <option key={template.public_id} value={template.public_id}>
                {template.name}{template.current_version_id ? "" : "（暂无版本）"}
              </option>
            ))}
          </select>
          <label className="form-label" htmlFor="pub-rubric">报告评分表 <span>可选</span></label>
          <select id="pub-rubric" className="field" value={createForm.rubricId}
            onChange={(event) => setCreateForm((prev) => ({ ...prev, rubricId: event.target.value }))}>
            <option value="">选择评分表</option>
            {(rubrics.data?.rows ?? []).map((rubric) => (
              <option key={rubric.public_id} value={rubric.public_id}>
                {rubric.name}{rubric.current_version_id ? "" : "（暂无可用版本）"}
              </option>
            ))}
          </select>
          <label className="form-label" htmlFor="pub-chapter">所属课程章节</label>
          <select id="pub-chapter" className="field" value={createForm.chapterId} onChange={event => setCreateForm(prev => ({ ...prev, chapterId: event.target.value }))}><option value="">请选择课程章节</option>{courseChapters.data?.rows.map(chapter => <option key={chapter.public_id} value={chapter.public_id}>{chapter.title}</option>)}</select>
          {courseChapters.error ? <p role="alert">章节加载失败，请重新打开表单重试。</p> : courseChapters.isSuccess && !courseChapters.data.rows.length ? <p>请先创建课程章节。</p> : null}
          <label className="form-label" htmlFor="pub-title">发布标题 <span>必填</span></label>
          <input id="pub-title" className="field" value={createForm.title}
            onChange={(event) => setCreateForm((prev) => ({ ...prev, title: event.target.value }))}
            placeholder="例如 Python 容器实验" />
          <label className="form-label" htmlFor="pub-desc">说明</label>
          <textarea id="pub-desc" className="field" rows={2} value={createForm.description}
            onChange={(event) => setCreateForm((prev) => ({ ...prev, description: event.target.value }))} />
          <div style={{ display: "grid", gap: 10, gridTemplateColumns: "1fr 1fr" }}>
            <div>
              <label className="form-label" htmlFor="pub-start">开放时间 <span>必填</span></label>
              <input id="pub-start" className="field" type="datetime-local" value={createForm.window_start}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, window_start: event.target.value }))} />
            </div>
            <div>
              <label className="form-label" htmlFor="pub-end">截止时间 <span>必填</span></label>
              <input id="pub-end" className="field" type="datetime-local" value={createForm.window_end}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, window_end: event.target.value }))} />
            </div>
          </div>
          <div>
            <label className="form-label" htmlFor="pub-release">编程成绩公布时间（留空为截止后）</label>
            <input id="pub-release" className="field" type="datetime-local" value={createForm.score_release_at}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, score_release_at: event.target.value }))} />
          </div>
          <div>
            <label className="form-label" htmlFor="pub-assign">分配截止</label>
            <input id="pub-assign" className="field" type="datetime-local" value={createForm.assignment_deadline}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, assignment_deadline: event.target.value }))} />
          </div>
          <label className="form-label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={hasProgramming && createForm.report_required} disabled={!hasProgramming}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, report_required: event.target.checked }))} />
            需要提交实验报告
          </label>
          <p className="subtle" style={{ margin: 0 }}>创建后运行预检；需要实验报告时，先在发布草稿中上传报告模板，再发布给学生。</p>
        </div>
      </Modal>

      <ConfirmDialog open={withdrawTarget != null} onClose={() => setWithdrawTarget(null)}
        onConfirm={() => { if (withdrawTarget) withdraw.mutate(withdrawTarget); }}
        title="撤回实验？" eyebrow="实验发布" tone="danger" busy={withdraw.isPending}
        confirmLabel="确认撤回"
        description={<p>撤回后已分配任务的处理方式将按课程策略决定；撤回操作需要版本号匹配，若期间实验被他人修改会要求刷新。</p>}
      />
      <ConfirmDialog open={closeTarget != null} onClose={() => setCloseTarget(null)}
        onConfirm={() => { if (closeTarget) close.mutate(closeTarget); }}
        title="关闭实验？" eyebrow="实验发布" tone="danger" busy={close.isPending}
        confirmLabel="确认关闭"
        description={<p>关闭后不再接受新的提交；进行中的任务会按后端策略结束。</p>}
      />
    </>
  );
}


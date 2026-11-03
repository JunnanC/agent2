import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@edu/auth-client";
import { reportApi, taskApi, workspaceApi } from "@edu/api-client";
import type { ExecutionRun, ReportDraft, WorkbenchAggregate } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { readWorkspaceSession, sessionCapabilitiesStale, storeWorkspaceSession, type StoredWorkspaceSession } from "@/lib/workspace-session";
import { htmlToMarkdown, markdownToHtml } from "@/lib/report-format";
import {
  AsyncJobProgress, Button, EmptyState, Icon, LoadingState, Modal, RichTextEditor,
  Splitter, useToast,
} from "@edu/ui";

type SaveStatusState = { label: string; tone: "" | "good" | "warn" | "bad" };
type WorkspaceTab = "terminal" | "editor" | "preview";

const TESTS_MIN = 120;
const TESTS_MAX = 360;
const REPORT_MIN = 240;

/* 后端 WorkspaceExecutionRun.Status 契约(QUEUED/RUNNING/PASSED/FAILED/TIMEOUT/RESOURCE_EXCEEDED/REJECTED) */
const RUN_RUNNING_STATUSES = new Set(["QUEUED", "RUNNING"]);
const RUN_FAILED_STATUSES = new Set(["FAILED", "TIMEOUT", "RESOURCE_EXCEEDED", "REJECTED"]);

function runIsRunning(status?: string): boolean {
  return status != null && RUN_RUNNING_STATUSES.has(status);
}

function runIsFailed(status?: string): boolean {
  return status != null && RUN_FAILED_STATUSES.has(status);
}

export function Workbench() {
  const { taskId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();

  /* ── 本地状态(会话优先:工作区 REST 需要 X-Workspace-Token)── */
  const [storedSession, setStoredSession] = useState<StoredWorkspaceSession | null>(
    () => readWorkspaceSession(taskId),
  );
  const workspaceToken = storedSession?.token ?? "";

  /* ── 服务端数据 ── */
  const workbench = useQuery({ queryKey: keys.workbench(taskId), queryFn: () => workspaceApi.workbench(taskId) });
  const taskDetail = useQuery({ queryKey: keys.task(taskId), queryFn: () => taskApi.detail(taskId) });
  const checkpoints = useQuery({
    queryKey: [...keys.checkpoints(taskId), storedSession?.session_id ?? "none"],
    queryFn: () => workspaceApi.checkpoints(taskId, workspaceToken),
  });
  const executionRuns = useQuery({
    queryKey: [...keys.executionRuns(taskId), storedSession?.session_id ?? "none"],
    queryFn: () => workspaceApi.executionRuns(taskId, { page_size: 10 }, workspaceToken),
    enabled: Boolean(workspaceToken),
    refetchInterval: (query) => query.state.data?.rows.some((run) => runIsRunning(run.status)) ? 2000 : false,
  });
  const [chapterId, setChapterId] = useState<string | null>(null);
  const [view, setView] = useState<"brief" | "report">("brief");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("terminal");
  const [chapterMenuOpen, setChapterMenuOpen] = useState(false);
  const [draftHtml, setDraftHtml] = useState<string>("");
  const [draftBase, setDraftBase] = useState<ReportDraft | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatusState>({ label: "草稿", tone: "" });
  const [conflict, setConflict] = useState<string | null>(null);
  const [reportSize, setReportSize] = useState(320);
  const [testsSize, setTestsSize] = useState(155);
  const [exitOpen, setExitOpen] = useState(false);
  const [checkpointOpen, setCheckpointOpen] = useState(false);
  const [checkpointName, setCheckpointName] = useState("");
  const [submitOpen, setSubmitOpen] = useState(false);
  const [selfTestInput, setSelfTestInput] = useState("");
  const draftBaseRef = useRef<ReportDraft | null>(null);
  const saveQueue = useRef<Promise<boolean>>(Promise.resolve(true));
  const draftRef = useRef(draftHtml);
  draftRef.current = draftHtml;

  /* ── 报告草稿载入 ── */
  const draftQuery = useQuery({ queryKey: keys.reportDraft(taskId), queryFn: () => reportApi.draft(taskId), retry: false });
  useEffect(() => {
    if (draftQuery.data && draftBase == null) {
      setDraftBase(draftQuery.data);
      draftBaseRef.current = draftQuery.data;
      if (!draftRef.current) setDraftHtml(markdownToHtml(draftQuery.data.body_markdown ?? ""));
      setSaveStatus({ label: "已保存", tone: "good" });
    }
  }, [draftQuery.data, draftBase]);

  const reportTemplateHtml = "<h3>实验目标与任务</h3><p>请简述本阶段目标与任务要求。</p><h3>操作过程与关键结果</h3><p>请记录关键步骤、命令与输出。</p><h3>问题分析与修复方案</h3><p>请说明定位过程和修复方法。</p><h3>验证结果与总结</h3><p>请填写验证结果和本阶段结论。</p>";

  /* ── 自动保存（2s 防抖；412 冲突保留本地文本并提示合并）── */
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    if (!draftRef.current) return;
    setSaveStatus({ label: "保存中", tone: "warn" });
    saveTimer.current = setTimeout(() => {
      void saveDraftNow();
    }, 2000);
    return () => { if (saveTimer.current) clearTimeout(saveTimer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftHtml]);

  const saveDraftNow = useCallback(async (silent = false) => {
    if (!draftRef.current) return false;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    const html = draftRef.current;
    const save = saveQueue.current.then(async () => {
      // A genuine server conflict blocks queued writes until the user resolves it.
      if (draftBaseRef.current == null) return false;
      try {
      const result = await reportApi.saveDraft(
        taskId,
        { body_markdown: htmlToMarkdown(html) },
        draftBaseRef.current.row_version,
      );
      draftBaseRef.current = result.data;
      setDraftBase(result.data);
      setConflict(null);
      if (html === draftRef.current) setSaveStatus({ label: "已保存", tone: "good" });
      void queryClient.invalidateQueries({ queryKey: keys.reportDraft(taskId) });
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.kind === "conflict") {
        draftBaseRef.current = null;
        setConflict("报告在服务器上已被更新，你的本地内容已保留。请确认以哪个版本为准。");
        setSaveStatus({ label: "存在冲突", tone: "bad" });
      } else if (error instanceof ApiError) {
        setSaveStatus({ label: "保存失败", tone: "bad" });
        if (!silent) toast.notify(error.payload?.message ?? "保存失败，稍后自动重试", "error");
      }
      }
      return false;
    });
    saveQueue.current = save;
    return save;
  }, [taskId, toast, queryClient]);

  const createCheckpoint = useMutation({
    mutationFn: async () => {
      await workspaceApi.captureSnapshot(taskId, workspaceToken);
      return workspaceApi.createCheckpoint(taskId, { label: checkpointName.trim() || "阶段检查点" }, workspaceToken);
    },
    onSuccess: (checkpoint) => {
      toast.notify(`检查点已保存：${checkpoint.name ?? checkpoint.label ?? checkpoint.public_id}`);
      setCheckpointOpen(false);
      setCheckpointName("");
      void checkpoints.refetch();
      void workbench.refetch();
    },
    onError: (error) => toast.notify(serializeError(error), "error"),
  });

  const restoreCheckpoint = useMutation({
    /* If-Match 锁的是会话 row_version，恢复会推进会话版本；先取最新列表再恢复，避免 428/412 */
    mutationFn: async (checkpointId: string) => {
      const list = await workspaceApi.checkpoints(taskId, workspaceToken);
      return workspaceApi.restoreCheckpoint(taskId, checkpointId, list.sessionRowVersion, workspaceToken);
    },
    onSuccess: () => {
      toast.notify("检查点已恢复");
      void checkpoints.refetch();
      void workbench.refetch();
    },
    onError: (error) => toast.notify(serializeError(error), "error"),
  });

  const connectWorkspace = useMutation({
    // enter 同时覆盖 READY→IN_PROGRESS 与会话重建(轮换新 token),比 createSession 适用于更多状态
    mutationFn: () => taskApi.enter(taskId, taskDetail.data?.row_version ?? workbench.data?.task?.row_version ?? ""),
    onSuccess: (data) => {
      const session = data.session;
      if (!session?.workspace_token) return;
      const payload: StoredWorkspaceSession = {
        session_id: session.public_id,
        token: session.workspace_token,
        expires_at: session.expires_at ?? null,
        status: session.status,
        workspace_urls: session.workspace_urls,
        capabilities: session.capabilities,
      };
      storeWorkspaceSession(taskId, payload);
      setStoredSession(payload);
      void queryClient.invalidateQueries({ queryKey: keys.task(taskId) });
      void queryClient.invalidateQueries({ queryKey: keys.checkpoints(taskId) });
      void queryClient.invalidateQueries({ queryKey: keys.executionRuns(taskId) });
    },
    onError: (error) => toast.notify(serializeError(error), "error"),
  });

  const aggregateTaskStatus = taskDetail.data?.status ?? workbench.data?.task?.status;
  const aggregateAllowed = taskDetail.data?.allowed_actions ?? workbench.data?.task?.allowed_actions ?? [];
  /* 会话快照过期判定:
     - 老载荷缺 capabilities 键(重建会话)
     - 与聚合里模板锁定的能力声明不一致(教师补充 terminal 等情形,重入轮换刷新)
     - expires_at 已过(重新进入会轮换新 token) */
  const storedSessionStale = storedSession != null
    && (sessionCapabilitiesStale(
          storedSession.capabilities,
          (workbench.data as WorkbenchAggregate | undefined)?.template_caps,
        )
      || (storedSession.expires_at != null
        && new Date(storedSession.expires_at).getTime() <= Date.now()));
  useEffect(() => {
    // 直达工作台(如从任务列表进入)但本标签页没有(或会话快照过期/能力缺失)时:
    // 任务处于可运行状态 → 自动重新进入,轮换新 token 并刷新能力
    if (
      (storedSession == null || storedSessionStale)
      && !connectWorkspace.isPending
      && ["READY", "IN_PROGRESS", "REPORT_DRAFT"].includes(String(aggregateTaskStatus ?? ""))
      && aggregateAllowed.includes("enter")
    ) {
      connectWorkspace.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aggregateTaskStatus, storedSession, aggregateAllowed]);

  const runTests = useMutation({
    mutationFn: async (testKeys?: string[]) => {
      const snapshot = await workspaceApi.captureSnapshot(taskId, workspaceToken);
      return workspaceApi.createExecutionRun(taskId, { snapshot_id: snapshot.result_snapshot_id!, test_keys: testKeys }, workspaceToken);
    },
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: keys.executionRuns(taskId) });
      void workbench.refetch();
      currentRunId.current = run.public_id;
    },
    onError: (error) => toast.notify(serializeError(error), "error"),
  });

  const selfTest = useMutation({
    mutationFn: async () => {
      const snapshot = await workspaceApi.captureSnapshot(taskId, workspaceToken);
      return workspaceApi.operation(
        storedSession?.session_id ?? "",
        "SELF_TEST",
        { input: selfTestInput, snapshot_id: snapshot.result_snapshot_id },
        workspaceToken,
      );
    },
    onSuccess: (event) => {
      currentRunId.current = event.execution_run_id ?? null;
      void queryClient.invalidateQueries({ queryKey: keys.executionRuns(taskId) });
      void workbench.refetch();
    },
    onError: (error) => toast.notify(serializeError(error), "error"),
  });

  const switchLanguage = useMutation({
    mutationFn: async (language: string) => {
      await workspaceApi.captureSnapshot(taskId, workspaceToken);
      const latest = await workspaceApi.checkpoints(taskId, workspaceToken);
      return workspaceApi.storageJob(taskId, { kind: "SWITCH", language }, latest.sessionRowVersion ?? 0, workspaceToken);
    },
    onSuccess: () => {
      toast.notify("语言工作区已切换");
      void queryClient.invalidateQueries({ queryKey: keys.workbench(taskId) });
      void queryClient.invalidateQueries({ queryKey: keys.checkpoints(taskId) });
      void queryClient.invalidateQueries({ queryKey: keys.executionRuns(taskId) });
    },
    onError: (error) => toast.notify(serializeError(error), "error"),
  });

  const currentRunId = useRef<string | null>(null);
  const lastRun: ExecutionRun | undefined = useMemo(() => {
    const rows = executionRuns.data?.rows ?? [];
    return currentRunId.current
      ? rows.find((row) => row.public_id === currentRunId.current) ?? rows[0]
      : rows[0];
  }, [executionRuns.data]);

  const submitReport = useMutation({
    /* If-Match 锁的是任务 row_version；保存草稿会推进任务状态，缓存里的版本会过期，提交前现取最新 */
    mutationFn: async () => {
      if (!await saveDraftNow()) throw new Error("请先保存报告并解决保存冲突");
      const latest = await taskApi.detail(taskId);
      return reportApi.submitReport(taskId, undefined, latest.row_version);
    },
    onSuccess: () => {
      toast.notify("报告已提交，等待教师评审");
      setSubmitOpen(false);
      void taskDetail.refetch();
      void workbench.refetch();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.kind === "conflict") {
        void taskDetail.refetch();
        void workbench.refetch();
      }
      toast.notify(serializeError(error), "error");
    },
  });

  const leaveWorkbench = (mode: "keep" | "release") => {
    const backend = async () => {
      if (mode === "release" && storedSession) {
        await workspaceApi.revokeSession(storedSession.session_id, storedSession.token);
        sessionStorage.removeItem(`edu.workspace.${taskId}`);
      }
      if (mode === "keep") await saveDraftNow(true);
    };
    void backend()
      .then(() => navigate(`/experiments/${taskId}`))
      .catch((error: unknown) => toast.notify(serializeError(error), "error"));
  };

  if (workbench.isLoading && taskDetail.isLoading) {
    return <div className="workbench-shell"><LoadingState label="正在装载工作台" /></div>;
  }
  if (workbench.error) {
    const error = workbench.error;
    return (
      <div className="workbench-shell">
        <div className="app-shell" style={{ padding: 24 }}>
          <EmptyState
            title="无法进入工作台"
            hint={error instanceof ApiError
              ? `${error.payload?.message ?? error.message}${error.kind === "conflict" ? "，请稍后重试。" : ""}`
              : "请稍后重试。"}
            action={<Link className="btn" to={`/experiments/${taskId}`}>返回任务详情</Link>}
          />
        </div>
      </div>
    );
  }

  const aggregate = workbench.data as WorkbenchAggregate | undefined;
  const task = (taskDetail.data ?? aggregate?.task);
  const sessionActive = storedSession != null;
  /* 真实终端:会话有用的 terminal capability 时才嵌入 workspace-gateway 终端页 */
  const terminalOnline = storedSession?.capabilities?.["terminal"] === true;
  const terminalBase = storedSession?.workspace_urls?.["terminal"]
    ?? `/workspace/${storedSession?.session_id ?? ""}/terminal/`;
  /* ttyd 前端按 URL 查询参数合并 xterm 选项(cursorBlink 优先级最高) */
  const terminalUrl = terminalBase.includes("?")
    ? `${terminalBase}&cursorBlink=true`
    : `${terminalBase}?cursorBlink=true`;
  const chapters = aggregate?.chapters ?? [];
  const activeChapter = chapters.find((chapter) => chapter.public_id === chapterId) ?? chapters[0];
  const tests = aggregate?.tests ?? [];
  const testsAvailable = aggregate?.tests_available ?? tests.length > 0;
  const blockers = task?.blockers ?? [];
  const allowed = task?.allowed_actions ?? [];
  const workspace = aggregate?.workspace;
  const languagePolicy = workspace?.language_policy;
  const allowedLanguages = languagePolicy?.allowed_languages ?? [];
  const languageSelectable = languagePolicy?.mode === "STUDENT_SELECT" && allowedLanguages.length > 0;
  const currentLanguage = workspace?.language ?? languagePolicy?.language ?? "python";

  /* 判题资源可能不公开分项用例，由服务端声明是否需要测试。 */
  const submitChecks = [
    { label: "实验报告已保存", ok: saveStatus.tone === "good", failReason: "请等待报告草稿保存完成" },
    ...(testsAvailable
      ? [{ label: "本阶段测试已通过", ok: lastRun?.status === "PASSED", failReason: "请先运行并通过本阶段测试" }]
      : []),
    ...blockers.map((blocker) => ({ label: blocker.reason ?? "服务端阻塞", ok: false, failReason: blocker.reason ?? "存在未解除的阻塞" })),
  ];

  const canSubmit = submitChecks.every((check) => check.ok);

  return (
    <div className="workbench-shell">
      {/* ── 工作台顶部 ── */}
      <header className="topbar compact workbench-topbar">
        <div className="brand-lockup">
          <Link to={`/experiments/${taskId}`} className="brand-mark" aria-label="返回任务详情" style={{ textDecoration: "none" }}>
            <Icon name="layers" size={16} />
          </Link>
          <span className="brand-name">实验工作台</span>
          <span className="context-dot" />
          <span className="context-label">{sessionActive ? "工作区已连接" : "工作区未连接"}</span>
        </div>
        <div className="topbar-actions workbench-top-actions">
          <span className={`status ${sessionActive ? "good" : "warn"}`}>
            {sessionActive ? "自动保存已开启" : "等待工作区就绪"}
          </span>
        </div>
      </header>

      <div className="workbench-main workbench-layout">
        {/* ── 左栏：章节与说明/报告 ── */}
        <aside className="workbench-panel workbench-left">
          <div className="workbench-panel-header">
            <div className="task-heading-row">
              <button type="button" className="chapter-menu-toggle" aria-label="实验章节菜单"
                aria-expanded={chapterMenuOpen} onClick={() => setChapterMenuOpen((open) => !open)}>
                <Icon name="menu" />
              </button>
              <div style={{ minWidth: 0 }}>
                <span className="eyebrow">实验任务</span>
                <h1>{task?.title ?? "实验进行中"}</h1>
              </div>
            </div>
            {chapterMenuOpen ? (
              <div className="chapter-menu">
                <div className="chapter-menu-heading">
                  <strong>选择章节任务</strong>
                  <button type="button" aria-label="关闭章节菜单" className="icon-btn sm" onClick={() => setChapterMenuOpen(false)}>
                    <Icon name="x" size={13} />
                  </button>
                </div>
                <nav aria-label="实验章节">
                  {chapters.map((chapter, index) => {
                    const isActive = chapter.public_id === activeChapter?.public_id;
                    const isDone = chapter.status === "COMPLETED";
                    return (
                      <button type="button" key={chapter.public_id}
                        className={`chapter-option${isActive ? " is-current" : ""}${isDone ? " is-complete" : ""}`}
                        aria-current={isActive ? "step" : undefined}
                        onClick={() => { setChapterId(chapter.public_id); setChapterMenuOpen(false); }}>
                        <span className="chapter-state">{isDone ? <Icon name="check" size={11} /> : index + 1}</span>
                        <span><strong>{chapter.title}</strong><small>{isDone ? "已完成" : "进行中"}</small></span>
                      </button>
                    );
                  })}
                </nav>
              </div>
            ) : null}
          </div>

          <div className="workbench-left-content">
            <div className="workbench-switcher" role="tablist" aria-label="任务内容">
              <button type="button" role="tab" aria-selected={view === "brief"} className={view === "brief" ? "active" : ""}
                data-view="brief" onClick={() => setView("brief")}>实验说明</button>
              <button type="button" role="tab" aria-selected={view === "report"} className={view === "report" ? "active" : ""}
                data-view="report" onClick={() => setView("report")}>实验报告</button>
            </div>

            <section className="task-detail-panel" role="tabpanel" aria-label="实验说明" hidden={view !== "brief"}>
              <div className="detail-kicker">{activeChapter ? `章节 ${activeChapter.sort_order + 1}` : "当前章节"}</div>
              <h2>{activeChapter?.title ?? "实验说明"}</h2>
              <p>{activeChapter?.description ?? aggregate?.current_chapter?.instructions?.join("\n") ?? "按教师发布的说明完成本章节任务。"}</p>
              {sessionActive ? (
                <div className="task-completion-note">
                  <span>完成本阶段后，请在「实验报告」中填写并提交对应报告。</span>
                </div>
              ) : null}
            </section>

            <div className="report-editor-panel" role="tabpanel" aria-label="实验报告编辑器" hidden={view !== "report"}>
              <RichTextEditor
                ariaLabel="实验报告编辑器"
                initialHtml={draftHtml || reportTemplateHtml}
                placeholder="按报告模板填写本阶段内容"
                onChange={(html) => { setDraftHtml(html); setSaveStatus({ label: "未保存", tone: "warn" }); }}
                saveStatus={
                  <span className={`report-toolbar-status ${saveStatus.tone}`} aria-live="polite">
                    {saveStatus.label}
                  </span>
                }
                toolbarExtra={
                  <>
                    <Button size="sm" onClick={() => { void saveDraftNow(); }} disabled={saveStatus.tone === ""}>保存报告</Button>
                  </>
                }
              />
              {conflict ? (
                <div className="join-course-note" style={{ marginTop: 8 }}>
                  <span style={{ color: "var(--amber)" }}>!</span>
                  <span>{conflict}</span>
                  <Button size="sm" style={{ marginLeft: "auto" }}
                    onClick={async () => {
                      try {
                        draftBaseRef.current = await reportApi.draft(taskId);
                        await saveDraftNow();
                      } catch (error) { toast.notify(serializeError(error), "error"); }
                    }}>
                    以我的版本覆盖
                  </Button>
                </div>
              ) : null}
            </div>
          </div>
        </aside>

        {/* 分隔条（可拖拽 + 键盘调整） */}
        <Splitter
          orientation="vertical" ariaLabel="调整说明与工作区宽度"
          minSize={REPORT_MIN} maxSize={560} currentSize={reportSize}
          onChange={(next) => setReportSize(Math.max(REPORT_MIN, Math.min(560, next)))}
        />

        {/* ── 中栏：工作区 + 测试 ── */}
        <section className="workbench-panel workbench-center">
          <div className="workspace-tabs">
            <div className="workspace-tab-list" role="tablist" aria-label="工作区工具">
              {([["terminal", "终端"], ["editor", "文件编辑"], ["preview", "结果预览"]] as Array<[WorkspaceTab, string]>).map(([tab, label]) => (
                <button type="button" key={tab} role="tab" aria-selected={workspaceTab === tab}
                  className={workspaceTab === tab ? "active" : ""} data-worktab={tab}
                  onClick={() => setWorkspaceTab(tab)}>{label}</button>
              ))}
            </div>
            <div className="workspace-language-control">
              <label htmlFor="workspace-language">编程语言</label>
              {languageSelectable ? (
                <select id="workspace-language" value={currentLanguage}
                  disabled={!sessionActive || switchLanguage.isPending || Boolean(workspace?.active_storage_job)}
                  onChange={(event) => {
                    const next = event.target.value;
                    if (next !== currentLanguage) switchLanguage.mutate(next);
                  }}>
                  {allowedLanguages.map((language) => <option key={language} value={language}>{languageLabel(language)}</option>)}
                </select>
              ) : (
                <span aria-label="当前编程语言">{languageLabel(currentLanguage)}{workspace?.toolchain_version ? ` · ${workspace.toolchain_version}` : ""}</span>
              )}
              {switchLanguage.isPending ? <small aria-live="polite">切换中…</small> : null}
            </div>
            <Button size="sm" className="workspace-exit" onClick={() => setExitOpen(true)}>
              <Icon name="log-out" size={13} /> 退出实验
            </Button>
          </div>

          <div className="workspace-content" style={{ ["--tests-pane-size" as never]: `${testsSize}px` }}>
            <div className="workspace-card" role="tabpanel" aria-label="工作区面板">
              {workspaceTab === "terminal" ? (
                terminalOnline ? (
                  <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                    <div className="terminal-head"><span>终端</span><small>真实工作区终端</small></div>
                    <iframe
                      key={storedSession?.session_id}
                      src={terminalUrl}
                      title="实验工作区终端"
                      aria-label="终端输出"
                      referrerPolicy="same-origin"
                      style={{ flex: 1, minHeight: 0, width: "100%", border: "none", background: "#10171f" }}
                    />
                  </div>
                ) : (
                  <div className="preview-empty">
                    <strong>{sessionActive ? "当前模板未启用终端" : "工作区尚未连接"}</strong>
                    <span>
                      {sessionActive
                        ? "该实验的 workspace_capabilities 未声明 terminal,请改用文件编辑或让教师更新模板。"
                        : "正在自动进入工作区;终端就绪后会显示在这里。"}
                    </span>
                    {sessionActive ? null : <Link className="btn" to={`/experiments/${taskId}`}>返回任务详情</Link>}
                  </div>
                )
              ) : null}
              {workspaceTab === "editor" ? (
                storedSession?.capabilities?.["webide"] === true ? (
                  <iframe title="实验文件编辑器"
                    src={storedSession.workspace_urls?.["webide"] ?? `/workspace/${storedSession.session_id}/webide/`}
                    style={{ flex: 1, width: "100%", minHeight: 0, border: 0 }} />
                ) : <EmptyState title="文件编辑器尚未就绪" hint="工作区连接后，启用了 Web IDE 的实验可在这里编辑和保存文件。" />
              ) : null}
              {workspaceTab === "preview" ? (
                lastRun && (lastRun.status === "PASSED" || runIsRunning(lastRun.status) || runIsFailed(lastRun.status)) ? (
                  <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                    <div className="terminal-head"><span>结果预览</span><span>{lastRun.status === "PASSED" ? "最近一次通过" : lastRun.status}</span></div>
                    <div style={{ padding: 10, overflow: "auto" }}>
                      {(lastRun.test_cases ?? []).map((testCase, index) => (
                        <div className={`test-case${testCase.status === "PASSED" ? " is-passed" : " is-failed"}`} key={index}>
                          <span><strong>{testCase.name}</strong><small>{testCase.message}</small></span>
                          <span className="test-case-result">{testCase.status}</span>
                        </div>
                      ))}
                      {!lastRun.test_cases?.length ? <p className="subtle">{lastRun.result_summary ?? "暂无输出"}</p> : null}
                    </div>
                  </div>
                ) : (
                  <div className="preview-empty">
                    <strong>还没有测试结果</strong>
                    <span>完成本阶段任务后，运行测试用例查看结果。</span>
                  </div>
                )
              ) : null}
            </div>

            <Splitter
              orientation="horizontal" ariaLabel="调整工作区与测试区高度"
              minSize={TESTS_MIN} maxSize={TESTS_MAX} currentSize={testsSize}
              onChange={(next) => setTestsSize(Math.max(TESTS_MIN, Math.min(TESTS_MAX, next)))}
            />

            <section className="test-panel" aria-label="测试用例">
              <div className="test-panel-heading">
                <h2>测试用例</h2>
                <span className="test-summary">{tests.length ? `本阶段共 ${tests.length} 项` : testsAvailable ? "分项用例未公开" : "暂无测试"} · {lastRun?.status === "PASSED" ? "全部通过" : runIsRunning(lastRun?.status) ? "运行中" : runIsFailed(lastRun?.status) ? `测试失败${lastRun?.error_code ? ` · ${lastRun.error_code}` : ""}` : "尚未运行"}</span>
                <span className={`test-status ${lastRun?.status === "PASSED" ? "passed" : runIsRunning(lastRun?.status) ? "running" : runIsFailed(lastRun?.status) ? "failed" : ""}`}>
                  {lastRun?.status === "PASSED" ? "通过" : runIsRunning(lastRun?.status) ? "运行中" : runIsFailed(lastRun?.status) ? "失败" : "待运行"}
                </span>
              </div>
              <div className="test-case-list">
                {tests.length ? tests.map((testCase, index) => (
                  <div className="test-case" key={String(testCase.key ?? index)}>
                    <span className="test-case-icon"><Icon name={lastRun?.status === "PASSED" ? "circle-check" : "circle-dashed"} /></span>
                    <span><strong>{testCase.name}</strong><small>{testCase.description}</small></span>
                    <span className="test-case-result">{lastRun?.status === "PASSED" ? "通过" : runIsRunning(lastRun?.status) ? "运行中" : runIsFailed(lastRun?.status) ? "未返回分项结果" : "待测试"}</span>
                  </div>
                )) : (
                  <div className="state-block" style={{ padding: 14 }}><strong>{testsAvailable ? "运行测试以检查本阶段代码，分项用例未公开" : "本阶段暂无测试用例"}</strong></div>
                )}
              </div>
              <div className="test-panel-actions">
                {workbench.data?.task?.allowed_operations?.includes("SELF_TEST") ? (
                  <div className="self-test-box">
                    <label htmlFor="self-test-input">自测输入</label>
                    <textarea id="self-test-input" value={selfTestInput}
                      onChange={(event) => setSelfTestInput(event.target.value)}
                      placeholder="输入本次自测数据，可换行" rows={3} maxLength={65536} />
                    <Button size="sm" disabled={!sessionActive || !selfTestInput.trim() || selfTest.isPending || runIsRunning(lastRun?.status)}
                      onClick={() => selfTest.mutate()}>
                      <Icon name="play" size={13} /> {selfTest.isPending ? "自测中…" : "自测运行"}
                    </Button>
                  </div>
                ) : null}
                <Button size="sm" onClick={() => setCheckpointOpen(true)}>
                  <Icon name="bookmark-plus" size={13} /> 保存检查点
                </Button>
                <div>
                  <Button size="sm" disabled={!sessionActive || runTests.isPending || runIsRunning(lastRun?.status) || createCheckpoint.isPending || restoreCheckpoint.isPending || !testsAvailable}
                    onClick={() => runTests.mutate(undefined)}>
                    <Icon name="play" size={13} />
                    {sessionActive
                      ? (runTests.isPending ? "运行中…" : "运行测试")
                      : "等待工作区就绪"}
                  </Button>
                  <Button size="sm" variant="primary" onClick={() => setSubmitOpen(true)}
                    disabled={blockers.length > 0 && !allowed.includes("submit_report")}>
                    <Icon name="send" size={13} /> 提交报告
                  </Button>
                  {blockers.length > 0 && !allowed.includes("submit_report")
                    ? <small style={{ display: "block", marginTop: 4 }}>{blockers.map((b) => b.reason ?? b.detail ?? "").join("；")}</small>
                    : null}
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>

      {/* ── 退出实验确认：按 blockers 动态说明保留项 ── */}
      <Modal open={exitOpen} onClose={() => setExitOpen(false)} eyebrow="退出实验"
        title="要如何退出当前实验？"
        wide
        actions={(
          <>
            <Button onClick={() => { setExitOpen(false); }}>继续实验</Button>
            <Button variant="primary" onClick={() => { setExitOpen(false); leaveWorkbench("keep"); }}>保留实例并退出</Button>
          </>
        )}>
        <p className="subtle">退出后仍可从任务详情重新进入。当前状态的保留说明以服务端为准。</p>
        <div className="status-line is-ok">
          ✓ 工作区记录与报告草稿会保留；checkpoint 列表中的记录可随时恢复。
        </div>
        {sessionActive ? (
          <div className="status-line is-blocked" style={{ marginTop: 6 }}>
            说明：若选择释放实例，下次进入需要重新装载工作区（装载耗时视资源情况而定）。
          </div>
        ) : null}
        {blockers.length ? (
          <div className="status-line is-blocked" style={{ marginTop: 6 }}>
            <strong>服务端阻塞：</strong>
            {blockers.map((blocker, index) => <p key={index} style={{ margin: 0 }}>{blocker.reason ?? blocker.detail ?? blocker.code}</p>)}
          </div>
        ) : null}
      </Modal>

      {/* ── checkpoint ── */}
      <Modal open={checkpointOpen} onClose={() => setCheckpointOpen(false)} eyebrow="工作区记录"
        title="保存检查点"
        wide
        actions={(
          <>
            <Button onClick={() => setCheckpointOpen(false)}>关闭</Button>
            <Button variant="primary" disabled={createCheckpoint.isPending || runTests.isPending || runIsRunning(lastRun?.status) || restoreCheckpoint.isPending || !sessionActive} onClick={() => createCheckpoint.mutate()}>
              {createCheckpoint.isPending ? "保存中…" : "保存检查点"}
            </Button>
          </>
        )}>
        <label className="form-label" htmlFor="checkpoint-name">检查点名称</label>
        <input id="checkpoint-name" className="field" value={checkpointName}
          onChange={(event) => setCheckpointName(event.target.value)}
          placeholder={`${activeChapter?.title ?? "当前阶段"}检查点`} />
        <div style={{ marginTop: 12 }}>
          <strong>已保存检查点</strong>
          {restoreCheckpoint.isPending ? <small style={{ marginLeft: 8 }}>恢复中…</small> : null}
          <div style={{ marginTop: 8 }}>
            {checkpoints.data?.rows.length ? (
              checkpoints.data.rows.map((checkpoint) => (
                <div className="status-line" key={checkpoint.public_id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ flex: 1 }}>
                    {checkpoint.name ?? checkpoint.label ?? checkpoint.public_id}
                    <small style={{ display: "block" }}>{checkpoint.created_at ?? checkpoint.saved_at}</small>
                  </span>
                  <Button size="sm" disabled={restoreCheckpoint.isPending || createCheckpoint.isPending || runTests.isPending || runIsRunning(lastRun?.status) || !sessionActive}
                    onClick={() => restoreCheckpoint.mutate(checkpoint.public_id)}>
                    恢复
                  </Button>
                </div>
              ))
            ) : (
              <p className="subtle">还没有检查点。运行测试或离开工作台前保存一个，可随时恢复。</p>
            )}
          </div>
        </div>
      </Modal>

      {/* ── 提交确认：逐项校验并显示阻塞原因 ── */}
      <Modal open={submitOpen} onClose={() => setSubmitOpen(false)} eyebrow="阶段提交"
        title="提交实验报告？"
        wide
        actions={(
          <>
            <Button onClick={() => setSubmitOpen(false)}>返回修改</Button>
            <Button variant="primary" disabled={!canSubmit || submitReport.isPending}
              onClick={() => submitReport.mutate()}>
              {submitReport.isPending ? "提交中…" : canSubmit ? "确认提交" : "请先完成检查"}
            </Button>
          </>
        )}>
        <p className="subtle">提交后当前阶段进入教师评审。提交前请确认以下内容。</p>
        {submitChecks.map((check) => (
          <div key={check.label} className={`status-line ${check.ok ? "is-ok" : "is-blocked"}`}>
            {check.ok ? "✓" : "!"}　{check.ok ? check.label : check.failReason}
          </div>
        ))}
        {saveStatus.tone === "bad" || saveStatus.tone === "warn" ? (
          <AsyncJobProgress status="processing" stages={[{ key: "draft", label: "报告草稿保存", state: "running" }]} />
        ) : null}
      </Modal>
    </div>
  );
}

function serializeError(error: unknown): string {
  if (error instanceof ApiError) return error.payload?.message ?? "操作失败，请稍后重试";
  if (error instanceof Error) return error.message;
  return "操作失败，请稍后重试";
}

function languageLabel(language: string): string {
  return ({ c: "C", cpp: "C++", java: "Java", python: "Python", go: "Go" } as Record<string, string>)[language] ?? language;
}

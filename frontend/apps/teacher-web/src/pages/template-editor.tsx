import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { teachingApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  AsyncJobProgress, Button, EmptyState, Breadcrumbs, Panel, RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import type { JobStage } from "@edu/ui";
import { apiErrorMessage } from "@/lib/format";

const STEPS = ["基础信息", "内容结构", "运行环境", "报告与评审", "预检与发布"] as const;

function templateMediaType(fileName: string): string {
  const name = fileName.toLowerCase();
  if (name.endsWith(".tar.gz")) return "application/gzip";
  const extension = name.slice(name.lastIndexOf("."));
  return ({
    ".pdf": "application/pdf", ".md": "text/markdown", ".txt": "text/plain",
    ".zip": "application/zip", ".tar": "application/x-tar", ".gz": "application/gzip",
    ".tgz": "application/gzip", ".csv": "text/csv", ".json": "application/json",
  } as Record<string, string>)[extension] ?? "application/octet-stream";
}

async function fileDigest(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function TemplateEditor() {
  const { courseId = "", templateId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [step, setStep] = useState<(typeof STEPS)[number]>("基础信息");
  const [chapterTitle, setChapterTitle] = useState("");
  const [chapterDescription, setChapterDescription] = useState("");
  const [taskChapterId, setTaskChapterId] = useState<string>("");
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null);
  const [selectedAdapterId, setSelectedAdapterId] = useState<string>("");
  const [selectedImageId, setSelectedImageId] = useState<string>("");
  const [selectedProfileId, setSelectedProfileId] = useState<string>("");
  const [testsJson, setTestsJson] = useState('{"cases":[{"input":"hello\\n","expected":"HELLO"}]}');
  const [specEntrypoint, setSpecEntrypoint] = useState("main.py");
  const [specLanguage, setSpecLanguage] = useState("");
  const [specToolchainVersion, setSpecToolchainVersion] = useState("");
  const [specLanguageStandard, setSpecLanguageStandard] = useState("");
  const [specComparator, setSpecComparator] = useState("token");
  const [specAbsoluteTolerance, setSpecAbsoluteTolerance] = useState("0.000001");
  const [specRelativeTolerance, setSpecRelativeTolerance] = useState("0.000001");
  const [assetPurpose, setAssetPurpose] = useState("STARTER");
  const [selectedMaterials, setSelectedMaterials] = useState<Record<string, string>>({});
  const [specTimeout, setSpecTimeout] = useState("10");
  const [specMemory, setSpecMemory] = useState("256");
  const [specCpu, setSpecCpu] = useState("500");

  const versions = useQuery({
    queryKey: keys.templateVersions(courseId, templateId),
    queryFn: () => teachingApi.templateVersions(courseId, templateId),
    refetchInterval: (query) => query.state.data?.rows.some((version) => version.status === "PRECHECKING") ? 2000 : false,
  });
  const refetchVersions = versions.refetch;

  const currentVersion = versions.data?.rows
    .find((version) => version.public_id === selectedVersion || version.status === "DRAFT")
    ?? versions.data?.rows?.[0];

  const versionId = currentVersion?.public_id ?? "";
  const chapters = useQuery({
    queryKey: keys.templateChapters(versionId),
    queryFn: () => teachingApi.templateChapters(courseId, versionId),
    enabled: Boolean(versionId),
  });
  const options = useQuery({
    queryKey: keys.templateOptions(courseId),
    queryFn: () => teachingApi.templateOptions(courseId),
  });
  const templateAssets = useQuery({
    queryKey: ["template-assets", courseId, templateId, versionId],
    queryFn: () => teachingApi.templateAssets(courseId, templateId, versionId),
    enabled: Boolean(versionId),
    refetchInterval: (query) => query.state.data?.rows.some((asset) => asset["scan_status"] === "PENDING") ? 2000 : false,
  });
  const assetScanState = (templateAssets.data?.rows ?? [])
    .map((asset) => `${String(asset["public_id"])}:${String(asset["scan_status"])}`)
    .join(",");
  const governanceImages = options.data?.["images"] ?? [];
  const adapters = options.data?.["runtime_adapters"] ?? [];
  const profiles = options.data?.["resource_profiles"] ?? [];
  const toolchains = options.data?.toolchains ?? [];
  const selectedToolchain = toolchains.find((item) => item.language === specLanguage);
  const studentLanguages = toolchains.filter((item) => item.available).map((item) => item.language);
  const selectedMaterialNotReady = (templateAssets.data?.rows ?? []).some((asset) =>
    Boolean(selectedMaterials[String(asset["public_id"])]) && asset["scan_status"] !== "CLEAN",
  );

  useEffect(() => {
    const spec = (currentVersion as unknown as { execution_spec?: { materials?: Array<{ asset_id: string; role: string }> } })?.execution_spec;
    if (Array.isArray(spec?.materials)) {
      setSelectedMaterials(Object.fromEntries(spec.materials.map((item) => [item.asset_id, item.role])));
    }
  }, [versionId, currentVersion]);

  useEffect(() => {
    if (assetScanState && !assetScanState.includes(":PENDING")) void refetchVersions();
  }, [assetScanState, refetchVersions]);

  const addChapter = useMutation({
    mutationFn: () => teachingApi.createTemplateChapter(
      courseId, versionId,
      { title: chapterTitle.trim(), description: chapterDescription.trim() || undefined },
      currentVersion?.row_version ?? "",
    ),
    onError: (error) => toast.notify(`章节写入失败：${apiErrorMessage(error)}`, "error"),
    onSuccess: () => {
      toast.notify("章节已保存");
      setChapterTitle("");
      setChapterDescription("");
      void chapters.refetch();
      void versions.refetch(); // refresh row_version / ETag for the next save
    },
  });

  const addTask = useMutation({
    mutationFn: () => teachingApi.createTemplateTask(
      courseId,
      taskChapterId,
      { title: taskTitle.trim(), description: taskDescription.trim() || undefined },
      currentVersion?.row_version ?? "",
    ),
    onError: (error) => toast.notify(`任务写入失败：${apiErrorMessage(error)}`, "error"),
    onSuccess: () => {
      toast.notify("章节任务已保存");
      setTaskTitle("");
      setTaskDescription("");
      void chapters.refetch();
      void versions.refetch();
    },
  });

  const saveEnvironment = useMutation({
    mutationFn: () => teachingApi.updateTemplateVersion(
      courseId,
      versionId,
      {
        image_id: selectedImageId,
        resource_profile_id: selectedProfileId,
      },
      currentVersion?.row_version ?? "",
    ),
    onError: (error) => toast.notify(`运行环境保存失败：${apiErrorMessage(error)}`, "error"),
    onSuccess: () => {
      toast.notify("运行环境已保存到当前草稿版本");
      void versions.refetch();
    },
  });

  const initializeVersion = useMutation({
    mutationFn: () => teachingApi.createTemplateVersion(courseId, templateId, {
      runtime_type: "CONTAINER",
      runtime_adapter_id: selectedAdapterId,
      image_id: selectedImageId,
      resource_profile_id: selectedProfileId,
      retention_days: 30,
      workspace_capabilities: {
        require_gateway: true,
        webide: true,
        snapshot: true,
        checkpoint: true,
      },
      report_policy: { required: true },
      review_policy: { mode: "MANUAL_WITH_AUTO_CHECK" },
    }),
    onSuccess: (created) => {
      toast.notify("草稿版本已创建，可继续维护章节与任务");
      setSelectedVersion(created.public_id);
      setSelectedAdapterId("");
      void versions.refetch();
    },
    onError: (error) => toast.notify(`草稿版本创建失败：${apiErrorMessage(error)}`, "error"),
  });

  const runPrecheck = useMutation({
    mutationFn: (rowVersion?: number | string) => teachingApi.precheck(courseId, versionId, rowVersion ?? currentVersion?.row_version ?? ""),
    onSuccess: () => {
      toast.notify("预检作业已提交，可查看阶段进度");
      void versions.refetch();
      void queryClient.invalidateQueries({ queryKey: keys.precheckRuns(versionId) });
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const saveSpec = useMutation({
    mutationFn: () => teachingApi.saveExecutionSpec(
      courseId,
      versionId,
      {
        tests_json: testsJson,
        schema_version: 2,
        language: specLanguage || null,
        toolchain_version: specToolchainVersion || null,
        language_standard: specLanguageStandard || null,
        entrypoint: specLanguage
          ? (specEntrypoint.trim() || selectedToolchain?.entrypoint || null)
          : null,
        timeout_seconds: Number(specTimeout) || 10,
        memory_mb: Number(specMemory) || 256,
        cpu_millicores: Number(specCpu) || 500,
        comparator: specComparator,
        absolute_tolerance: Number(specAbsoluteTolerance),
        relative_tolerance: Number(specRelativeTolerance),
        network_mode: "DENY_ALL",
        materials: Object.entries(selectedMaterials).map(([asset_id, role]) => ({ asset_id, role })),
      },
      currentVersion?.row_version ?? "",
    ),
    onSuccess: (saved) => {
      toast.notify("执行规格已保存，正在运行预检");
      void versions.refetch();
      runPrecheck.mutate(saved.row_version);
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const uploadMaterial = useMutation({
    mutationFn: async (file: File) => {
      const mediaType = templateMediaType(file.name);
      if (mediaType === "application/octet-stream") throw new Error("不支持的文件类型");
      const created = await teachingApi.createTemplateAsset(
        courseId,
        templateId,
        {
          version_id: versionId,
          purpose: assetPurpose,
          file_name: file.name,
          media_type: mediaType,
          size_bytes: file.size,
          digest_sha256: await fileDigest(file),
        },
        currentVersion?.row_version ?? "",
      );
      const form = new FormData();
      Object.entries(created.upload.fields).forEach(([key, value]) => form.append(key, value));
      form.append("file", file);
      const uploaded = await fetch(created.upload.url, { method: "POST", body: form });
      if (!uploaded.ok) throw new Error("对象存储上传失败");
      return teachingApi.completeTemplateAsset(
        courseId,
        templateId,
        String(created.asset["public_id"]),
        String(created.asset["row_version"] ?? ""),
      );
    },
    onSuccess: (asset) => {
      const id = String(asset["public_id"] ?? "");
      const role = assetPurpose === "STARTER" ? "STUDENT_FILES"
        : assetPurpose === "HIDDEN_SOURCE" ? "HIDDEN_SOURCE"
          : assetPurpose === "PUBLIC_DATA" ? "PUBLIC_DATA" : "";
      if (id && role) setSelectedMaterials((current) => ({ ...current, [id]: role }));
      void queryClient.invalidateQueries({ queryKey: ["template-assets", courseId, templateId, versionId] });
      toast.notify("材料已上传，正在进行安全扫描");
    },
    onError: (error) => toast.notify(`材料上传失败：${apiErrorMessage(error)}`, "error"),
  });

  const saveMaterials = useMutation({
    mutationFn: () => {
      const spec = (currentVersion as unknown as { execution_spec?: Record<string, unknown> })?.execution_spec;
      if (!spec) throw new Error("请先保存执行规格");
      return teachingApi.updateTemplateVersion(
        courseId,
        versionId,
        {
          execution_spec: {
            ...spec,
            materials: Object.entries(selectedMaterials).map(([asset_id, role]) => ({ asset_id, role })),
          },
        },
        currentVersion?.row_version ?? "",
      );
    },
    onSuccess: () => {
      toast.notify("材料用途已保存");
      void versions.refetch();
    },
    onError: (error) => toast.notify(`材料配置保存失败：${apiErrorMessage(error)}`, "error"),
  });

  const publishVersion = useMutation({
    mutationFn: () =>
      teachingApi.publishTemplateVersion(courseId, versionId, currentVersion?.row_version ?? ""),
    onSuccess: () => {
      toast.notify("模板版本已发布，可去「实验发布」创建实验任务");
      void versions.refetch();
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const canRunPrecheck = Boolean(
    currentVersion
      && (currentVersion.status === "DRAFT" || currentVersion.status === "PRECHECK_FAILED"),
  );
  const canPublish = currentVersion?.status === "PRECHECK_PASSED";
  const canEditDraft = Boolean(
    currentVersion
      && (currentVersion.status === "DRAFT" || currentVersion.status === "PRECHECK_FAILED"),
  );

  const hasSpec = Boolean(
    currentVersion && (() => {
      const spec = (currentVersion as unknown as { execution_spec?: { schema_version?: number; entrypoint?: string } }).execution_spec;
      return spec?.schema_version === 2 || Boolean(spec?.entrypoint);
    })(),
  );

  const precheckRuns = useQuery({
    queryKey: keys.precheckRuns(versionId),
    queryFn: () => teachingApi.precheckRuns(courseId, versionId),
    enabled: Boolean(versionId),
    refetchInterval: (query) => query.state.data?.rows.some((run) => ["QUEUED", "RUNNING", "RETRY"].includes(run.status)) ? 2000 : false,
  });

  // 选中草稿版本后,回填其运行环境选择
  useEffect(() => {
    if (currentVersion?.image_id && !selectedImageId) setSelectedImageId(String(currentVersion.image_id));
    if (currentVersion?.resource_profile_id && !selectedProfileId) {
      setSelectedProfileId(String(currentVersion.resource_profile_id));
    }
  }, [currentVersion?.image_id, currentVersion?.resource_profile_id, selectedImageId, selectedProfileId]);
  const latestPrecheck = precheckRuns.data?.rows?.[0];

  const precheckStages: JobStage[] = (latestPrecheck?.stage_results ?? []).map((stage, index) => ({
    key: String(index),
    label: stage.stage,
    state: stage.result === "PASSED" ? "done"
      : stage.result === "FAILED" ? "failed"
        : stage.result === "RUNNING" ? "running" : "pending",
  }));

  return (
    <>
      <Breadcrumbs
        items={[
          { label: "教师门户" },
          { label: "实验设计", onClick: () => window.location.assign(`/courses/${courseId}/templates`) },
        ]}
        current={templateId || "配置实验模板"}
      />
      <div className="page-actions align-end">
        <span className="subtle" style={{ marginRight: "auto" }}>
          当前版本 {currentVersion ? `v${currentVersion.version_no} · ${currentVersion.status}` : "—"}{canEditDraft ? " · 可编辑" : ""}
        </span>
        <Link to={`/courses/${courseId}/templates`} className="btn">返回模板列表</Link>
        {canPublish ? (
          <Button variant="primary" disabled={!versionId || publishVersion.isPending} onClick={() => publishVersion.mutate()}>
            {publishVersion.isPending ? "发布中…" : "发布模板版本"}
          </Button>
        ) : null}
        <Button
          variant="primary"
          disabled={!versionId || !canRunPrecheck || runPrecheck.isPending}
          title={canRunPrecheck ? undefined : "预检已通过后不能重复运行；如需修改，请撤回发布或新建版本"}
          onClick={() => runPrecheck.mutate()}
        >
          {runPrecheck.isPending ? "预检提交中…" : "运行预检"}
        </Button>
      </div>

      <div className="editor">
        <aside className="panel steps">
          {STEPS.map((label, index) => (
            <button type="button" key={label} className={`step${step === label ? " active" : ""}`} onClick={() => setStep(label)}>
              <span>{String(index + 1).padStart(2, "0")}　{label}</span>
              <span>{(chapters.data?.rows?.length ?? 0) > index ? "✓" : ""}</span>
            </button>
          ))}
        </aside>

        <Panel>
          {step === "基础信息" ? (
            <RequestStateView loading={versions.isLoading} error={versions.error}
              onRetry={() => void versions.refetch()}
              empty={!currentVersion} emptyState={<EmptyState title="暂无模板版本" hint="先在「运行环境」步骤初始化草稿版本。" />}>
              <div>
                <label className="form-label">模板版本</label>
                <select className="field" value={versionId} onChange={(event) => setSelectedVersion(event.target.value)}>
                  {(versions.data?.rows ?? []).map((version) => (
                    <option key={version.public_id} value={version.public_id}>
                      v{version.version_no} · {version.status}
                    </option>
                  ))}
                </select>
                <label className="form-label">运行时类型</label>
                <input className="field" value={currentVersion?.runtime_type ?? "docker_swarm"} disabled readOnly />
              </div>
            </RequestStateView>
          ) : null}

          {step === "内容结构" ? (
            <RequestStateView loading={chapters.isLoading} error={chapters.error}
              onRetry={() => void chapters.refetch()}
              empty={!currentVersion}
              emptyState={
                <EmptyState
                  title="暂无模板版本"
                  hint="先在「运行环境」步骤选择适配器、镜像与规格并初始化草稿版本。"
                />}>
              <div>
                <div className="panel-title"><h2>模板章节</h2><span className="status good">{chapters.data?.rows?.length ?? 0} 个章节</span></div>
                {(chapters.data?.rows ?? []).map((chapter) => (
                  <div className="item" key={chapter.public_id}>
                    <div>
                      <strong>{chapter.sort_order + 1}. {chapter.title}</strong>
                      <small>{chapter.description ?? "—"}</small>
                    </div>
                    <span className="status neutral">{chapter.status}</span>
                  </div>
                ))}
                <div className="section">
                  <label className="form-label" htmlFor="chapter-title">新增章节标题</label>
                  <input id="chapter-title" className="field" value={chapterTitle} onChange={(event) => setChapterTitle(event.target.value)} />
                  <label className="form-label" htmlFor="chapter-desc">章节说明</label>
                  <textarea id="chapter-desc" className="field" rows={2} value={chapterDescription} onChange={(event) => setChapterDescription(event.target.value)} />
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <Button size="sm" disabled={!chapterTitle.trim()} onClick={() => addChapter.mutate()}>保存章节</Button>
                    {addChapter.isPending ? <small>章节写入中…</small> : null}
                  </div>
                  <div className="section">
                    <label className="form-label" htmlFor="task-chapter">所属章节</label>
                    <select id="task-chapter" className="field" value={taskChapterId}
                      onChange={(event) => setTaskChapterId(event.target.value)}>
                      <option value="">选择章节</option>
                      {(chapters.data?.rows ?? []).map((chapter) => (
                        <option key={chapter.public_id} value={chapter.public_id}>
                          {chapter.sort_order + 1}. {chapter.title}
                        </option>
                      ))}
                    </select>
                    <label className="form-label" htmlFor="task-title">任务标题</label>
                    <input id="task-title" className="field" value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} />
                    <label className="form-label" htmlFor="task-desc">任务说明</label>
                    <textarea id="task-desc" className="field" rows={2} value={taskDescription}
                      onChange={(event) => setTaskDescription(event.target.value)} />
                    <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                      <Button size="sm" disabled={!taskChapterId || !taskTitle.trim()} onClick={() => addTask.mutate()}>保存任务</Button>
                      {addTask.isPending ? <small>任务写入中…</small> : null}
                    </div>
                    {(chapters.data?.rows ?? []).some((chapter) => chapter.tasks.length) ? (
                      <div className="section">
                        <strong>章节任务</strong>
                        {(chapters.data?.rows ?? []).flatMap((chapter) => chapter.tasks.map((task) => (
                          <div className="status-line" key={task.public_id}>
                            {chapter.title} · {task.title}
                          </div>
                        )))}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </RequestStateView>
          ) : null}

          {step === "运行环境" ? (
            <div>
              <div className="panel-title">
                <h2>镜像与资源</h2>
                <span className="subtle">来自治理目录：已启用适配器、已扫描批准镜像、已生效规格</span>
              </div>
              {governanceImages.length
                ? governanceImages.map((image) => (
                  <label className="item" key={String(image.public_id)} style={{ cursor: "pointer", display: "flex", gap: 10, alignItems: "center" }}>
                    <input type="radio" name="template-image" checked={selectedImageId === image.public_id}
                      onChange={() => setSelectedImageId(String(image.public_id))} />
                    <div style={{ flex: 1 }}>
                      <strong>{String(image.repository ?? "")} {String(image.display_tag ?? "")}</strong>
                      <small>{String(image.digest ?? "").slice(0, 20)}…</small>
                    </div>
                    <StatusBadge tone="good">已批准·已扫描</StatusBadge>
                  </label>
                ))
                : <EmptyState title="治理目录暂无可用镜像" hint="请联系平台管理员在治理目录中接入并批准镜像。" />}
              <div className="section">
                <label className="form-label">运行时适配器</label>
                {adapters.length
                  ? adapters.map((adapter) => (
                    <label className="resource" key={String(adapter.public_id)} style={{ cursor: "pointer", display: "flex", gap: 10, alignItems: "center" }}>
                      <input type="radio" name="template-adapter" checked={selectedAdapterId === adapter.public_id}
                        onChange={() => setSelectedAdapterId(String(adapter.public_id))} />
                      <div>
                        <strong>{String(adapter.name ?? adapter.code ?? "")}</strong>
                        <span className="resource-spec">{String(adapter.driver ?? "")}</span>
                      </div>
                    </label>
                  ))
                  : <p className="subtle">平台尚未启用任何运行时适配器。</p>}
                <label className="form-label">资源规格</label>
                {profiles.length
                  ? profiles.map((profile) => (
                    <label className="resource" key={String(profile.public_id)} style={{ cursor: "pointer", display: "flex", gap: 10, alignItems: "center" }}>
                      <input type="radio" name="template-profile" checked={selectedProfileId === profile.public_id}
                        onChange={() => setSelectedProfileId(String(profile.public_id))} />
                      <div>
                        <strong>{String(profile.name ?? profile.code ?? "")}</strong>
                        <span className="resource-spec">
                          {String(profile.cpu_millicores ?? "?")}m CPU · {String(profile.memory_mb ?? "?")}MB · {String(profile.disk_gb ?? "?")}GB
                        </span>
                      </div>
                    </label>
                  ))
                  : <p className="subtle">平台配置的资源规格完成后，此处会显示 CPU / 内存 / 磁盘 / 网络明细。</p>}
                <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                  {versionId ? (
                    <Button size="sm" variant="primary"
                      disabled={!selectedImageId || !selectedProfileId || saveEnvironment.isPending}
                      onClick={() => saveEnvironment.mutate()}>
                      {saveEnvironment.isPending ? "保存中…" : "保存运行环境"}
                    </Button>
                  ) : (
                    <Button size="sm" variant="primary"
                      disabled={!selectedAdapterId || !selectedImageId || !selectedProfileId || initializeVersion.isPending}
                      onClick={() => initializeVersion.mutate()}>
                      {initializeVersion.isPending ? "创建中…" : "初始化草稿版本"}
                    </Button>
                  )}
                  {versionId ? null : <small>选择适配器、镜像与规格后将创建首个草稿版本。</small>}
                </div>
              </div>
            </div>
          ) : null}

          {step === "报告与评审" ? (
            <div>
              <h2>报告与评审</h2>
              <p className="subtle">报告模板与 Rubric 属于模板版本资产与评审策略,发布后学生工作台以该版本为准。</p>
              <div className="section">
                <strong>评审策略(report_policy / review_policy)</strong>
                <div className="report-submission-copy" style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>
                  {JSON.stringify({ report_policy: currentVersion?.report_policy ?? {}, review_policy: currentVersion?.review_policy ?? {} }, null, 2)}
                </div>
              </div>
              <div className="section">
                <p className="subtle" style={{ margin: 0 }}>
                  正文模板是版本资产:在「模板资产」上传 report 模板后绑定到版本;当前简表编辑器暂未提供资产绑定入口。
                </p>
              </div>
            </div>
          ) : null}

          {step === "预检与发布" ? (
            <div>
              <div className="panel-title">
                <h2>预检与发布</h2>
                {latestPrecheck ? <StatusBadge tone={latestPrecheck.status === "PASSED" ? "good" : latestPrecheck.status === "FAILED" ? "bad" : "blue"}>
                  {latestPrecheck.status === "PASSED" ? "预检通过" : latestPrecheck.status === "FAILED" ? "预检失败" : "预检进行中"}
                </StatusBadge> : <span className="subtle">尚未预检</span>}
              </div>
              {canPublish ? (
                <div className="section">
                  <strong>预检已通过</strong>
                  <p className="subtle" style={{ marginTop: 4 }}>
                    该版本已锁定为最终规格，不能重复预检。点击右上角「发布模板版本」生效；后续修改请撤回发布或新版本。
                  </p>
                </div>
              ) : null}
              {currentVersion?.status === "PUBLISHED" ? (
                <div className="section">
                  <strong>该版本已发布</strong>
                  <p className="subtle" style={{ marginTop: 4 }}>
                    发布的版本为不可变契约；如需调整，请撤回发布或基于该版本新建草稿。
                  </p>
                </div>
              ) : null}
              {canEditDraft && currentVersion && !hasSpec ? (
                <div className="section">
                  <strong>执行规格（首次运行预检前必须配置一次）</strong>
                  <p className="subtle" style={{ marginTop: 4 }}>
                    版本缺少 execution_spec，预检会在 ASSETS 阶段失败。此表单会保存默认测试用例与运行参数。
                  </p>
                  <label className="form-label" htmlFor="spec-tests">tests.json（测试用例）</label>
                  <textarea id="spec-tests" className="field" rows={4} value={testsJson}
                    onChange={(event) => setTestsJson(event.target.value)} />
                  <div className="section">
                    <label className="form-label" htmlFor="spec-language">编程语言</label>
                    <select id="spec-language" className="field" value={specLanguage}
                      onChange={(event) => {
                        const next = toolchains.find((item) => item.language === event.target.value);
                        setSpecLanguage(event.target.value);
                        setSpecToolchainVersion("");
                        setSpecLanguageStandard("");
                        setSpecEntrypoint(next?.entrypoint ?? "");
                      }}>
                      <option value="">学生自选（当前可用：{studentLanguages.join("、") || "无"}）</option>
                      {toolchains.map((item) => (
                        <option key={item.language} value={item.language}>
                          {item.language}{item.available ? "" : "（环境尚未验收，暂不能发布）"}
                        </option>
                      ))}
                    </select>
                    <small className="subtle">
                      {selectedToolchain
                        ? `工具链：${selectedToolchain.toolchain_id} ${specToolchainVersion || selectedToolchain.versions.find((item) => item.default)?.version}；${specLanguageStandard || selectedToolchain.default_standard}${selectedToolchain.available ? "" : "；当前运行镜像未提供该工具链"}`
                        : `学生仅可在已验收语言中选择：${studentLanguages.join("、") || "无"}；使用各语言系统默认版本`}
                    </small>
                    {selectedToolchain ? (
                      <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
                        <div>
                          <label className="form-label" htmlFor="spec-toolchain-version">工具链版本</label>
                          <select id="spec-toolchain-version" className="field" value={specToolchainVersion}
                            onChange={(event) => setSpecToolchainVersion(event.target.value)}>
                            <option value="">系统默认</option>
                            {selectedToolchain.versions.map((item) => (
                              <option key={item.version} value={item.version}>{item.version}{item.default ? "（默认）" : ""}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="form-label" htmlFor="spec-language-standard">语言标准</label>
                          <select id="spec-language-standard" className="field" value={specLanguageStandard}
                            onChange={(event) => setSpecLanguageStandard(event.target.value)}>
                            <option value="">系统默认</option>
                            {selectedToolchain.standards.map((item) => <option key={item} value={item}>{item}</option>)}
                          </select>
                        </div>
                      </div>
                    ) : null}
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                    <div>
                      <label className="form-label" htmlFor="spec-comparator">输出比较方式</label>
                      <select id="spec-comparator" className="field" value={specComparator}
                        onChange={(event) => setSpecComparator(event.target.value)}>
                        <option value="token">忽略空白后逐项比较</option>
                        <option value="numeric">数值误差比较</option>
                      </select>
                    </div>
                    {specComparator === "numeric" ? <>
                      <div>
                        <label className="form-label" htmlFor="spec-absolute-tolerance">绝对误差</label>
                        <input id="spec-absolute-tolerance" className="field" type="number" min="0" step="any"
                          value={specAbsoluteTolerance} onChange={(event) => setSpecAbsoluteTolerance(event.target.value)} />
                      </div>
                      <div>
                        <label className="form-label" htmlFor="spec-relative-tolerance">相对误差</label>
                        <input id="spec-relative-tolerance" className="field" type="number" min="0" step="any"
                          value={specRelativeTolerance} onChange={(event) => setSpecRelativeTolerance(event.target.value)} />
                      </div>
                    </> : null}
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
                    <div>
                      <label className="form-label" htmlFor="spec-entry">入口文件</label>
                      <input id="spec-entry" className="field" style={{ width: 140 }} value={specEntrypoint}
                        onChange={(event) => setSpecEntrypoint(event.target.value)} />
                    </div>
                    <div>
                      <label className="form-label" htmlFor="spec-timeout">超时(秒)</label>
                      <input id="spec-timeout" className="field" style={{ width: 100 }} value={specTimeout}
                        onChange={(event) => setSpecTimeout(event.target.value)} />
                    </div>
                    <div>
                      <label className="form-label" htmlFor="spec-memory">内存(MB)</label>
                      <input id="spec-memory" className="field" style={{ width: 100 }} value={specMemory}
                        onChange={(event) => setSpecMemory(event.target.value)} />
                    </div>
                    <div>
                      <label className="form-label" htmlFor="spec-cpu">CPU(m)</label>
                      <input id="spec-cpu" className="field" style={{ width: 100 }} value={specCpu}
                        onChange={(event) => setSpecCpu(event.target.value)} />
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                    <Button size="sm" variant="primary"
                      disabled={!versionId || saveSpec.isPending}
                      onClick={() => saveSpec.mutate()}>
                      {saveSpec.isPending ? "保存中…" : "保存执行规格并运行预检"}
                    </Button>
                  </div>
                </div>
              ) : null}
              {canEditDraft && currentVersion ? (
                <div className="section">
                  <strong>实验材料</strong>
                  <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "end" }}>
                    <div>
                      <label className="form-label" htmlFor="asset-purpose">材料用途</label>
                      <select id="asset-purpose" className="field" value={assetPurpose}
                        onChange={(event) => setAssetPurpose(event.target.value)}>
                        <option value="MANUAL">实验指导书（TXT / Markdown / PDF）</option>
                        <option value="STARTER">学生文件（ZIP / TAR）</option>
                        <option value="HIDDEN_SOURCE">后台辅助源码（ZIP / TAR）</option>
                        <option value="PUBLIC_DATA">学生公开数据（CSV / JSON / ZIP）</option>
                      </select>
                    </div>
                    <div>
                      <label className="form-label" htmlFor="asset-file">选择文件</label>
                      <input id="asset-file" className="field" type="file"
                        accept={assetPurpose === "MANUAL" ? ".txt,.md,.pdf"
                          : assetPurpose === "PUBLIC_DATA" ? ".csv,.json,.txt,.zip,.tar,.gz,.tgz,.tar.gz"
                            : ".zip,.tar,.gz,.tgz,.tar.gz"}
                        disabled={uploadMaterial.isPending}
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) uploadMaterial.mutate(file);
                          event.target.value = "";
                        }} />
                    </div>
                    {uploadMaterial.isPending ? <small>上传与扫描请求处理中…</small> : null}
                  </div>
                  {(templateAssets.data?.rows ?? []).length ? (
                    <div style={{ marginTop: 8 }}>
                      {(templateAssets.data?.rows ?? []).map((asset) => {
                        const id = String(asset["public_id"] ?? "");
                        const purpose = String(asset["purpose"] ?? "");
                        const role = purpose === "STARTER" ? "STUDENT_FILES"
                          : purpose === "HIDDEN_SOURCE" ? "HIDDEN_SOURCE"
                            : purpose === "PUBLIC_DATA" ? "PUBLIC_DATA" : "";
                        const scanStatus = String(asset["scan_status"] ?? "");
                        return (
                          <div className="item" key={id}>
                            {role ? (
                              <input type="checkbox" aria-label={`纳入材料 ${String(asset["file_name"] ?? "")}`}
                                checked={selectedMaterials[id] === role}
                                disabled={scanStatus !== "CLEAN"}
                                onChange={(event) => setSelectedMaterials((current) => {
                                  const next = { ...current };
                                  if (event.target.checked) next[id] = role;
                                  else delete next[id];
                                  return next;
                                })} />
                            ) : null}
                            <div style={{ flex: 1 }}>
                              <strong>{String(asset["file_name"] ?? "")}</strong>
                              <small>{purpose === "MANUAL" ? "实验指导书" : role || purpose}</small>
                            </div>
                            <StatusBadge tone={scanStatus === "CLEAN" ? "good" : scanStatus === "PENDING" ? "blue" : "bad"}>
                              {scanStatus === "CLEAN" ? "扫描通过" : scanStatus === "PENDING" ? "扫描中" : "不可用"}
                            </StatusBadge>
                          </div>
                        );
                      })}
                    </div>
                  ) : <p className="subtle">尚未上传材料。</p>}
                  {selectedMaterialNotReady ? <p className="subtle">所选材料需通过扫描后才能保存执行规格。</p> : null}
                  {hasSpec ? (
                    <Button size="sm" variant="primary" disabled={saveMaterials.isPending || selectedMaterialNotReady}
                      onClick={() => saveMaterials.mutate()}>
                      {saveMaterials.isPending ? "保存中…" : "保存材料用途"}
                    </Button>
                  ) : null}
                </div>
              ) : null}
              {latestPrecheck ? (
                <AsyncJobProgress
                  status={latestPrecheck.status === "PASSED" ? "succeeded" : latestPrecheck.status === "FAILED" ? "failed" : "processing"}
                  stages={precheckStages}
                  failureReason="预检失败时，请修正对应章节或资源配置后重新运行。"
                  onRetry={() => runPrecheck.mutate()}
                />
              ) : (
                <EmptyState title="还没有预检记录" hint="点击「运行预检」生成最新预检结果。" />
              )}
              <div className="section" style={{ display: "flex", gap: 8 }}>
                <Button variant="primary" onClick={() => navigate(`/courses/${courseId}/publishing?template=${templateId}`)}>配置并发布此实验</Button>
                <Button onClick={() => navigate(`/courses/${courseId}/templates/${templateId}/validate`)}>进入验证工作台</Button>
              </div>
            </div>
          ) : null}
        </Panel>
      </div>
    </>
  );
}

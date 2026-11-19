import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { teachingApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, Panel, RequestStateView, useToast } from "@edu/ui";
import { AssessmentQuestions } from "@/components/assessment-questions";
import {
  PRECHECK_STATUS_LABEL,
  TEMPLATE_VERSION_STATUS_LABEL,
  apiErrorMessage,
} from "@/lib/format";
import { precheckFailureMessage } from "@/lib/precheck-errors";

const RESOURCE_TIERS = [
  { cpu: 250, memory: 256, label: "轻量", hint: "选择题判题、小脚本" },
  { cpu: 500, memory: 512, label: "标准", hint: "常规编程题，推荐" },
  { cpu: 1000, memory: 1024, label: "加强", hint: "Java/Go 编译、输入较大的用例" },
] as const;

function profileDetail(profile: { cpu_millicores: number; memory_mb: number }): string {
  const memory = profile.memory_mb >= 1024 && profile.memory_mb % 1024 === 0
    ? `${profile.memory_mb / 1024} GB`
    : `${profile.memory_mb} MB`;
  return `${Number((profile.cpu_millicores / 1000).toFixed(2))} 核 CPU / ${memory} 内存`;
}

export function TemplateEditor() {
  const { courseId = "", templateId = "" } = useParams();
  const toast = useToast();
  const [selected, setSelected] = useState("");
  const [profile, setProfile] = useState("");
  const [busy, setBusy] = useState(false);
  const versions = useQuery({ queryKey: keys.templateVersions(courseId, templateId),
    queryFn: () => teachingApi.templateVersions(courseId, templateId),
    refetchInterval: query => query.state.data?.rows.some(v => v.status === "PRECHECKING") ? 2000 : false });
  const version = versions.data?.rows.find(v => v.public_id === selected) ?? versions.data?.rows[0];
  const options = useQuery({ queryKey: keys.templateOptions(courseId), queryFn: () => teachingApi.templateOptions(courseId) });
  const adapters = (options.data?.runtime_adapters ?? []).filter(r => r.driver === "DOCKER_LOCAL");
  const images = options.data?.images ?? [];
  const profiles = options.data?.resource_profiles ?? [];
  const adapterId = version?.runtime_adapter_id || (adapters.length === 1 ? adapters[0]?.public_id ?? "" : "");
  const imageId = version?.image_id || (images.length === 1 ? images[0]?.public_id ?? "" : "");
  const orderedProfiles = [...profiles].sort((a, b) => a.cpu_millicores - b.cpu_millicores || a.memory_mb - b.memory_mb);
  const standardProfileId = profiles.find(p => p.cpu_millicores === 500 && p.memory_mb === 512)?.public_id;
  const profileId = profile || version?.resource_profile_id || standardProfileId || orderedProfiles[0]?.public_id || "";
  const checks = useQuery({ queryKey: keys.precheckRuns(version?.public_id ?? ""),
    queryFn: () => teachingApi.precheckRuns(courseId, version!.public_id), enabled: !!version,
    refetchInterval: query => {
      const status = query.state.data?.rows[0]?.status;
      const running = status === "QUEUED" || status === "RUNNING" || status === "RETRY";
      return running || version?.status === "PRECHECKING" ? 2000 : false;
    } });
  async function act(operation: () => Promise<unknown>) {
    setBusy(true);
    try { await operation(); await versions.refetch(); await checks.refetch(); }
    catch (error) { toast.notify(apiErrorMessage(error), "error"); }
    finally { setBusy(false); }
  }
  async function chooseProfile(id: string) {
    if (!version || busy || id === profileId) return;
    setProfile(id);
    try {
      await teachingApi.updateTemplateVersion(courseId, version.public_id, {
        runtime_type: "CONTAINER",
        runtime_adapter_id: adapterId,
        image_id: imageId,
        resource_profile_id: id,
      }, version.row_version);
      await versions.refetch();
    } catch (error) {
      setProfile("");
      toast.notify(apiErrorMessage(error), "error");
    }
  }
  const locked = !version || version.status === "PUBLISHED" || version.status === "PRECHECKING" || busy;
  return <>
    <Breadcrumbs items={[{ label: "教师门户" }, { label: "实验模板" }]} current="编辑实验" />
    <div className="tab-head"><h2>实验设计</h2></div>
    <Panel>
      <h2>实验题目与发布版本</h2>
      <RequestStateView loading={versions.isLoading} error={versions.error} empty={false} emptyState={null} onRetry={() => void versions.refetch()} />
      <label>版本<select className="field" value={version?.public_id ?? ""} onChange={e => { setSelected(e.target.value); setProfile(""); }}>
        {versions.data?.rows.map(v => <option key={v.public_id} value={v.public_id}>第 {v.version_no} 版 · {TEMPLATE_VERSION_STATUS_LABEL[v.status] ?? v.status}</option>)}
      </select></label>
      <button className="btn" disabled={busy} onClick={() => void act(async () => {
        const created = await teachingApi.createTemplateVersion(courseId, templateId, {});
        setSelected(created.public_id);
      })}>新建草稿版本</button>
      <p className="subtle">发布后内容固定，修改请新建版本。</p>
    </Panel>
    {version && <>
      <AssessmentQuestions key={version.public_id} courseId={courseId} templateId={templateId} version={version} refresh={versions.refetch} />
      <Panel className="section"><h2>预检与发布</h2>
        <span className="form-label">判题资源</span>
        <div role="radiogroup" aria-label="判题资源" style={{ display: "grid", gap: 8, margin: "0 0 8px" }}>
          {orderedProfiles.map(p => {
            const tier = RESOURCE_TIERS.find(t => t.cpu === p.cpu_millicores && t.memory === p.memory_mb);
            const checked = profileId === p.public_id;
            return (
              <label key={p.public_id} htmlFor={`judge-resource-${p.public_id}`} style={{
                display: "flex", alignItems: "flex-start", gap: 10,
                border: `1px solid ${checked ? "var(--teal)" : "var(--line)"}`,
                borderRadius: 10, padding: "10px 12px", cursor: locked ? "not-allowed" : "pointer",
                opacity: locked ? 0.6 : 1,
              }}>
                <input id={`judge-resource-${p.public_id}`} type="radio" name="judge-resource" value={p.public_id} checked={checked}
                  disabled={locked} onChange={() => void chooseProfile(p.public_id)} />
                <span style={{ fontWeight: 600 }}>
                  {tier ? `${tier.label} · ${profileDetail(p)}` : profileDetail(p)}
                  <span className="field-hint" style={{ display: "block", fontWeight: 400 }}>{tier?.hint ?? "自定义规格"}</span>
                </span>
              </label>
            );
          })}
        </div>
        {options.error && <p role="alert">运行资源载入失败</p>}
        {!options.isLoading && orderedProfiles.length === 0 && <p role="alert">暂无可用的判题资源，请联系管理员。</p>}
        <p className="field-hint">单次判题最多使用上述资源，超出会被终止；题目里的内存限制不能超过这一档。</p>
        <button className="btn" disabled={locked} onClick={() => void act(() => teachingApi.precheck(courseId, version.public_id, version.row_version))}>执行预检</button>
        {' '}
        <button className="btn primary" disabled={busy || version.status !== "PRECHECK_PASSED"} onClick={() => void act(() => teachingApi.publishTemplateVersion(courseId, version.public_id, version.row_version))}>发布模板版本</button>
        {checks.data?.rows.map(check => <p key={check.public_id}>
          {check.status === "FAILED"
            ? `未通过。${precheckFailureMessage(check)}`
            : (PRECHECK_STATUS_LABEL[check.status] ?? check.status)}
        </p>)}
        <Link className="btn" to={`/courses/${courseId}/publishing`}>配置实验发布、报告与截止时间</Link>
      </Panel>
    </>}
  </>;
}

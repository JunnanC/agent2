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

export function TemplateEditor() {
  const { courseId = "", templateId = "" } = useParams();
  const toast = useToast();
  const [selected, setSelected] = useState("");
  const [adapter, setAdapter] = useState("");
  const [image, setImage] = useState("");
  const [profile, setProfile] = useState("");
  const [busy, setBusy] = useState(false);
  const versions = useQuery({ queryKey: keys.templateVersions(courseId, templateId),
    queryFn: () => teachingApi.templateVersions(courseId, templateId),
    refetchInterval: query => query.state.data?.rows.some(v => v.status === "PRECHECKING") ? 2000 : false });
  const version = versions.data?.rows.find(v => v.public_id === selected) ?? versions.data?.rows[0];
  const options = useQuery({ queryKey: keys.templateOptions(courseId), queryFn: () => teachingApi.templateOptions(courseId) });
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
  const locked = !version || version.status === "PUBLISHED" || version.status === "PRECHECKING" || busy;
  return <>
    <Breadcrumbs items={[{ label: "教师门户" }, { label: "实验模板" }]} current="编辑实验" />
    <Panel>
      <h1>实验题目与发布版本</h1>
      <RequestStateView loading={versions.isLoading} error={versions.error} empty={false} emptyState={null} onRetry={() => void versions.refetch()} />
      <label>版本<select className="field" value={version?.public_id ?? ""} onChange={e => { setSelected(e.target.value); setAdapter(""); setImage(""); setProfile(""); }}>
        {versions.data?.rows.map(v => <option key={v.public_id} value={v.public_id}>第 {v.version_no} 版 · {TEMPLATE_VERSION_STATUS_LABEL[v.status] ?? v.status}</option>)}
      </select></label>
      <button className="btn" disabled={busy} onClick={() => void act(async () => {
        const created = await teachingApi.createTemplateVersion(courseId, templateId, {});
        setSelected(created.public_id);
      })}>新建草稿版本</button>
      <p>按题目组成支持纯选择、纯编程或混合实验。发布后的内容固定，修改请新建版本。</p>
    </Panel>
    {version && <>
      <AssessmentQuestions key={version.public_id} courseId={courseId} templateId={templateId} version={version} refresh={versions.refetch} />
      <Panel className="section"><h2>编程题运行环境</h2>
        <p>在上方编辑编程题内容；这里设置这些题目共用的运行环境和资源。纯选择题不需要配置。</p>
        {options.error && <p role="alert">运行资源载入失败</p>}
        <fieldset disabled={locked}><legend>运行环境</legend>
          <label>运行适配器<select className="field" value={adapter || version.runtime_adapter_id || ""} onChange={e => setAdapter(e.target.value)}>
            <option value="">选择 Docker Local</option>
            {options.data?.runtime_adapters.filter(r => r.driver === "DOCKER_LOCAL").map(r => <option key={r.public_id} value={r.public_id}>{r.name}</option>)}
          </select></label>
          <label>执行镜像<select className="field" value={image || version.image_id || ""} onChange={e => setImage(e.target.value)}>
            <option value="">选择已审批 stdio 镜像</option>
            {options.data?.images.map(i => <option key={i.public_id} value={i.public_id}>{i.repository} · {i.digest.slice(0, 19)}</option>)}
          </select></label>
          <label>资源规格<select className="field" value={profile || version.resource_profile_id || ""} onChange={e => setProfile(e.target.value)}>
            <option value="">选择资源规格</option>
            {options.data?.resource_profiles.map(p => <option key={p.public_id} value={p.public_id}>{p.name}</option>)}
          </select></label>
          <button className="btn" onClick={() => void act(() => teachingApi.updateTemplateVersion(courseId, version.public_id, {
            runtime_type: "CONTAINER", runtime_adapter_id: adapter || version.runtime_adapter_id,
            image_id: image || version.image_id, resource_profile_id: profile || version.resource_profile_id,
          }, version.row_version))}>保存运行环境</button>
        </fieldset>
      </Panel>
      <Panel className="section"><h2>预检与发布</h2>
        <button className="btn" disabled={locked} onClick={() => void act(() => teachingApi.precheck(courseId, version.public_id, version.row_version))}>执行预检</button>
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

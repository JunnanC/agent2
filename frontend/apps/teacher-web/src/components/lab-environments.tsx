import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { labAssessmentApi, type LabEnvironment, type LabEnvironmentInput } from "@edu/api-client";
import { Modal, Panel, useToast } from "@edu/ui";
import { apiErrorMessage, formatDateTime } from "@/lib/format";
import "./lab-workbench.css";

const baseline: LabEnvironmentInput = {
  name: "", language: "python", cpu_millicores: 1000, memory_mb: 512,
  image_id: "", runtime_adapter_id: "",
};

const languages = { python: "Python", java: "Java", c: "C", cpp: "C++", go: "Go" } as const;

export function TestLabEnvironment({ courseId, environmentId, publicationId }: {
  courseId: string; environmentId: string; publicationId?: string;
}) {
  const toast = useToast();
  const test = useMutation({
    mutationFn: () => labAssessmentApi.testEnvironment(courseId, environmentId, publicationId),
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });
  const testId = test.data?.test_id ?? "";
  const status = useQuery({
    queryKey: ["lab-environment-test", courseId, environmentId, testId],
    queryFn: () => labAssessmentApi.testStatus(courseId, environmentId, testId),
    enabled: Boolean(testId),
    refetchInterval: (query) => {
      const state = query.state.data?.status;
      return query.state.status === "error" || state === "PASSED" || state === "FAILED" ? false : 1500;
    },
  });
  const result = status.data;
  const pending = test.isPending || Boolean(testId && !status.isError
    && result?.status !== "PASSED" && result?.status !== "FAILED");
  return <div>
    <button className="btn sm" type="button" disabled={pending} onClick={() => test.mutate()}>
      {pending ? "正在测试…" : "测试环境"}
    </button>
    {result?.status === "PASSED" && <p role="status">编译或解释执行通过</p>}
    {result?.status === "FAILED" && <p role="alert">
      {result.reason === "runtime_unavailable" ? "无法使用所选运行时或镜像。" : "环境测试未通过。"}
      {result.stderr && <span className="lab-code"> {result.stderr}</span>}
    </p>}
    {status.isError && <p role="alert">暂时无法读取测试结果，可重新测试。</p>}
  </div>;
}

export function LabEnvironments({ courseId, onClose }: { courseId: string; onClose: () => void }) {
  const toast = useToast();
  const [target, setTarget] = useState<LabEnvironment | undefined>();
  const [form, setForm] = useState<LabEnvironmentInput | null>(null);
  const environments = useQuery({
    queryKey: ["lab-environments", courseId],
    queryFn: () => labAssessmentApi.environments(courseId),
    refetchInterval: 12000,
  });
  const save = useMutation({
    mutationFn: (input: LabEnvironmentInput) => labAssessmentApi.saveEnvironment(courseId, input, target),
    onSuccess: () => {
      toast.notify("实验环境已保存");
      setForm(null);
      setTarget(undefined);
      void environments.refetch();
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });
  const data = environments.data;

  function open(item?: LabEnvironment, copy = false) {
    setTarget(copy ? undefined : item);
    setForm(item ? {
      name: copy ? `${item.name.slice(0, 115)} 副本` : item.name,
      language: item.language, cpu_millicores: item.cpu_millicores, memory_mb: item.memory_mb,
      image_id: item.image_id, runtime_adapter_id: item.runtime_adapter_id,
    } : { ...baseline, runtime_adapter_id: data?.adapters[0]?.public_id ?? "",
      image_id: data?.images[0]?.public_id ?? "" });
  }
  const field = <K extends keyof LabEnvironmentInput>(key: K, value: LabEnvironmentInput[K]) =>
    setForm((current) => current ? { ...current, [key]: value } : current);

  return <Modal open wide title="实验环境" onClose={onClose}
    actions={<button className="btn" type="button" onClick={onClose}>关闭</button>}>
    <div className="lab-form">
      {!form && <div className="page-actions"><button className="btn primary" type="button" onClick={() => open()}>新建环境</button></div>}
      {environments.isPending && <p role="status">正在读取实验环境…</p>}
      {environments.isError && <p role="alert">无法读取实验环境。 <button type="button" className="btn" onClick={() => void environments.refetch()}>重试</button></p>}
      {form && <Panel title={<h3>{target ? "编辑环境" : "新建环境"}</h3>}>
        <form className="lab-form" onSubmit={(event) => { event.preventDefault(); save.mutate(form); }}>
          <div className="lab-fields">
            <label>环境名称<input className="field" value={form.name} maxLength={120} required
              onChange={(event) => field("name", event.target.value)} /></label>
            <label>语言<select className="field" value={form.language}
              onChange={(event) => field("language", event.target.value as LabEnvironmentInput["language"])}>
              {Object.entries(languages).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select></label>
            <label>已启用运行时<select className="field" value={form.runtime_adapter_id} required
              onChange={(event) => field("runtime_adapter_id", event.target.value)}>
              <option value="">选择运行时</option>
              {data?.adapters.map((item) => <option key={item.public_id} value={item.public_id}>{item.name}</option>)}
            </select></label>
            <label>已审批镜像<select className="field" value={form.image_id} required
              onChange={(event) => field("image_id", event.target.value)}>
              <option value="">选择镜像</option>
              {data?.images.map((item) => <option key={item.public_id} value={item.public_id}>{item.name}</option>)}
            </select></label>
            <label>CPU（毫核）<input className="field" type="number" required min={100} max={8000}
              value={form.cpu_millicores} onChange={(event) => field("cpu_millicores", Number(event.target.value))} /></label>
            <label>内存（MiB）<input className="field" type="number" required min={64} max={16384}
              value={form.memory_mb} onChange={(event) => field("memory_mb", Number(event.target.value))} /></label>
          </div>
          <div className="page-actions">
            <button type="button" className="btn" onClick={() => setForm(null)}>取消</button>
            <button type="submit" className="btn primary" disabled={save.isPending}>保存环境</button>
          </div>
        </form>
      </Panel>}
      {data && <div className="table-wrap">
        <table className="table">
          <thead><tr><th>环境</th><th>实际用量</th><th>教学班实验</th><th>操作</th></tr></thead>
          <tbody>
            {!data.rows.length && <tr><td colSpan={4}>本教学班还没有实验环境</td></tr>}
            {data.rows.map((item) => <tr key={item.public_id}>
              <td data-wrap><strong>{item.display_name}</strong></td>
              <td className="lab-usage" data-wrap>{item.usage.status === "AVAILABLE"
                ? item.usage.containers === 0 ? "空闲 · 0 个容器" : [
                  `${item.usage.containers} 个容器`,
                  `${item.usage.cpu_millicores} 毫核`,
                  `${Math.round((item.usage.memory_bytes ?? 0) / 1048576)} MiB`,
                ].join(" · ")
                : item.usage.status === "PENDING" ? "等待运行时采样" : "指标不可用"}
                {item.usage.sampled_at && <small className="subtle"> {formatDateTime(item.usage.sampled_at)}</small>}
              </td>
              <td data-wrap>{item.experiments.map((experiment) => <div key={experiment.publication_id}>
                <Link to={`/courses/${experiment.course_id}/publishing/${experiment.publication_id}/reviews?direct=1`} onClick={onClose}>{experiment.title}</Link>
              </div>)}{!item.experiments.length && "—"}</td>
              <td className="table-actions"><button className="btn sm" type="button" onClick={() => open(item)}>编辑</button>
                <button className="btn sm" type="button" onClick={() => open(item, true)}>复制</button>
                <TestLabEnvironment courseId={courseId} environmentId={item.public_id} />
              </td>
            </tr>)}
          </tbody>
        </table>
      </div>}
    </div>
  </Modal>;
}

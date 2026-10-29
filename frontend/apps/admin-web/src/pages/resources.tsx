import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { platformApi } from "@edu/api-client";
import type { PlatformImage, ResourceProfile, RuntimeAdapter, Quota } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  Breadcrumbs, Button, ConfirmDialog, Metric, Panel, RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import { useState } from "react";
import { apiErrorMessage } from "@/lib/format";

export function Resources() {
  const toast = useToast();
  const [imageTarget, setImageTarget] = useState<PlatformImage | null>(null);

  const images = useQuery({ queryKey: keys.images({}), queryFn: () => platformApi.images({ page_size: 50 }) });
  const profiles = useQuery({ queryKey: keys.resourceProfiles({}), queryFn: () => platformApi.resourceProfiles({}) });
  const adapters = useQuery({ queryKey: keys.runtimeAdapters({}), queryFn: () => platformApi.runtimeAdapters() });
  const quotas = useQuery({ queryKey: keys.quotas({}), queryFn: () => platformApi.quotas({}) });
  const instances = useQuery({ queryKey: keys.instances({ status: "ACTIVE" }), queryFn: () => platformApi.instances({ status: "ACTIVE", page_size: 1 }) });
  const sessions = useQuery({ queryKey: keys.platformWorkspaceSessions({}), queryFn: () => platformApi.workspaceSessions({ page_size: 1 }) });

  const decideImage = useMutation({
    mutationFn: (input: { target: PlatformImage; decision: "approve" | "reject" }) =>
      platformApi.decideImage(input.target.public_id, { decision: input.decision }, input.target.row_version),
    onSuccess: (_data, input) => {
      toast.notify(input.decision === "approve" ? "镜像已批准" : "已拒绝镜像");
      setImageTarget(null);
      void images.refetch();
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const imageRows = images.data?.rows ?? [];
  const profileRows = (profiles.data?.rows ?? []) as ResourceProfile[];
  const adapterRows = (adapters.data?.rows ?? []) as RuntimeAdapter[];
  const quotaRows = (quotas.data?.rows ?? []) as Quota[];
  const sessionTotal = typeof sessions.data?.total === "number"
    ? sessions.data?.total
    : (sessions.data?.rows.length ?? 0);
  const instanceTotal = typeof instances.data?.total === "number"
    ? instances.data?.total
    : (instances.data?.rows.length ?? 0);

  const approvedImages = imageRows.filter((image) => image.approval_status === "APPROVED" && image.scan_status === "CLEAN").length;
  const pendingImages = imageRows.filter((image) => image.approval_status !== "APPROVED").length;
  const quotaAlerts = quotaRows.filter((quota) => (quota.used_value ?? 0) / Math.max(1, quota.limit_value) > 0.8).length;

  const METRIC_LABEL: Record<string, string> = {
    cpu: "CPU",
    memory: "内存",
    storage: "对象存储",
    disk: "磁盘",
  };

  return (
    <>
      <Breadcrumbs items={[{ label: "平台管理" }]} current="资源治理" />
      <div className="page-actions align-end">
        <Link className="btn" to="/governance">查看治理告警</Link>
        <button type="button" className="btn primary"
          onClick={() => { void images.refetch(); void adapters.refetch(); void quotas.refetch(); void instances.refetch(); }}
          aria-label="刷新巡检列表">
          刷新巡检
        </button>
      </div>

      <Panel className="section">
        <RequestStateView loading={images.isLoading && adapters.isLoading}
          error={images.error ?? adapters.error}
          onRetry={() => { void images.refetch(); void adapters.refetch(); }}
          empty={false} emptyState={null}>
          <div className="metric-strip">
            <Metric label="运行中实例" value={instanceTotal ? String(instanceTotal) : "—"} icon="boxes" sub="当前活跃实例" />
            <Metric label="已治理镜像" value={String(approvedImages)} icon="boxes" sub="全部通过扫描" />
            <Metric label="配额预警" value={String(quotaAlerts)} icon="gauge" sub="使用率超过 80%" />
            <Metric label="工作区会话" value={sessionTotal ? String(sessionTotal) : "—"} icon="monitor" sub="会话记录" />
          </div>
        </RequestStateView>
      </Panel>

      <div className="grid two section">
        <Panel title={<><h2>运行时健康</h2>
          <span className={`status ${adapterRows.length && adapterRows.every((adapter) => adapter.health_status === "HEALTHY") ? "good" : adapterRows.length ? "warn" : "neutral"}`}>
            {adapterRows.length && adapterRows.every((adapter) => adapter.health_status === "HEALTHY") ? "全部正常" : adapterRows.length ? "存在关注项" : "—"}
          </span>
        </>}>
          <RequestStateView loading={adapters.isLoading} error={adapters.error}
            onRetry={() => void adapters.refetch()}
            empty={!adapterRows.length}
            emptyState={<div className="state-block"><strong>暂无运行时</strong></div>}>
            <div>
              {adapterRows.map((adapter) => {
                const cpuCapacity = adapter.capacity_cpu_millicores ?? 0;
                const cpuAvailable = adapter.available_cpu_millicores ?? 0;
                const usage = cpuCapacity > 0 ? Math.round(((cpuCapacity - cpuAvailable) / cpuCapacity) * 100) : null;
                const healthy = adapter.health_status === "HEALTHY";
                return (
                  <div className="item" key={adapter.public_id}>
                    <div><strong>{adapter.name} · {adapter.code}</strong><small>{adapter.driver} · 节点 {adapter.node_count ?? "—"}</small></div>
                    <StatusBadge tone={healthy && (usage ?? 0) <= 80 ? "good" : "warn"}>
                      {healthy ? `健康 ${100 - (usage ?? 0)}%` : `容量 ${usage ?? "—"}%`}
                    </StatusBadge>
                  </div>
                );
              })}
            </div>
          </RequestStateView>
        </Panel>
        <Panel title={<><h2>配额与存储</h2><span className="subtle">当前学期</span></>}>
          <RequestStateView loading={quotas.isLoading} error={quotas.error}
            onRetry={() => void quotas.refetch()}
            empty={!quotaRows.length}
            emptyState={<div className="state-block"><strong>暂无配额配置</strong><p>平台配置 CPU / 内存 / 对象存储配额后展示使用率。</p></div>}>
            <div>
              {quotaRows.map((quota) => {
                const percent = quota.limit_value
                  ? Math.round(((quota.used_value ?? 0) / quota.limit_value) * 100)
                  : 0;
                return (
                  <div className="quota-line" key={quota.public_id}>
                    <span>{METRIC_LABEL[quota.metric] ?? quota.metric}</span>
                    <div className="progress"><span style={{ width: `${percent}%` }} /></div>
                    <strong>{percent}%</strong>
                  </div>
                );
              })}
            </div>
          </RequestStateView>
        </Panel>
      </div>

      <Panel className="section" title={<><h2>镜像与资源库</h2>
        {pendingImages > 0
          ? <span className="status warn">{`${pendingImages} 个待审批`}</span>
          : <span className="status neutral">只读汇总</span>}
      </>}>
        <RequestStateView
          loading={images.isLoading || adapters.isLoading || profiles.isLoading}
          error={images.error ?? adapters.error ?? profiles.error}
          onRetry={() => { void images.refetch(); void adapters.refetch(); void profiles.refetch(); }}
          empty={!imageRows.length && !adapterRows.length && !profileRows.length}
          emptyState={<div className="state-block"><strong>暂无治理资源</strong><p>镜像、运行时与资源规格会在这里统一汇总。</p></div>}
        >
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>资源</th><th>版本</th><th>状态</th><th>最近检查</th><th>使用</th></tr></thead>
              <tbody>
                {imageRows.map((image) => (
                  <tr key={image.public_id}>
                    <td><strong>{image.display_tag}</strong><small style={{ display: "block" }}>{image.registry}</small></td>
                    <td><small>{(image.digest ?? "").slice(0, 18)}…</small></td>
                    <td>
                      {image.approval_status === "APPROVED"
                        ? <StatusBadge tone="good">已批准</StatusBadge>
                        : <Button size="sm" variant="primary" onClick={() => setImageTarget(image)}>审批</Button>}
                    </td>
                    <td>{image.scanned_at ?? "—"}</td>
                    <td className="subtle">—</td>
                  </tr>
                ))}
                {adapterRows.map((adapter) => (
                  <tr key={adapter.public_id}>
                    <td><strong>{adapter.name}</strong><small style={{ display: "block" }}>{adapter.driver}</small></td>
                    <td><small>{adapter.code}</small></td>
                    <td>
                      <StatusBadge tone={adapter.health_status === "HEALTHY" ? "good" : "warn"}>
                        {adapter.health_status === "HEALTHY" ? "在线" : adapter.health_status}
                      </StatusBadge>
                    </td>
                    <td>{adapter.last_health_at ?? "—"}</td>
                    <td>{sessionTotal ? `${sessionTotal} 会话` : "—"}</td>
                  </tr>
                ))}
                {profileRows.map((profile) => (
                  <tr key={profile.public_id}>
                    <td><strong>{profile.name}</strong><small style={{ display: "block" }}>CPU {profile.cpu_millicores} m · {profile.memory_mb} MB</small></td>
                    <td><small>{profile.code}</small></td>
                    <td><StatusBadge tone={profile.status === "ACTIVE" ? "good" : "neutral"}>{profile.status}</StatusBadge></td>
                    <td className="subtle">—</td>
                    <td className="subtle">—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>

      <ConfirmDialog
        open={imageTarget != null}
        onClose={() => setImageTarget(null)}
        onConfirm={() => { if (imageTarget) decideImage.mutate({ target: imageTarget, decision: "approve" }); }}
        title="批准镜像？"
        eyebrow="镜像治理"
        busy={decideImage.isPending}
        confirmLabel="批准"
        description={<p>批准后教师可将其纳入模板版本；拒绝操作可在列表页对同一镜像重新执行。</p>}
      />
    </>
  );
}

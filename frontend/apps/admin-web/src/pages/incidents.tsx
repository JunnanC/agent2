import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { platformApi } from "@edu/api-client";
import type { Anomaly, Compensation } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { ApiError } from "@edu/auth-client";
import {
  Breadcrumbs, Button, Drawer, EmptyState, Metric, Modal, Panel, RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import { apiErrorMessage } from "@/lib/format";
import { exportCsv } from "@/lib/csv";

const KIND_LABEL: Record<string, string> = {
  task: "实验任务异常",
  "report-scan": "报告扫描",
  precheck: "模板预检",
  instance: "实例异常",
};

const LEVEL_LABEL: Record<string, string> = {
  HIGH: "高",
  MEDIUM: "中",
  LOW: "低",
  INFO: "低",
};

export function Incidents() {
  const toast = useToast();
  const [range, setRange] = useState("7");

  const taskAnomalies = useQuery({ queryKey: keys.anomalies({ page_size: 100 }), queryFn: () => platformApi.anomalies({ page_size: 100 }) });
  const scanAnomalies = useQuery({ queryKey: keys.scanAnomalies({ page_size: 50 }), queryFn: () => platformApi.scanAnomalies({ page_size: 50 }) });

  const rows = useMemo(() => [
    ...(taskAnomalies.data?.rows ?? []),
    ...(scanAnomalies.data?.rows ?? []),
  ].sort((a: Anomaly, b: Anomaly) => String(b.occurred_at ?? "").localeCompare(String(a.occurred_at ?? ""))), [taskAnomalies.data, scanAnomalies.data]);

  const filtered = useMemo(() => {
    if (range === "all") return rows;
    const days = Number(range);
    const cutoff = Date.now() - days * 86_400_000;
    return rows.filter((row) => !row.occurred_at || new Date(row.occurred_at).getTime() >= cutoff);
  }, [rows, range]);

  const pending = filtered.filter((row) => !["RESOLVED", "CLOSED"].includes(row.status));
  const highPriority = filtered.filter((row) => row.level === "HIGH");
  const resolvedToday = filtered.filter((row) => {
    if (!["RESOLVED", "CLOSED"].includes(row.status) || !row.occurred_at) return false;
    return new Date(row.occurred_at).getTime() >= Date.now() - 86_400_000;
  }).length;

  const [search, setSearch] = useState("");
  const [detailRow, setDetailRow] = useState<Anomaly | null>(null);
  const [retryTarget, setRetryTarget] = useState<Compensation | null>(null);
  const [retryReason, setRetryReason] = useState("");
  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return filtered.filter((row) => !query
      || `${row.target_ref} ${row.message} ${row.trace_id ?? ""}`.toLowerCase().includes(query));
  }, [filtered, search]);

  const compensations = useQuery({
    queryKey: [...keys.anomalies({ scope: "compensations" }), "failed"],
    queryFn: () => platformApi.compensations({ status: "" }),
    refetchInterval: 8000,
  });
  const retryable = (compensations.data?.rows ?? []).filter(
    (row: Compensation) => !["DONE", "RETRYING"].includes(row.status),
  );

  const retryMutation = useMutation({
    mutationFn: (target: Compensation) =>
      platformApi.retryCompensation(target.public_id, { reason: retryReason.trim() }, target.row_version),
    onSuccess: () => {
      toast.notify("补偿重试已进队列");
      setRetryTarget(null);
      setRetryReason("");
      void compensations.refetch();
    },
    onError: (error) => toast.notify(error instanceof ApiError ? apiErrorMessage(error) : apiErrorMessage(error), "error"),
  });

  const exportList = () => {
    exportCsv(`处理清单-${new Date().toISOString().slice(0, 10)}.csv`, [
      ["类型", "对象", "级别", "发生时间", "负责人", "状态", "说明", "Trace ID"],
      ...visible.map((row) => [
        KIND_LABEL[row.kind] ?? row.kind,
        row.target_ref,
        LEVEL_LABEL[row.level] ?? row.level,
        row.occurred_at ?? "",
        row.assignee ?? "未分配",
        row.status,
        row.message,
        row.trace_id ?? "",
      ]),
    ]);
    toast.notify("处理清单已导出");
  };

  return (
    <>
      <Breadcrumbs items={[{ label: "平台管理" }]} current="异常中心" />
      <div className="page-actions align-end">
        <select className="field" style={{ width: 110 }} aria-label="时间范围" value={range}
          onChange={(event) => setRange(event.target.value)}>
          <option value="7">近 7 天</option>
          <option value="30">近 30 天</option>
          <option value="all">全部</option>
        </select>
        <Button variant="primary" onClick={exportList}>导出处理清单</Button>
      </div>

      <Panel className="section">
        <RequestStateView loading={taskAnomalies.isLoading && scanAnomalies.isLoading}
          error={taskAnomalies.error ?? scanAnomalies.error}
          onRetry={() => { void taskAnomalies.refetch(); void scanAnomalies.refetch(); }}
          empty={false} emptyState={null}>
          <div className="metric-strip">
            <Metric label="待处理" value={String(pending.length)} icon="alert-triangle" sub="跨任务与资源" />
            <Metric label="高优先级" value={String(highPriority.length)} icon="alert-triangle" sub="需要快速响应" />
            <Metric label="待补偿" value={String(pending.filter((row) => row.kind === "task").length)} icon="refresh" sub="失败作业" />
            <Metric label="已闭环" value={String(resolvedToday)} icon="circle-check" sub="近 24 小时" />
          </div>
        </RequestStateView>
      </Panel>

      <Panel title={<><h2>异常队列</h2><span className="subtle">{visible.length} 条记录</span></>}
        actions={(
          <input className="field" style={{ width: 240 }} type="search" placeholder="搜索任务、Trace 或资源"
            aria-label="搜索异常" value={search} onChange={(event) => setSearch(event.target.value)} />
        )}>
        <RequestStateView
          loading={taskAnomalies.isLoading || scanAnomalies.isLoading}
          error={taskAnomalies.error ?? scanAnomalies.error}
          onRetry={() => { void taskAnomalies.refetch(); void scanAnomalies.refetch(); }}
          empty={!visible.length}
          emptyState={<EmptyState title="暂无异常记录" hint="当前筛选范围内平台运行平稳。" />}
        >
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>类型</th><th>对象</th><th>级别</th><th>发生时间</th><th>负责人</th><th>处理</th></tr></thead>
              <tbody>
                {visible.map((row) => (
                  <tr key={row.public_id}>
                    <td><strong>{KIND_LABEL[row.kind] ?? row.kind}</strong></td>
                    <td data-wrap>{row.target_ref}</td>
                    <td>
                      <StatusBadge tone={row.level === "HIGH" ? "bad" : row.level === "MEDIUM" ? "warn" : "neutral"}>
                        {LEVEL_LABEL[row.level] ?? row.level}
                      </StatusBadge>
                    </td>
                    <td>{row.occurred_at ?? "—"}</td>
                    <td>{row.assignee ?? "待分派"}</td>
                    <td className="table-actions">
                      <Button size="sm" onClick={() => setDetailRow(row)}>查看详情</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>

      <Drawer open={detailRow != null} onClose={() => setDetailRow(null)}
        title={detailRow ? `异常详情 · ${KIND_LABEL[detailRow.kind] ?? detailRow.kind}` : "异常详情"}>
        {detailRow ? (
          <div style={{ display: "grid", gap: 10 }}>
            <div className="status-line"><strong>对象：</strong>{detailRow.target_ref}</div>
            <div className="status-line"><strong>状态：</strong>{detailRow.status}</div>
            <div className="status-line"><strong>说明：</strong>{detailRow.message}</div>
            {detailRow.code ? <div className="status-line"><strong>错误码：</strong>{detailRow.code}</div> : null}
            {detailRow.trace_id ? <div className="status-line"><strong>Trace：</strong>{detailRow.trace_id}</div> : null}
            <div className="status-line"><strong>发生时间：</strong>{detailRow.occurred_at ?? "—"}</div>
            {detailRow.payload && Object.keys(detailRow.payload as Record<string, unknown>).length ? (
              <>
                <strong>Payload</strong>
                <div className="report-submission-copy" style={{ whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(detailRow.payload, null, 2)}
                </div>
              </>
            ) : null}
          </div>
        ) : null}
      </Drawer>

      <div className="grid two section">
        <Panel title={<><h2>补偿作业</h2>
          <span className={`status ${retryable.length ? "warn" : "neutral"}`}>
            {retryable.length} 个待重试
          </span>
        </>}>
          {compensations.isLoading && !compensations.data ? (
            <p className="subtle">载入补偿队列…</p>
          ) : retryable.length ? (
            retryable.slice(0, 8).map((row: Compensation) => (
              <div className="status-line" key={row.public_id} style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span style={{ flex: 1 }}>
                  <strong>{row.task_type}</strong>
                  <small style={{ display: "block" }}>
                    {row.subject_type} #{row.subject_ref} · 尝试 {row.attempt_count}/{row.max_attempts}
                    {row.error_code ? ` · ${row.error_code}` : ""}
                  </small>
                </span>
                <Button size="sm" onClick={() => { setRetryTarget(row); setRetryReason(""); }}>重试</Button>
              </div>
            ))
          ) : (
            <p className="subtle" style={{ margin: 0 }}>补偿队列为空;归档回收、实例销毁失败会进入这里,可手工重试。</p>
          )}
        </Panel>
        <Panel title={<><h2>安全与审计</h2>
          <span className={`status ${highPriority.length ? "warn" : "good"}`}>{highPriority.length ? "存在高风险" : "无高风险"}</span>
        </>}>
          <div className="section">
            <p className="subtle" style={{ margin: 0 }}>
              {highPriority.length
                ? `当前范围 ${highPriority.length} 条 HIGH 级异常待响应,请在上表处理。`
                : "当前没有需要升级的安全告警；安全策略与网络白名单的明细在审计日志中留痕。"}
            </p>
          </div>
        </Panel>
      </div>

      <Modal open={retryTarget != null} onClose={() => setRetryTarget(null)} eyebrow="补偿作业" title="发起补偿重试"
        actions={(
          <>
            <Button onClick={() => setRetryTarget(null)}>取消</Button>
            <Button variant="primary" disabled={!retryReason.trim() || retryMutation.isPending}
              onClick={() => retryTarget && retryMutation.mutate(retryTarget)}>
              {retryMutation.isPending ? "提交中…" : "确认重试"}
            </Button>
          </>
        )}>
        {retryTarget ? (
          <div style={{ display: "grid", gap: 10 }}>
            <p className="subtle" style={{ margin: 0 }}>
              目标:{retryTarget.task_type} · {retryTarget.subject_type} #{retryTarget.subject_ref}(已尝试 {retryTarget.attempt_count}/{retryTarget.max_attempts})
            </p>
            <label className="form-label" htmlFor="retry-reason">重试原因 <span>必填</span></label>
            <textarea id="retry-reason" className="field" rows={3} value={retryReason}
              onChange={(event) => setRetryReason(event.target.value)} placeholder="记录本次手工重试的原因,写入审计日志" />
          </div>
        ) : null}
      </Modal>
    </>
  );
}

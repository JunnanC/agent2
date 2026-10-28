import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { platformApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  Breadcrumbs, EmptyState, Panel, RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import type { OperationLog } from "@edu/api-client";
import { exportCsv } from "@/lib/csv";
import { Button } from "@edu/ui";

const RESULT_LABEL: Record<string, { label: string; tone: "good" | "warn" | "neutral" }> = {
  SUCCESS: { label: "成功", tone: "good" },
  NEED_REVIEW: { label: "需复核", tone: "warn" },
  FAILED: { label: "失败", tone: "neutral" },
};

export function Audit() {
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [range, setRange] = useState("7");
  const logs = useQuery({ queryKey: keys.operationLogs({}), queryFn: () => platformApi.operationLogs({ page_size: 50 }) });

  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    const cutoff = range === "all" ? 0 : Date.now() - Number(range) * 86_400_000;
    return (logs.data?.rows ?? []).filter((row: OperationLog) => {
      const withinRange = !cutoff || !row.occurred_at || new Date(row.occurred_at).getTime() >= cutoff;
      const matches = !query
        || `${row.action} ${row.target} ${row.actor_name ?? ""} ${row.trace_id ?? ""}`.toLowerCase().includes(query);
      return withinRange && matches;
    });
  }, [logs.data, search, range]);

  const exportLogs = () => {
    exportCsv(`操作日志-${new Date().toISOString().slice(0, 10)}.csv`, [
      ["时间", "操作者", "动作", "对象", "结果", "Trace ID"],
      ...rows.map((row) => [
        row.occurred_at ?? "",
        row.actor_name ?? row.actor ?? "系统",
        row.action,
        row.target,
        RESULT_LABEL[row.result]?.label ?? row.result,
        row.trace_id ?? "",
      ]),
    ]);
    toast.notify("日志已导出");
  };

  return (
    <>
      <Breadcrumbs items={[{ label: "平台管理" }]} current="异常与审计" />
      <div className="page-actions align-end">
        <select className="field" style={{ width: 110 }} aria-label="时间范围" value={range}
          onChange={(event) => setRange(event.target.value)}>
          <option value="3">近 3 天</option>
          <option value="7">近 7 天</option>
          <option value="30">近 30 天</option>
          <option value="all">全部</option>
        </select>
        <Button onClick={exportLogs}>导出日志</Button>
      </div>

      <Panel title={<><h2>操作日志</h2><span className="subtle">{rows.length} 条记录</span></>}
        actions={(
          <input className="field" style={{ width: 240 }} type="search" placeholder="搜索操作、用户或资源" aria-label="搜索日志"
            value={search} onChange={(event) => setSearch(event.target.value)} />
        )}>
        <RequestStateView
          loading={logs.isLoading}
          error={logs.error}
          onRetry={() => void logs.refetch()}
          empty={!rows.length}
          emptyState={<EmptyState title="暂无操作日志" hint="当前时间范围内没有平台关键操作。" />}
        >
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>对象</th><th>结果</th></tr></thead>
              <tbody>
                {rows.map((row: OperationLog) => {
                  const result = RESULT_LABEL[row.result] ?? { label: row.result, tone: "neutral" as const };
                  return (
                    <tr key={row.id}>
                      <td>{row.occurred_at}</td>
                      <td><strong>{row.actor_name ?? row.actor ?? "系统"}</strong></td>
                      <td>{row.action}</td>
                      <td data-wrap>{row.target}</td>
                      <td>
                        <StatusBadge tone={result.tone}>{result.label}</StatusBadge>
                        {row.trace_id ? <small style={{ display: "block", color: "var(--muted)" }}>Trace {row.trace_id}</small> : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>
    </>
  );
}

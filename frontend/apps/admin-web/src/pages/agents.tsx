import { useQuery } from "@tanstack/react-query";
import { platformApi } from "@edu/api-client";
import type { ModelRoute, ToolPolicy, UsageCost } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { EmptyState, Metric,  Panel, RequestStateView, StatusBadge } from "@edu/ui";

export function Agents() {
  const routes = useQuery({ queryKey: keys.agentModelRoutes(), queryFn: () => platformApi.agentModelRoutes() });
  const policies = useQuery({ queryKey: keys.agentToolPolicies(), queryFn: () => platformApi.agentToolPolicies() });
  const costs = useQuery({ queryKey: keys.agentUsageCosts({ window: "month" }), queryFn: () => platformApi.agentUsageCosts({ window: "month" }) });

  const routeRows = (routes.data?.rows ?? []) as ModelRoute[];
  const policyRows = (policies.data?.rows ?? []) as ToolPolicy[];
  const costRows = (costs.data?.rows ?? []) as UsageCost[];
  const totalCostMinor = costRows.reduce((sum, row) => sum + (row.cost_minor ?? 0), 0);

  return (
    <>
      
      <RequestStateView loading={routes.isLoading && costs.isLoading}
        error={routes.error ?? costs.error}
        onRetry={() => { void routes.refetch(); void costs.refetch(); }}
        empty={false} emptyState={null}>
        <div className="metric-group" style={{ marginBottom: 15 }}>
          <Metric label="模型路由" value={String(routeRows.length)} icon="box" sub="生效配置" />
          <Metric label="工具策略" value={String(policyRows.length)} icon="shield" sub="ALLOW / ASK / DENY" />
          <Metric label="本月成本" value={(totalCostMinor / 100).toFixed(2)} icon="chart" sub={costRows[0]?.currency_code ?? "USD"} />
        </div>
      </RequestStateView>
      <div className="grid two">
        <Panel title={<h2>模型路由</h2>}>
          <RequestStateView loading={routes.isLoading} error={routes.error}
            onRetry={() => void routes.refetch()}
            empty={!routeRows.length}
            emptyState={<EmptyState title="暂无模型路由" />}>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>路由</th><th>模型</th><th>状态</th></tr></thead>
                <tbody>
                  {routeRows.map((row) => (
                    <tr key={row.public_id}>
                      <td><strong>{row.name ?? row.scope}</strong><small style={{ display: "block" }}>{row.scope}</small></td>
                      <td>{row.model}</td>
                      <td><StatusBadge tone="good">{row.status ?? "生效"}</StatusBadge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </RequestStateView>
        </Panel>
        <Panel title={<h2>工具策略</h2>}>
          <RequestStateView loading={policies.isLoading} error={policies.error}
            onRetry={() => void policies.refetch()}
            empty={!policyRows.length}
            emptyState={<EmptyState title="暂无工具策略" />}>
            <div>
              {policyRows.map((policy) => (
                <div className="item" key={policy.public_id}>
                  <div><strong>{policy.name}</strong><small>{policy.tools.map((tool) => `${tool.key}:${tool.mode}`).join(" · ")}</small></div>
                </div>
              ))}
            </div>
          </RequestStateView>
        </Panel>
      </div>
      <Panel className="section" title={<h2>使用成本</h2>}>
        <RequestStateView loading={costs.isLoading} error={costs.error}
          onRetry={() => void costs.refetch()}
          empty={!costRows.length}
          emptyState={<EmptyState title="暂无使用成本数据" />}>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>范围</th><th>令牌（入）</th><th>令牌（出）</th><th>成本</th></tr></thead>
              <tbody>
                {costRows.map((row, index) => (
                  <tr key={index}>
                    <td>{row.course ?? row.scope ?? "全局"}</td>
                    <td>{row.tokens_in ?? "—"}</td>
                    <td>{row.tokens_out ?? "—"}</td>
                    <td>{((row.cost_minor ?? 0) / 100).toFixed(2)} {row.currency_code}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>
    </>
  );
}

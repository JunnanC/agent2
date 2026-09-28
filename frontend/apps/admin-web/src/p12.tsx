import { useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ApiError, RequestIntent, apiRequestWithMetadata } from '@edu/api-client'
import { agentKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge, TextField } from '@edu/ui'

type RecordData = {
  public_id: string
  key: string
  version_no: number
  provider: string
  model_name: string
  regions?: string[]
  status: string
  max_tokens?: number
  tool_name: string
  risk: string
  timeout_seconds: number
  output_limit: number
  name?: string
  case_count?: number
  platform_managed?: boolean
  [key: string]: unknown
}
function message(error: unknown) { return error instanceof ApiError ? `${error.payload.error.message}（trace: ${error.traceId || 'n/a'}）` : '平台 Agent 请求未完成。' }
function useList<T>(path: string, key: readonly unknown[]) { return useQuery({ queryKey: key, queryFn: () => apiRequestWithMetadata<{ data: T[] }>(path) }) }

export function PlatformAgentPage() {
  const [error, setError] = useState(''); const [notice, setNotice] = useState('')
  const [policyForm, setPolicyForm] = useState(false); const [routeForm, setRouteForm] = useState(false)
  const policies = useList<RecordData>('/api/v2/platform/agent/tool-policies', agentKeys.platformPolicies())
  const routes = useList<RecordData>('/api/v2/platform/agent/model-routes', [...agentKeys.all, 'platform', 'routes'])
  const suites = useList<RecordData>('/api/v2/platform/agent/eval-suites', [...agentKeys.all, 'platform', 'eval-suites'])
  const usage = useQuery({ queryKey: [...agentKeys.all, 'platform', 'usage'], queryFn: () => apiRequestWithMetadata<RecordData>('/api/v2/platform/agent/usage-costs') })

  const createPolicy = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); const form = new FormData(event.currentTarget)
    try { await apiRequestWithMetadata('/api/v2/platform/agent/tool-policies', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: form.get('key'), tool_name: form.get('tool_name'), risk: form.get('risk'), timeout_seconds: Number(form.get('timeout_seconds')), output_limit: Number(form.get('output_limit')), allowlist: [String(form.get('tool_name'))] }), intent: new RequestIntent() }); setNotice('平台工具策略已创建新版本。'); setPolicyForm(false); await policies.refetch() } catch (cause) { setError(message(cause)) }
  }
  const createRoute = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); const form = new FormData(event.currentTarget)
    try { await apiRequestWithMetadata('/api/v2/platform/agent/model-routes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: form.get('key'), provider: form.get('provider'), model_name: form.get('model_name'), regions: ['LOCAL'], max_tokens: Number(form.get('max_tokens')), timeout_seconds: Number(form.get('timeout_seconds')) }), intent: new RequestIntent() }); setNotice('批准模型路由已登记。'); setRouteForm(false); await routes.refetch() } catch (cause) { setError(message(cause)) }
  }
  const createSuite = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); const form = new FormData(event.currentTarget)
    try { await apiRequestWithMetadata('/api/v2/platform/agent/eval-suites', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.get('name'), threshold: { minimum_score: Number(form.get('minimum_score') || 1) } }), intent: new RequestIntent() }); setNotice('平台强制评测套件已创建。'); await suites.refetch(); event.currentTarget.reset() } catch (cause) { setError(message(cause)) }
  }
  if (policies.isPending || routes.isPending || suites.isPending) return <RequestStateView state="loading" />
  if (policies.isError) return <RequestStateView state="error" message={message(policies.error)} onRetry={() => void policies.refetch()} />
  const policyValues = policies.data?.payload.data ?? []; const routeValues = routes.data?.payload.data ?? []; const suiteValues = suites.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="PLATFORM / AGENTS" title="Agent 策略、路由与评测" description="管理端展示治理事实和聚合指标，敏感上下文按最小权限隐藏。" actions={<div className="toolbar"><button className="text-button" onClick={() => setRouteForm((value) => !value)}>新增路由</button><button className="text-button" onClick={() => setPolicyForm((value) => !value)}>新增工具策略</button></div>} />{notice ? <p className="notice" role="status">{notice}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}
    {routeForm ? <section className="section-block"><h2>批准模型路由</h2><form className="form-grid" onSubmit={(event) => void createRoute(event)}><TextField label="路由 key" name="key" required /><TextField label="Provider" name="provider" defaultValue="LOCAL" required /><TextField label="模型名" name="model_name" defaultValue="rule-based" required /><TextField label="最大 token" name="max_tokens" type="number" defaultValue="4096" /><TextField label="超时秒数" name="timeout_seconds" type="number" defaultValue="5" /><button className="primary-button" type="submit">保存路由</button></form></section> : null}
    {policyForm ? <section className="section-block"><h2>工具策略版本</h2><form className="form-grid" onSubmit={(event) => void createPolicy(event)}><TextField label="策略 key" name="key" required /><TextField label="工具名称" name="tool_name" required /><label className="field"><span>风险等级</span><select name="risk" defaultValue="LOW"><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>FORBIDDEN</option></select></label><TextField label="超时秒数" name="timeout_seconds" type="number" defaultValue="30" /><TextField label="输出上限" name="output_limit" type="number" defaultValue="8192" /><button className="primary-button" type="submit">保存策略</button></form></section> : null}
    <section className="section-block"><h2>模型路由与 fallback</h2><div className="data-table-wrap"><table className="data-table"><thead><tr><th>路由</th><th>Provider/模型</th><th>区域</th><th>状态</th><th>token 上限</th></tr></thead><tbody>{routeValues.map((item) => <tr key={item.public_id}><td>{item.key} · v{item.version_no}</td><td>{item.provider} / {item.model_name}</td><td>{(item.regions ?? []).join(', ')}</td><td><StatusBadge status={item.status} /></td><td>{item.max_tokens}</td></tr>)}</tbody></table></div>{routeValues.length === 0 ? <RequestStateView state="empty" /> : null}</section>
    <section className="section-block"><h2>工具策略</h2><div className="data-table-wrap"><table className="data-table"><thead><tr><th>工具</th><th>风险</th><th>状态</th><th>超时/输出</th></tr></thead><tbody>{policyValues.map((item) => <tr key={item.public_id}><td>{item.tool_name} · v{item.version_no}</td><td><StatusBadge status={item.risk} /></td><td><StatusBadge status={item.status} /></td><td>{item.timeout_seconds}s / {item.output_limit}</td></tr>)}</tbody></table></div>{policyValues.length === 0 ? <RequestStateView state="empty" /> : null}</section>
    <section className="section-block"><h2>平台强制评测</h2><form className="form-grid" onSubmit={(event) => void createSuite(event)}><TextField label="套件名称" name="name" required /><TextField label="最低分" name="minimum_score" type="number" step="0.01" defaultValue="1" /><button className="text-button" type="submit">创建套件</button></form>{suiteValues.length ? <ul>{suiteValues.map((item) => <li key={item.public_id}>{item.name} · {item.case_count ?? 0} 题 · {item.platform_managed ? '强制' : '课程'}</li>)}</ul> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>调用与成本聚合</h2>{usage.isPending ? <RequestStateView state="loading" /> : usage.isError ? <RequestStateView state="error" onRetry={() => void usage.refetch()} /> : <pre className="summary-item">{JSON.stringify(usage.data?.payload.data ?? {}, null, 2)}</pre>}</section>
  </section>
}

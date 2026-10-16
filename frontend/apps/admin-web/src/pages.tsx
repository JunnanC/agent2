import { useState } from 'react';
import { auditRows, governanceRows, imageRows, incidentRows, instanceRows, profileRows, type Page } from './data';
import { Badge, DataTable, Metrics, Panel, type Detail } from './components';

export function Overview({ navigate }: { navigate: (page: Page) => void }) {
  const items = [
    { label: '活跃工作区', value: '128', foot: '124 正常 · 4 个需关注', onClick: () => navigate('resources') },
    { label: 'CPU 配额使用', value: '62%', foot: '总量 32 vCPU · 近 24 小时', onClick: () => navigate('resources') },
    { label: '内存配额使用', value: '71%', foot: '可用 42 GB · 近 24 小时', onClick: () => navigate('resources') },
    { label: '待处理事项', value: String(governanceRows.length).padStart(2, '0'), foot: '2 项高优先级 · 等待处理', onClick: () => navigate('governance') },
  ];
  const queue: [string, string, string, Page][] = [
    ['教师资格审核', '12 位申请人 · 最早 2 天前', '高', 'governance'],
    ['镜像扫描复核', '3 个镜像等待复核', '中', 'resources'],
    ['运行时容量告警', '集群 B · CPU 余量偏低', '高', 'resources'],
    ['实验任务异常', '2 项等待分派', '低', 'incidents'],
  ];
  return <>
    <Metrics items={items} />
    <div className="columns section">
      <Panel title="资源使用趋势" extra={<div className="legend"><span><i />CPU</span><span><i className="blue" />内存</span></div>}>
        <div className="panel-body"><div className="trend" role="img" aria-label="演示趋势：CPU 使用率约为 30% 至 66%，内存使用率约为 42% 至 71%">
          <div className="chart-grid"><span /><span /><span /><span /></div>
          {[[30,44],[35,42],[41,47],[38,49],[48,53],[55,52],[51,57],[62,59],[58,63],[66,68],[62,71],[59,65]].map(([cpu, memory], index) => <span key={index} className="bar-group" title={`${index * 2}:00 CPU ${cpu}% / 内存 ${memory}%`}><i className="bar" style={{ height: `${cpu}%` }} /><i className="bar secondary" style={{ height: `${memory}%` }} /><em>{index % 3 === 0 ? String(index * 2).padStart(2, '0') : ''}</em></span>)}
        </div></div>
      </Panel>
      <Panel title="待处理治理事项" extra={<button className="row-action" onClick={() => navigate('governance')}>查看全部 →</button>}>
        <div className="panel-body queue">{queue.map(([title, meta, priority, page]) => <div className="queue-row" key={title}><div><div className="queue-title">{title}</div><div className="queue-meta">{meta}</div></div><button className="row-action" onClick={() => navigate(page)} aria-label={`查看${title}`}><Badge value={priority} /></button></div>)}</div>
      </Panel>
    </div>
    <section className="section"><div className="section-title"><h2>平台服务健康</h2><small>最后更新 14:32 · 数据为界面演示</small></div><div className="health-list">{[['API 服务', '响应正常 · p95 142 ms'], ['数据存储', '连接池运行正常'], ['运行时集群 B', '容量偏低 · 建议检查配额']].map(([title, description], index) => <div className="health" key={title}><div className="health-top"><i className={`health-dot ${index === 2 ? 'warn' : ''}`} />{title}</div><p>{description}</p></div>)}</div></section>
  </>;
}

export function Governance({ onDetail }: { onDetail: (detail: Detail) => void }) {
  return <>
    <Metrics items={[
      { label: '待处理事项', value: String(governanceRows.length).padStart(2, '0'), foot: '4 类治理队列' },
      { label: '高优先级', value: '02', foot: '需要尽快响应' },
      { label: '平均等待', value: '6.4h', foot: '按待处理事项计算' },
      { label: '今日已完成', value: '14', foot: '较昨日 +3' },
    ]} />
    <div className="section"><DataTable headers={['事项', '治理范围', '优先级', '等待时间', '负责人']} rows={governanceRows} statuses={['高', '中', '低']} badgeColumns={[2]} onDetail={onDetail} /></div>
  </>;
}

export function Resources({ onDetail }: { onDetail: (detail: Detail) => void }) {
  const [tab, setTab] = useState('runtime');
  const tabs = [['runtime', '运行时与配额'], ['images', '镜像治理'], ['instances', '实例与会话']];
  return <>
    <Metrics items={[
      { label: '运行中实例', value: '62', foot: '当前占用 71%' },
      { label: '已治理镜像', value: '18', foot: '扫描状态已通过' },
      { label: '配额预警', value: '04', foot: '2 项高风险' },
      { label: '活跃工作区会话', value: '84', foot: '最近 24 小时' },
    ]} />
    <section className="section"><div className="tabs" role="tablist" aria-label="资源分类">{tabs.map(([key, title], index) => <button key={key} id={`tab-${key}`} role="tab" aria-selected={tab === key} aria-controls="resource-panel" tabIndex={tab === key ? 0 : -1} className={tab === key ? 'active' : ''} onClick={() => setTab(key)} onKeyDown={event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      setTab(tabs[next][0]);
      document.getElementById(`tab-${tabs[next][0]}`)?.focus();
    }}>{title}</button>)}</div>
      <div id="resource-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === 'runtime' ? <>
          <div className="columns">
            <Panel title="运行时健康" extra={<span className="pill green">2 正常 · 1 需关注</span>}><div className="panel-body">{[['Docker Sandbox · v3', '健康率 99.8%', '健康'], ['Notebook Runtime · v2', '健康率 99.4%', '健康'], ['Judge Worker · v1', '队列占用 72%', '需关注']].map(([title, meta, status]) => <div className="resource-row" key={title}><div><div className="queue-title">{title}</div><div className="queue-meta">{meta}</div></div><Badge value={status} /></div>)}</div></Panel>
            <Panel title="配额使用" extra={<span className="muted">本学期</span>}><div className="panel-body">{[['CPU', 71], ['内存', 58], ['对象存储', 43]].map(([label, value]) => <div className="progress-row" key={label}><span>{label}</span><div className={`track ${Number(value) > 70 ? 'amber' : ''}`}><span style={{ width: `${value}%` }} /></div><strong>{value}%</strong></div>)}</div></Panel>
          </div>
          <section className="section"><div className="section-title"><h2>资源规格</h2><small>状态及操作由服务端权限决定</small></div><DataTable headers={['规格', 'CPU', '内存', '当前使用', '状态']} rows={profileRows} badgeColumns={[4]} onDetail={onDetail} /></section>
        </> : tab === 'images' ? <DataTable key="images" headers={['镜像', '版本 / Digest', '扫描状态', '治理状态', '最近检查']} rows={imageRows} badgeColumns={[2, 3]} onDetail={onDetail} /> : <DataTable key="instances" headers={['实例', '关联任务', '运行状态', '资源规格', '最近活动']} rows={instanceRows} badgeColumns={[2]} onDetail={onDetail} />}
      </div>
    </section>
  </>;
}

export function Incidents({ onDetail }: { onDetail: (detail: Detail) => void }) {
  return <>
    <Metrics items={[
      { label: '待处理异常', value: '07', foot: '跨任务与资源' },
      { label: '高优先级', value: '02', foot: '建议立即排查' },
      { label: '待运行补偿', value: '03', foot: '操作前需复核影响' },
      { label: '今日已解决', value: '14', foot: '近 24 小时' },
    ]} />
    <div className="section"><DataTable headers={['异常类型', '关联对象', '优先级', '发生时间', '状态', 'Trace ID']} rows={incidentRows} statuses={['待处理', '处理中', '待复核']} badgeColumns={[2, 4]} timeFilter onDetail={onDetail} /></div>
    <Panel title="补偿任务" extra={<span className="pill amber">3 个待复核</span>} className="section"><div className="panel-body split"><div><div className="queue-title">实例回收失败</div><div className="queue-meta">资源回收 · comp_01M8F2 · 最近重试 10:26</div></div><div><div className="queue-title">报告扫描超时</div><div className="queue-meta">文件扫描 · comp_01M8D9 · 等待人工复核</div></div></div></Panel>
  </>;
}

export function Audit({ onDetail }: { onDetail: (detail: Detail) => void }) {
  return <>
    <DataTable headers={['时间', '操作者', '动作', '对象', '结果', 'Trace ID']} rows={auditRows} statuses={['成功', '需复核', '失败']} badgeColumns={[4]} timeFilter exportable onDetail={onDetail} />
    <div className="section-title section"><h2>审计查询说明</h2><small>演示记录的日期基准为 2026-10-15</small></div><div className="health-list">{[['操作范围', '筛选管理员、资源对象、操作结果和时间范围。'], ['Trace 关联', '通过 Trace ID 关联请求与必要的运行记录。'], ['数据保护', '不在界面或日志中展示密钥、Cookie 和完整文件内容。']].map(([title, description]) => <div className="health" key={title}><div className="health-top">{title}</div><p>{description}</p></div>)}</div>
  </>;
}

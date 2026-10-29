import { useEffect, useRef, useState, type ReactNode } from 'react';
import { filterRows, toCsv, type RecordRow } from './data';

export function Badge({ value }: { value: string }) {
  const green = ['成功', '健康', '启用', '扫描通过', '已批准'];
  const red = ['高', '待处理', '失败', '扫描失败', '回收失败', '已阻止'];
  const blue = ['低', '处理中', '运行中'];
  const tone = green.includes(value) ? 'green' : red.includes(value) ? 'red' : blue.includes(value) ? 'blue' : value === '空闲' ? 'gray' : 'amber';
  return <span className={`pill ${tone}`}>{value}</span>;
}

export function Panel({ title, extra, children, className = '' }: { title: string; extra?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}><div className="panel-head"><h2>{title}</h2>{extra}</div>{children}</section>;
}

export type Metric = { label: string; value: string; foot: string; onClick?: () => void };
export function Metrics({ items }: { items: Metric[] }) {
  return <div className="metrics">{items.map(item => {
    const content = <><span className="metric-label">{item.label}</span><span className="metric-value">{item.value}</span><span className="metric-foot">{item.foot}</span></>;
    return item.onClick ? <button className="metric" key={item.label} onClick={item.onClick}>{content}</button> : <div className="metric" key={item.label}>{content}</div>;
  })}</div>;
}

export type Detail = { title: string; fields: [string, string][] };
export function DataTable({ headers, rows, badgeColumns = [], statuses = [], timeFilter = false, exportable = false, onDetail }: {
  headers: string[]; rows: RecordRow[]; badgeColumns?: number[]; statuses?: string[];
  timeFilter?: boolean; exportable?: boolean; onDetail: (detail: Detail) => void;
}) {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [days, setDays] = useState(7);
  const visible = filterRows(rows, query, status, timeFilter ? days : 0);
  function exportCurrent() {
    const url = URL.createObjectURL(new Blob([toCsv(headers, visible.map(row => row.cells))], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'audit-demo.csv';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="panel">
    <div className="toolbar">
      <input className="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索名称、对象 ID 或 Trace ID" aria-label="搜索记录" />
      {statuses.length > 0 && <select className="select" aria-label="筛选状态" value={status} onChange={event => setStatus(event.target.value)}><option value="all">全部状态</option>{statuses.map(value => <option key={value}>{value}</option>)}</select>}
      {timeFilter && <select className="select" aria-label="筛选时间" value={days} onChange={event => setDays(Number(event.target.value))}><option value={7}>最近 7 天</option><option value={1}>今天</option><option value={30}>最近 30 天</option></select>}
      {exportable && <button className="btn" onClick={exportCurrent}>导出当前记录</button>}
      <span className="toolbar-end" role="status">{visible.length} 条记录 · 演示数据</span>
    </div>
    <div className="table-wrap"><table><thead><tr>{headers.map(header => <th key={header}>{header}</th>)}<th><span className="sr-only">操作</span></th></tr></thead><tbody>
      {visible.map(row => <tr key={row.id}>{row.cells.map((value, index) => <td key={index} className={index === 0 ? 'object-cell' : ''}>{badgeColumns.includes(index) ? <Badge value={value} /> : value}</td>)}<td><button className="row-action" onClick={() => onDetail({ title: row.cells[0] ?? '', fields: [['记录 ID', row.id], ...headers.map((header, index): [string, string] => [header, row.cells[index] ?? ''])] })}>查看详情 →</button></td></tr>)}
      {visible.length === 0 && <tr><td colSpan={headers.length + 1} className="empty-state">没有匹配记录，请调整搜索或筛选条件。</td></tr>}
    </tbody></table></div>
  </section>;
}

export function DetailDrawer({ detail, onClose }: { detail: Detail; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const target = dialog.current!;
    const previous = document.activeElement as HTMLElement | null;
    target.showModal();
    return () => { target.close(); previous?.focus(); };
  }, []);
  return <dialog ref={dialog} className="detail-dialog" aria-labelledby="drawerTitle" onCancel={onClose} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="drawer-content"><div className="drawer-head"><div><h2 id="drawerTitle">{detail.title}</h2><p>平台管理记录 · 演示数据</p></div><button className="icon-button" onClick={onClose} aria-label="关闭详情">×</button></div>
      <div className="drawer-section"><h3>对象信息</h3>{detail.fields.map(([label, value]) => <div className="detail-line" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
      <div className="drawer-section"><h3>处理说明</h3><p className="detail-description">此界面展示演示记录。正式接入后根据服务端权限、允许操作和阻塞原因提供处理入口。</p></div>
      <div className="drawer-actions"><button className="btn" onClick={onClose}>关闭</button></div>
    </div>
  </dialog>;
}

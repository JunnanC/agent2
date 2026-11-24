import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { TeacherScrollFrame } from "./teacher-b";

export interface ExperimentRow {
  id: string;
  title: string;
  deadline: string;
  status: string;
  tone?: "info" | "warn" | "good";
  submitted: string;
  href: string;
  action: string;
}

export function ClassExperiments({ rows, actions, state }: { rows: ExperimentRow[]; actions: ReactNode; state?: ReactNode }) {
  return <section className="panel agenda-panel">
    <div className="panel-head"><div><h2>实验列表</h2></div>{actions}</div>
    {state}
    {rows.length ? <TeacherScrollFrame label="实验列表"><table className="table">
      <thead><tr><th scope="col">实验名称</th><th scope="col">提交截止</th><th scope="col">状态</th>
        <th scope="col" className="num">报告提交</th><th scope="col" className="row-actions">操作</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.id}><td><strong>{row.title}</strong></td><td>{row.deadline}</td>
        <td><span className={`pill ${row.tone ?? ""}`}>{row.status}</span></td><td className="num">{row.submitted}</td>
        <td className="row-actions"><Link className="text-button" to={row.href}>{row.action}</Link></td></tr>)}</tbody>
    </table></TeacherScrollFrame> : !state && <p className="empty">这个教学班还没有实验。</p>}
  </section>;
}

import { useQuery } from "@tanstack/react-query";
import { timetableApi } from "@edu/api-client";
import { ClassTimetable } from "@edu/ui";
import { Link, useSearchParams } from "react-router-dom";
import type { Account } from "./api";

export function TermClasses({ teachers, students }: { teachers: Account[]; students: Account[] }) {
  const [params, setParams] = useSearchParams();
  const term = params.get("term") || undefined;
  const role = params.get("role") || "";
  const person = params.get("person") || "";
  const q = params.get("q") || "";
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "", 10) || 1);
  const query = { term_id: term, role: role || undefined, person_id: person || undefined, q, page };
  const data = useQuery({ queryKey: ["platform-term-classes", query], queryFn: () => timetableApi.platform(query),
    placeholderData: (previous) => previous });
  const update = (changes: Record<string, string>, replace = false) => setParams((current) => {
    const next = new URLSearchParams(current);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    return next;
  }, { replace });
  const people = role === "TEACHER" ? teachers : role === "STUDENT" ? students : [];
  const pages = Math.max(1, Math.ceil((data.data?.total ?? 0) / 20));
  return <section aria-label="教学班学期查询">
    <div className="page-actions">
      <label>角色{" "}<select className="field" value={role} onChange={(event) => update({ role: event.target.value, person: "", page: "" })}>
        <option value="">全部</option><option value="TEACHER">教师</option><option value="STUDENT">学生</option>
      </select></label>
      {role && <label>人员{" "}<select className="field" value={person} onChange={(event) => update({ person: event.target.value, page: "" })}>
        <option value="">请选择</option>
        {people.map((item) => <option key={item.public_id} value={item.public_id}>{item.display_name || item.username} · {item.username}</option>)}
      </select></label>}
      <label>在结果中查找{" "}<input className="field" value={q} placeholder="班名或教务编号" onChange={(event) => update({ q: event.target.value, page: "" }, true)} /></label>
    </div>
    <ClassTimetable title="学期教学班与课表" data={data.data} loading={data.isLoading} error={data.error}
      retry={() => void data.refetch()} onTermChange={(id) => update({ term: id, page: "" })}
      classLink={(id, title) => <Link to={`/students?type=teaching&class=${id}`}>{title} · 查看名单</Link>} />
    <div className="page-actions" aria-label="教学班分页">
      <button type="button" className="btn" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>上一页</button>
      <span>第 {page} / {pages} 页 · 共 {data.data?.total ?? 0} 班</span>
      <button type="button" className="btn" disabled={page >= pages || data.isPlaceholderData} onClick={() => update({ page: String(page + 1) })}>下一页</button>
    </div>
  </section>;
}

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { teachingApi } from "@edu/api-client";
import { Panel, RequestStateView, EmptyState, Modal } from "@edu/ui";
import { allPages } from "@/lib/all-pages";
import { meanGrade } from "@/lib/grades";

export function GradeAnalysis({ courseId }: { courseId: string }) {
  const [publication, setPublication] = useState("");
  const [retake, setRetake] = useState(false);
  const [selectedTasks, setSelectedTasks] = useState<string[]>([]);
  const [studentSearch, setStudentSearch] = useState("");
  const [start, setStart] = useState("");
  const [deadline, setDeadline] = useState("");
  const [requestReady, setRequestReady] = useState(false);
  const data = useQuery({
    queryKey: ["course-grade-analysis", courseId],
    queryFn: async () => {
      const [publications, tasks, reviews] = await Promise.all([
        allPages(page => teachingApi.publications(courseId, { page })),
        allPages(page => teachingApi.progress(courseId, { page, page_size: 100 })),
        allPages(page => teachingApi.reviews(courseId, { page })),
      ]);
      // The list endpoint does not include confirmed scores; read actual decisions.
      const details = [];
      for (let offset = 0; offset < reviews.length; offset += 6) {
        details.push(...await Promise.all(reviews.slice(offset, offset + 6).map(r => teachingApi.review(courseId, r.public_id))));
      }
      return { publications, tasks, reviews: details };
    },
  });
  const tasks = (data.data?.tasks ?? []).filter(t => !publication || t.publication_id === publication);
  const gradeFor = (taskId: string) => {
    const review = data.data?.reviews.filter(r => r.task_id === taskId && r.decision).sort((a,b) => (b.round_no ?? 0) - (a.round_no ?? 0))[0];
    return review?.score != null && Number.isFinite(Number(review.score)) ? Number(review.score) : 0;
  };
  const unfinished = tasks.filter(t => !["COMPLETED", "APPROVED", "CANCELLED", "WITHDRAWN"].includes(t.status ?? ""));
  const candidates = unfinished.filter(t => (t.student_name ?? "").includes(studentSearch.trim()));
  const openRetake = () => { setSelectedTasks([]); setStudentSearch(""); setRequestReady(false); setRetake(true); };
  const average = meanGrade(tasks.map(t => gradeFor(t.public_id ?? "")));
  return <Panel title={<h2>实验成绩与任务</h2>} actions={<select className="field" aria-label="选择成绩统计实验" value={publication} onChange={e => { setPublication(e.target.value); setSelectedTasks([]); setRetake(false); setRequestReady(false); }}><option value="">全部实验</option>{data.data?.publications.map(p => <option key={p.public_id} value={p.public_id}>{p.title}</option>)}</select>}><RequestStateView loading={data.isLoading} error={data.error} onRetry={() => void data.refetch()} empty={!tasks.length} emptyState={<EmptyState title="暂无已分配实验任务" />}><div className="teacher-summary"><div><span>平均成绩</span><strong>{average?.toFixed(2) ?? "—"}</strong></div><div><span>应提交任务</span><strong>{tasks.length}</strong></div><div><span>未提交任务</span><strong>{tasks.filter(t => !["SUBMITTED", "UNDER_REVIEW", "COMPLETED", "APPROVED"].includes(t.status ?? "")).length}</strong></div></div><p className="subtle">按全部已分配任务计算，未提交按 0 分；已提交待教师确认的成绩暂计 0 分。重做成绩关联与去重接口尚未提供，当前汇总仅适用于普通发布。</p><div className="table-wrap"><table className="table"><thead><tr><th>学生</th><th>实验</th><th>任务状态</th><th>已确认成绩</th><th /></tr></thead><tbody>{tasks.map(t => <tr key={t.public_id}><td>{t.student_name ?? "—"}</td><td>{t.title}</td><td>{t.status}</td><td>{gradeFor(t.public_id ?? "")}</td><td><Link to={`/courses/${courseId}/publishing/${t.publication_id}/reviews`}>报告与评分</Link></td></tr>)}</tbody></table></div><button type="button" className="btn" disabled={!publication} onClick={openRetake}>重新发布实验</button></RequestStateView><Modal open={retake} onClose={() => setRetake(false)} title="重新发布实验" wide>
      <p>{data.data?.publications.find(p => p.public_id === publication)?.title}</p>
      <p className="subtle">一次选择多位未完成学生，创建关联原实验的新发布；已提交待评审学生也属于尚未完成，是否参加由教师选择。</p>
      <input className="field" aria-label="搜索重新发布学生" placeholder="搜索学生" value={studentSearch} onChange={e => setStudentSearch(e.target.value)} />
      <div className="batch-toolbar"><label><input type="checkbox" checked={candidates.length > 0 && candidates.every(t => selectedTasks.includes(t.public_id!))} onChange={e => setSelectedTasks(previous => e.target.checked ? [...new Set([...previous, ...candidates.map(t => t.public_id!)])] : previous.filter(id => !candidates.some(t => t.public_id === id)))} /> 全选全部筛选结果（{candidates.length} 人）</label><span>已选 {selectedTasks.length} 人</span></div>
      <div className="table-wrap"><table className="table"><thead><tr><th>选择</th><th>学生</th><th>任务状态</th></tr></thead><tbody>{candidates.map(t => <tr key={t.public_id}><td><input type="checkbox" aria-label={`选择${t.student_name ?? t.public_id}`} checked={selectedTasks.includes(t.public_id!)} onChange={e => setSelectedTasks(previous => e.target.checked ? [...previous, t.public_id!] : previous.filter(id => id !== t.public_id))} /></td><td>{t.student_name ?? t.student_id ?? "—"}</td><td>{t.status}</td></tr>)}</tbody></table>{!candidates.length && <p className="subtle">没有符合条件的未完成学生</p>}</div>
      <label className="form-label" htmlFor="retake-start">重新开放时间</label><input id="retake-start" className="field" type="datetime-local" value={start} onChange={e => setStart(e.target.value)} />
      <label className="form-label" htmlFor="retake-deadline">重新提交截止时间</label><input id="retake-deadline" className="field" type="datetime-local" value={deadline} onChange={e => setDeadline(e.target.value)} />
      <p className="subtle">原发布保持截止，重做分数先封顶 60 分，再与首次分数取最大值，不新增计分项。</p>
      <button type="button" className="btn primary" disabled={!selectedTasks.length || !start || !deadline || new Date(start) <= new Date() || deadline <= start} onClick={() => setRequestReady(true)}>确认批量重新发布</button>
      <p role="status" className="teacher-notice">{requestReady ? `已选择 ${selectedTasks.length} 位学生，发布时间 ${start.replace("T", " ")}，截止时间 ${deadline.replace("T", " ")}。关联重做发布接口待后端提供，本次未发送请求、未创建发布。` : "关联重做发布接口尚未提供，当前可配置批量学生与时间；不会调用普通发布接口冒充重做成功。"}</p>
    </Modal></Panel>;
}

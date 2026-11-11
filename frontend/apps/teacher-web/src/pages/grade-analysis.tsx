import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { teachingApi } from "@edu/api-client";
import { newIdempotencyKey } from "@edu/auth-client";
import { Panel, RequestStateView, EmptyState, Modal, useToast } from "@edu/ui";
import { allPages } from "@/lib/all-pages";
import { meanGrade } from "@/lib/grades";

export function GradeAnalysis({ courseId }: { courseId: string }) {
  const [publication, setPublication] = useState("");
  const [retake, setRetake] = useState(false);
  const [selectedEnrollments, setSelectedEnrollments] = useState<string[]>([]);
  const [studentSearch, setStudentSearch] = useState("");
  const [start, setStart] = useState("");
  const [deadline, setDeadline] = useState("");
  const toast = useToast();
  const queryClient = useQueryClient();
  const retakeRequest = useRef<{ payload: string; key: string } | null>(null);
  const data = useQuery({
    queryKey: ["course-grade-analysis", courseId],
    queryFn: async () => {
      const [publications, tasks] = await Promise.all([
        allPages(page => teachingApi.publications(courseId, { page })),
        allPages(page => teachingApi.progress(courseId, { page, page_size: 100 })),
      ]);
      return { publications, tasks };
    },
  });
  const tasks = (data.data?.tasks ?? []).filter(t => !t.retake_of_task_id
    && (!publication || t.publication_id === publication));
  const gradeFor = (taskId: string) => {
    const score = data.data?.tasks.find(task => task.public_id === taskId)?.score;
    return score != null && Number.isFinite(Number(score)) ? Number(score) : 0;
  };
  const enrollments = useQuery({
    queryKey: ["course-active-enrollments", courseId],
    queryFn: () => allPages(page => teachingApi.enrollments(courseId, { status: "ACTIVE", page })),
    enabled: retake,
  });
  const originalStudentIds = new Set(tasks.filter(task => task.publication_id === publication && !task.has_retake)
    .map(task => task.student_id).filter((id): id is string => Boolean(id)));
  const candidates = (enrollments.data ?? []).filter(enrollment =>
    originalStudentIds.has(enrollment.student_id)
    && `${enrollment.student_name} ${enrollment.student_id}`.toLocaleLowerCase()
      .includes(studentSearch.trim().toLocaleLowerCase()),
  );
  const createRetake = useMutation({
    mutationFn: () => {
      const payload = {
        selected_enrollment_ids: selectedEnrollments,
        window_start: new Date(start).toISOString(),
        window_end: new Date(deadline).toISOString(),
      };
      const serialized = JSON.stringify({ courseId, publication, ...payload });
      if (retakeRequest.current?.payload !== serialized) {
        retakeRequest.current = { payload: serialized, key: newIdempotencyKey() };
      }
      return teachingApi.createRetakePublication(courseId, publication, payload, retakeRequest.current.key);
    },
    onSuccess: (result) => {
      toast.notify(result.status === "PUBLISHING" ? "补做实验已创建，正在分配学生任务" : "补做实验已创建并分配学生任务");
      setRetake(false);
      void queryClient.invalidateQueries({ queryKey: ["course-grade-analysis", courseId] });
    },
    onError: error => toast.notify(error instanceof Error ? error.message : "创建补做实验失败", "error"),
  });
  const openRetake = () => { setSelectedEnrollments([]); setStudentSearch(""); setRetake(true); };
  const average = meanGrade(tasks.map(t => gradeFor(t.public_id ?? "")));
  return <Panel title={<h2>实验成绩与任务</h2>} actions={<select className="field" aria-label="选择成绩统计实验" value={publication} onChange={e => { setPublication(e.target.value); setSelectedEnrollments([]); setRetake(false); }}><option value="">全部实验</option>{data.data?.publications.filter(p => !p.retake_of_publication_id).map(p => <option key={p.public_id} value={p.public_id}>{p.title}</option>)}</select>}><RequestStateView loading={data.isLoading} error={data.error} onRetry={() => void data.refetch()} empty={!tasks.length} emptyState={<EmptyState title="暂无已分配实验任务" />}><div className="teacher-summary"><div><span>平均成绩</span><strong>{average?.toFixed(2) ?? "—"}</strong></div><div><span>应提交任务</span><strong>{tasks.length}</strong></div><div><span>未提交任务</span><strong>{tasks.filter(t => !["SUBMITTED", "UNDER_REVIEW", "COMPLETED", "APPROVED"].includes(t.status ?? "")).length}</strong></div></div><p className="subtle">按全部已分配任务计算，未提交按 0 分；已提交待教师确认的成绩暂计 0 分。补做成绩按关联原实验计入。</p><div className="table-wrap"><table className="table"><thead><tr><th>学生</th><th>实验</th><th>任务状态</th><th>已确认成绩</th><th /></tr></thead><tbody>{tasks.map(t => <tr key={t.public_id}><td>{t.student_name ?? "—"}</td><td>{t.title}</td><td>{t.status}</td><td>{gradeFor(t.public_id ?? "")}</td><td><Link to={`/courses/${courseId}/publishing/${t.publication_id}/reviews`}>报告与评分</Link></td></tr>)}</tbody></table></div><button type="button" className="btn" disabled={!publication} onClick={openRetake}>重新发布实验</button></RequestStateView><Modal open={retake} onClose={() => setRetake(false)} title="重新发布实验" wide>
      <p>{data.data?.publications.find(p => p.public_id === publication)?.title}</p>
      <p className="subtle">从本课程有效选课学生中选择补做对象；同一原实验每位学生只能补做一次。</p>
      <input className="field" aria-label="搜索重新发布学生" placeholder="搜索学生" value={studentSearch} onChange={e => setStudentSearch(e.target.value)} />
      <RequestStateView loading={enrollments.isLoading} error={enrollments.error} onRetry={() => void enrollments.refetch()} empty={!candidates.length} emptyState={<EmptyState title="没有符合条件的有效选课学生" />}>
        <div className="batch-toolbar"><label><input type="checkbox" checked={candidates.length > 0 && candidates.every(enrollment => selectedEnrollments.includes(enrollment.public_id))} onChange={e => setSelectedEnrollments(previous => e.target.checked ? [...new Set([...previous, ...candidates.map(enrollment => enrollment.public_id)])] : previous.filter(id => !candidates.some(enrollment => enrollment.public_id === id)))} /> 全选筛选结果（{candidates.length} 人）</label><span>已选 {selectedEnrollments.length} 人</span></div>
        <div className="table-wrap"><table className="table"><thead><tr><th>选择</th><th>学生</th></tr></thead><tbody>{candidates.map(enrollment => <tr key={enrollment.public_id}><td><input type="checkbox" aria-label={`选择${enrollment.student_name}`} checked={selectedEnrollments.includes(enrollment.public_id)} onChange={e => setSelectedEnrollments(previous => e.target.checked ? [...previous, enrollment.public_id] : previous.filter(id => id !== enrollment.public_id))} /></td><td>{enrollment.student_name}</td></tr>)}</tbody></table></div>
      </RequestStateView>
      <label className="form-label" htmlFor="retake-start">重新开放时间</label><input id="retake-start" className="field" type="datetime-local" value={start} onChange={e => setStart(e.target.value)} />
      <label className="form-label" htmlFor="retake-deadline">重新提交截止时间</label><input id="retake-deadline" className="field" type="datetime-local" value={deadline} onChange={e => setDeadline(e.target.value)} />
      <p className="subtle">原发布保持截止，重做分数先封顶 60 分，再与首次分数取最大值，不新增计分项。</p>
      <button type="button" className="btn primary" disabled={!selectedEnrollments.length || !start || !deadline || new Date(start) <= new Date() || deadline <= start || createRetake.isPending} onClick={() => createRetake.mutate()}>确认批量重新发布</button>
      {createRetake.error ? <p role="alert" className="teacher-notice">{createRetake.error instanceof Error ? createRetake.error.message : "创建补做实验失败"}</p> : null}
    </Modal></Panel>;
}

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
  const average = meanGrade(tasks.map(t => gradeFor(t.public_id ?? "")));
  return <Panel title={<h2>实验成绩与任务</h2>} actions={<select className="field" aria-label="选择成绩统计实验" value={publication} onChange={e => setPublication(e.target.value)}><option value="">全部实验</option>{data.data?.publications.map(p => <option key={p.public_id} value={p.public_id}>{p.title}</option>)}</select>}><RequestStateView loading={data.isLoading} error={data.error} onRetry={() => void data.refetch()} empty={!tasks.length} emptyState={<EmptyState title="暂无已分配实验任务" />}><div className="teacher-summary"><div><span>平均成绩</span><strong>{average?.toFixed(2) ?? "—"}</strong></div><div><span>应提交任务</span><strong>{tasks.length}</strong></div><div><span>未提交任务</span><strong>{tasks.filter(t => !["SUBMITTED", "UNDER_REVIEW", "COMPLETED", "APPROVED"].includes(t.status ?? "")).length}</strong></div></div><p className="subtle">按全部已分配任务计算，未提交按 0 分；已提交待教师确认的成绩暂计 0 分。重做成绩关联与去重接口尚未提供，当前汇总仅适用于普通发布。</p><div className="table-wrap"><table className="table"><thead><tr><th>学生</th><th>实验</th><th>任务状态</th><th>已确认成绩</th><th /></tr></thead><tbody>{tasks.map(t => <tr key={t.public_id}><td>{t.student_name ?? "—"}</td><td>{t.title}</td><td>{t.status}</td><td>{gradeFor(t.public_id ?? "")}</td><td><Link to={`/courses/${courseId}/publishing/${t.publication_id}/reviews`}>报告与评分</Link></td></tr>)}</tbody></table></div><button type="button" className="btn" disabled={!publication} onClick={() => setRetake(true)}>安排不及格学生重做</button></RequestStateView><Modal open={retake} onClose={() => setRetake(false)} title="安排重做 · 接口待接入"><p>将创建关联原发布的新实验发布，指定学生和新的开放、截止时间。实际成绩为 max（首次成绩，min（第二次成绩，60）），重做不增加平均分分母。</p><p>后端尚无已确认的原新发布关联与计分接口，本页不会提交普通发布冒充重做。需求已记录在后端开发计划。</p></Modal></Panel>;
}

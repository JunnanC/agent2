import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { meApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { EmptyState, Panel, RequestStateView, StatusBadge } from "@edu/ui";
import { taskStatusLabel, taskStatusTone } from "@/lib/task-format";

export function LearningHistory() {
  const history = useQuery({ queryKey: keys.learningHistory(), queryFn: meApi.learningHistory });
  const years = (history.data?.years ?? []).filter((year) => year.terms.length > 0);
  return <Panel title={<h2>学习历史</h2>}>
    <RequestStateView loading={history.isLoading} error={history.error} onRetry={() => void history.refetch()}
      empty={!years.length} emptyState={<EmptyState title="暂无学习记录" hint="加入课程并开始学习后，记录会按学年和学期显示。" />}>
      {years.map((year) => <details key={year.academic_year} open>
        <summary>第 {year.university_year} 学年 · {year.academic_year}</summary>
        {year.terms.map((term) => <section className="section" key={term.term_id}>
          <h3>{term.name}</h3>
          {term.courses.map((course) => <div className="section" key={course.enrollment.public_id}>
            <strong>{course.course_title}</strong><span className="subtle"> · {course.course_code} · 第 {course.enrollment.cycle_no} 次选课</span>
            {!course.experiments.length && <p className="subtle">暂无实验记录</p>}
            {course.experiments.map((experiment) => <div className="item" key={experiment.task_id}>
              <div><Link to={`/experiments/${experiment.task_id}`}>{experiment.title}</Link><small>完成度 {experiment.progress}%</small></div>
              <div><StatusBadge tone={taskStatusTone(experiment.status)}>{taskStatusLabel(experiment.status)}</StatusBadge>
                {experiment.score != null && <span> · {experiment.score} 分</span>}
              </div>
            </div>)}
          </div>)}
        </section>)}
      </details>)}
    </RequestStateView>
  </Panel>;
}

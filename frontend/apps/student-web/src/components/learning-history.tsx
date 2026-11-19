import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { meApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { EmptyState, Panel, RequestStateView, StatusBadge } from "@edu/ui";
import { taskStatusLabel, taskStatusTone } from "@/lib/task-format";

const displayTermName = (name?: string) => !name || /^legacy\b/i.test(name) ? "当前学期" : name;

export function LearningHistory() {
  const history = useQuery({ queryKey: keys.learningHistory(), queryFn: meApi.learningHistory });
  const years = (history.data?.years ?? []).filter((year) => year.terms.length > 0);
  const singleYear = years.length === 1;
  return <Panel className="section student-learning-history" title={<h2>学习历史</h2>}>
    <RequestStateView loading={history.isLoading} error={history.error} onRetry={() => void history.refetch()}
      empty={!years.length} emptyState={<EmptyState title="暂无学习记录" hint="加入课程并开始学习后，记录会按学年和学期显示。" />}>
      {years.map((year, yearIndex) => {
        const courseCount = year.terms.reduce((total, term) => total + term.courses.length, 0);
        return <details className="history-year" key={year.academic_year} open={yearIndex === 0}>
          <summary>
            <span><strong>第 {year.university_year} 学年</strong><small>{year.academic_year}</small></span>
            <small>{year.terms.length} 个学期 · {courseCount} 门课程</small>
          </summary>
          <div className="history-terms">
            {year.terms.map((term, termIndex) => <details className="history-term" key={term.term_id} open={singleYear && termIndex === 0}>
              <summary>
                <strong>{displayTermName(term.name)}</strong>
                <small>{term.courses.length} 门课程</small>
              </summary>
              {term.courses.map((course) => <div className="history-course" key={course.enrollment.public_id}>
                <div className="history-course-head">
                  <strong>{course.course_title}</strong>
                  <small>{course.course_code} · 第 {course.enrollment.cycle_no} 次选课</small>
                </div>
                {!course.experiments.length && <p className="subtle">暂无实验记录</p>}
                {course.experiments.map((experiment) => <div className="item" key={experiment.task_id}>
                  <div><Link to={`/experiments/${experiment.task_id}`}>{experiment.title}</Link><small>完成度 {experiment.progress}%</small></div>
                  <div><StatusBadge tone={taskStatusTone(experiment.status)}>{taskStatusLabel(experiment.status)}</StatusBadge>
                    {experiment.score != null && <span> · {experiment.score} 分</span>}
                  </div>
                </div>)}
              </div>)}
            </details>)}
          </div>
        </details>;
      })}
    </RequestStateView>
  </Panel>;
}

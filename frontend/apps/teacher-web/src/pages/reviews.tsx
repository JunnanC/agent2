import { useSearchParams, useParams } from "react-router-dom";
import { AssessmentReviews } from "@/components/assessment-reviews";
import { AssessmentReportReview } from "@/components/assessment-report-review";

export function Reviews() {
  const { courseId = "", publicationId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const taskId = searchParams.get("task") ?? "";
  const reports = searchParams.get("tab") === "reports";
  function selectTab(showReports: boolean) {
    const next = new URLSearchParams(searchParams);
    if (showReports) next.set("tab", "reports");
    else next.delete("tab");
    setSearchParams(next);
  }
  const props = { courseId, publicationId, initialTaskId: taskId };
  const key = `${courseId}:${publicationId}:${taskId}`;
  return <>
    <nav className="page-actions assessment-review-tabs" aria-label="实验评审">
      <button className="btn" type="button" aria-pressed={!reports} onClick={() => selectTab(false)}>学生答卷</button>
      <button className="btn" type="button" aria-pressed={reports} onClick={() => selectTab(true)}>实验报告</button>
    </nav>
    {reports ? <AssessmentReportReview key={key} {...props} /> : <AssessmentReviews key={key} {...props} />}
  </>;
}

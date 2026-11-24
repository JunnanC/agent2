import { useSearchParams, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { teachingApi } from "@edu/api-client";
import { AssessmentReviews } from "@/components/assessment-reviews";
import { AssessmentReportReview } from "@/components/assessment-report-review";
import { LabGradeRelease } from "@/components/lab-grade-release";

export function Reviews() {
  const { courseId = "", publicationId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const taskId = searchParams.get("task") ?? "";
  const reports = searchParams.get("tab") === "reports";
  const experiment = useQuery({
    queryKey: ["review-publication", courseId, publicationId],
    queryFn: () => teachingApi.publication(courseId, publicationId),
    enabled: Boolean(publicationId),
  });
  const direct = experiment.data ? !experiment.data.template_version_id : searchParams.get("direct") === "1";
  function selectTab(showReports: boolean) {
    const next = new URLSearchParams(searchParams);
    if (showReports) next.set("tab", "reports");
    else next.delete("tab");
    setSearchParams(next);
  }
  const props = { courseId, publicationId, initialTaskId: taskId };
  const key = `${courseId}:${publicationId}:${taskId}`;
  return <>
    {direct && publicationId && <LabGradeRelease courseId={courseId} publicationId={publicationId} />}
    <nav className="page-actions assessment-review-tabs" aria-label="实验评审">
      <button className="btn" type="button" aria-pressed={!reports} onClick={() => selectTab(false)}>学生答卷</button>
      <button className="btn" type="button" aria-pressed={reports} onClick={() => selectTab(true)}>实验报告</button>
    </nav>
    {reports ? <AssessmentReportReview key={key} {...props} direct={direct} /> : <AssessmentReviews key={key} {...props} />}
  </>;
}

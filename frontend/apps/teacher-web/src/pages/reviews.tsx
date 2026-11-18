import { useSearchParams, useParams } from "react-router-dom";
import { Breadcrumbs } from "@edu/ui";
import { AssessmentReviews } from "@/components/assessment-reviews";

export function Reviews() {
  const { courseId = "", publicationId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get("task") ?? "";
  return <>
    <Breadcrumbs items={[{ label: "教师门户" }, { label: "课程" }]} current="学生试卷与评审" />
    <AssessmentReviews key={`${courseId}:${publicationId}:${taskId}`} courseId={courseId} publicationId={publicationId} initialTaskId={taskId} />
  </>;
}

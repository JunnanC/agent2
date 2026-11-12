import { useParams } from "react-router-dom";
import { Breadcrumbs } from "@edu/ui";
import { AssessmentReviews } from "@/components/assessment-reviews";

export function Reviews() {
  const { courseId = "", publicationId = "" } = useParams();
  return <>
    <Breadcrumbs items={[{ label: "教师门户" }, { label: "课程" }]} current="编程与报告评审" />
    <AssessmentReviews key={`${courseId}:${publicationId}`} courseId={courseId} publicationId={publicationId} />
  </>;
}

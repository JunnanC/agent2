import { useSearchParams, useParams } from "react-router-dom";
import { AssessmentReviews } from "@/components/assessment-reviews";

export function Reviews() {
  const { courseId = "", publicationId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get("task") ?? "";
  return <AssessmentReviews key={`${courseId}:${publicationId}:${taskId}`} courseId={courseId} publicationId={publicationId} initialTaskId={taskId} />;
}

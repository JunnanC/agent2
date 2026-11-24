import { ClassTimetable } from "@edu/ui";
import { Link } from "react-router-dom";
import { useStudentTimetable } from "@/lib/use-student-timetable";

export function StudentTimetable() {
  const { timetable, selectTerm } = useStudentTimetable();
  return <ClassTimetable data={timetable.data} loading={timetable.isLoading} error={timetable.error}
    classLink={(id, title) => <Link to={`/courses/${id}`}><strong>{title}</strong></Link>}
    retry={() => void timetable.refetch()} onTermChange={selectTerm} />;
}

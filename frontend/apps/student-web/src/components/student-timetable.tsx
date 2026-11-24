import { useQuery } from "@tanstack/react-query";
import { timetableApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { ClassTimetable } from "@edu/ui";
import { Link, useSearchParams } from "react-router-dom";

export function StudentTimetable() {
  const [params, setParams] = useSearchParams();
  const term = params.get("term") || undefined;
  const timetable = useQuery({
    queryKey: keys.timetable(term),
    queryFn: () => timetableApi.retrieve(term ? { term_id: term } : undefined),
    placeholderData: (previous) => previous,
  });
  return <ClassTimetable data={timetable.data} loading={timetable.isLoading} error={timetable.error}
    classLink={(id, title) => <Link to={`/courses/${id}`}><strong>{title}</strong></Link>}
    retry={() => void timetable.refetch()} onTermChange={(id) => setParams({ term: id })} />;
}

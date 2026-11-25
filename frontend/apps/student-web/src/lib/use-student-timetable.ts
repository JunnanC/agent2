import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { timetableApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";

export function useStudentTimetable() {
  const [params, setParams] = useSearchParams();
  const term = params.get("term") || undefined;
  const timetable = useQuery({
    queryKey: keys.timetable(term),
    queryFn: () => timetableApi.retrieve(term ? { term_id: term } : undefined),
  });
  const selectTerm = (id: string) => {
    const next = new URLSearchParams(params);
    next.set("term", id);
    setParams(next);
  };
  return { term, timetable, selectTerm };
}

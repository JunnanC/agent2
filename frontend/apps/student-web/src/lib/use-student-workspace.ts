import { useQuery } from "@tanstack/react-query";
import { assessmentApi } from "@edu/api-client";

export function useStudentWorkspace(taskId: string, enabled: boolean) {
  const entry = useQuery({
    queryKey: ["student-workspace-entry", taskId],
    queryFn: () => assessmentApi.enterWorkspace(taskId),
    enabled,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 3000,
  });
  const state = useQuery({
    queryKey: ["student-workspace-state", taskId],
    queryFn: () => assessmentApi.workspace(taskId),
    enabled: enabled && entry.isSuccess && entry.data?.status !== "NOT_REQUIRED",
    refetchInterval: (query) => query.state.data?.status === "EXPIRED" ? false : 2000,
  });
  return { entry, status: state.data?.status ?? entry.data?.status };
}

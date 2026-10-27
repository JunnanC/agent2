import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, authFlow } from "@edu/auth-client";
import { meApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { queryClient } from "./providers";

export interface SessionState {
  me?: Awaited<ReturnType<typeof meApi.retrieve>>;
  loading: boolean;
  error: ApiError | null;
  reload: () => void;
  logout: () => Promise<void>;
}

export function useSession(): SessionState {
  const [reloadFlag, setReloadFlag] = useState(false);
  const query = useQuery({
    queryKey: [...keys.me(), reloadFlag ? "reloaded" : "current"],
    queryFn: () => meApi.retrieve(),
    retry: false,
  });

  const error = query.error instanceof ApiError ? query.error : null;

  return {
    me: query.data,
    loading: query.isPending,
    error,
    reload: () => setReloadFlag(true),
    logout: async () => {
      try { await authFlow.logout(); } finally {
        queryClient.clear();
      }
    },
  };
}

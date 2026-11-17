import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { authFlow, ApiError } from "@edu/auth-client";
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
  const [reloadFlag, setReloadFlag] = useState(0);
  const query = useQuery({
    queryKey: [...keys.me(), reloadFlag],
    queryFn: () => meApi.retrieve(),
    retry: false,
  });

  const error = query.error instanceof ApiError ? query.error : null;

  return {
    me: query.data,
    loading: query.isPending,
    error,
    reload: () => setReloadFlag((n) => n + 1),
    logout: async () => {
      try {
        await authFlow.logout();
      } finally {
        queryClient.clear();
      }
    },
  };
}

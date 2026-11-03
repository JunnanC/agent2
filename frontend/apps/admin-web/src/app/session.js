import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { authFlow, ApiError } from "@edu/auth-client";
import { meApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { queryClient } from "./providers";
export function useSession() {
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
            try {
                await authFlow.logout();
            }
            finally {
                queryClient.clear();
            }
        },
    };
}

import { jsx as _jsx } from "react/jsx-runtime";
import { useEffect } from "react";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { ToastProvider } from "@edu/ui";
import { PortalEventStream } from "@edu/event-client";
export const queryClient = new QueryClient({
    defaultOptions: {
        queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 10_000 },
        mutations: { retry: false },
    },
});
export function domainInvalidation(event) {
    if (event.type === "message") {
        queryClient.invalidateQueries({ queryKey: ["notifications"] });
        return;
    }
    if (/^publish\./.test(event.type)) {
        queryClient.invalidateQueries({ queryKey: ["teaching-publications"] });
        return;
    }
    if (/^task\./.test(event.type) || /^provisioning\./.test(event.type)) {
        queryClient.invalidateQueries({ queryKey: ["teaching-courses"] });
        queryClient.invalidateQueries({ queryKey: ["teaching-reviews"] });
        return;
    }
    queryClient.invalidateQueries();
}
export function usePortalEvents({ enabled, streamRef }) {
    useEffect(() => {
        if (!enabled)
            return;
        const stream = new PortalEventStream();
        streamRef.current = stream;
        stream.start({
            onEvent: domainInvalidation,
            onResync: () => queryClient.invalidateQueries(),
        });
        return () => {
            stream.stop();
            streamRef.current = null;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [enabled]);
}
export function AppProviders({ children }) {
    return (_jsx(QueryClientProvider, { client: queryClient, children: _jsx(ToastProvider, { children: children }) }));
}
/** 供 hooks 注入使用（保持 import 路径稳定） */
export function useQueryClientBridge() {
    return useQueryClient();
}

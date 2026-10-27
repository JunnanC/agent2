import { useEffect } from "react";
import { QueryClient, useQueryClient } from "@tanstack/react-query";
import { PortalEventStream, STREAM_URL } from "@edu/event-client";
import type { PortalEvent } from "@edu/event-client";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 10_000,
    },
    mutations: { retry: false },
  },
});

/** SSE 事件域 → React Query 键的失效映射 */
function domainInvalidation(platform: string) {
  return (event: PortalEvent) => {
    if (event.type === "message") {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      return;
    }
    if (/^publish\./.test(event.type)) {
      queryClient.invalidateQueries({ queryKey: ["teaching-publications"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      return;
    }
    if (/^task\./.test(event.type) || /^provisioning\./.test(event.type)) {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      return;
    }
    if (/^review\./.test(event.type) || event.type === "report.returned") {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["teaching-reviews"] });
      return;
    }
    if (event.type === "course.updated") {
      queryClient.invalidateQueries({ queryKey: ["courses"] });
      queryClient.invalidateQueries({ queryKey: ["teaching-courses"] });
      return;
    }
    queryClient.invalidateQueries({ queryKey: [platform] });
    queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };
}

interface PortalEventsOptions {
  enabled: boolean;
  platform: string;
  streamRef: { current: PortalEventStream | null };
}

export function usePortalEvents({ enabled, platform, streamRef }: PortalEventsOptions): void {
  const client = useQueryClient();

  useEffect(() => {
    if (!enabled) return;
    const invalidateAll = () => client.invalidateQueries();
    const stream = new PortalEventStream();
    streamRef.current = stream;
    stream.start({
      onEvent: domainInvalidation(platform),
      onResync: invalidateAll,
    });
    return () => {
      stream.stop();
      streamRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, platform]);
}

export { STREAM_URL };

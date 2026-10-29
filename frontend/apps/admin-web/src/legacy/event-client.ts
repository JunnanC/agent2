import { PortalEventStream, type PortalEvent, type EventStreamStatus } from "../../../../packages/event-client/src/index";

export * from "../../../../packages/event-client/src/index";

export class PortalEventClient {
  private readonly stream = new PortalEventStream();

  constructor(private readonly callbacks: {
    onEvent: (event: PortalEvent) => void;
    onStateChange?: (state: string) => void;
  }) {}

  start(): void {
    this.stream.start({
      onEvent: this.callbacks.onEvent,
      onResync: () => undefined,
      onStatus: (status: EventStreamStatus) => this.callbacks.onStateChange?.(status === "reconnecting" ? "backoff" : status),
    });
  }

  stop(): void {
    this.stream.stop();
  }
}

import { PortalEventStream } from "../../../../packages/event-client/src/index";
export * from "../../../../packages/event-client/src/index";
export class PortalEventClient {
    callbacks;
    stream = new PortalEventStream();
    constructor(callbacks) {
        this.callbacks = callbacks;
    }
    start() {
        this.stream.start({
            onEvent: this.callbacks.onEvent,
            onResync: () => undefined,
            onStatus: (status) => this.callbacks.onStateChange?.(status === "reconnecting" ? "backoff" : status),
        });
    }
    stop() {
        this.stream.stop();
    }
}

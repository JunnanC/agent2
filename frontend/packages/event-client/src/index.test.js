import { describe, expect, it, vi } from "vitest";
import { PortalEventStream } from "./index";
class FakeEventSource {
    url;
    static instances = [];
    onopen = null;
    onmessage = null;
    onerror = null;
    listeners = new Map();
    closed = false;
    constructor(url) {
        this.url = url;
        FakeEventSource.instances.push(this);
    }
    close() { this.closed = true; }
    addEventListener(type, handler) {
        const list = this.listeners.get(type) ?? [];
        list.push(handler);
        this.listeners.set(type, list);
    }
    emit(type, data, lastEventId = "evt-1") {
        for (const handler of this.listeners.get(type) ?? [])
            handler({ data, lastEventId });
    }
    fail() { this.onerror?.(); }
}
describe("PortalEventStream", () => {
    it("分发业务事件并记录 last id", () => {
        const stream = new PortalEventSourceStream();
        const onEvent = vi.fn();
        const onResync = vi.fn();
        stream.start({ onEvent, onResync });
        const source = FakeEventSource.instances[0];
        if (!source)
            throw new Error("未创建 EventSource");
        source.onmessage?.({ data: JSON.stringify({ hello: 1 }), lastEventId: "001" });
        expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "message", id: "001" }));
        expect(onEvent).not.toHaveBeenCalledWith(expect.objectContaining({ type: "resync.required" }));
        expect(stream.lastId).toBe("001");
    });
    it("resync.required 触发 REST 复核回调", () => {
        const stream = new PortalEventSourceStream();
        const onResync = vi.fn();
        stream.start({ onEvent: () => undefined, onResync });
        const source = FakeEventSource.instances[0];
        if (!source)
            throw new Error("未创建 EventSource");
        source.onmessage?.({ data: JSON.stringify({}), lastEventId: "002" });
        source.onmessage?.({ data: "{}", lastEventId: "003" });
        expect(onResync).not.toHaveBeenCalled();
        source.emit("resync.required", "{}", "004");
        expect(onResync).toHaveBeenCalledWith("resync-required");
        expect(stream.lastId).toBe("004");
    });
    it("stop 后不再重连", () => {
        FakeEventSource.instances = [];
        const stream = new PortalEventStream((url) => new FakeEventSource(url));
        stream.start({ onEvent: () => undefined, onResync: () => undefined });
        stream.stop();
        expect(FakeEventSource.instances[0]?.closed).toBe(true);
        expect(stream.currentStatus).toBe("closed");
    });
});
class PortalEventSourceStream extends PortalEventStream {
    constructor() {
        FakeEventSource.instances = [];
        super((url) => new FakeEventSource(url));
    }
}

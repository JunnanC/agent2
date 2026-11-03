/**
 * 门户 SSE 客户端：GET /api/v2/events/stream（EventSource 同源携带 session cookie）。
 * - 保存最后事件 id；浏览器原生 EventSource 自动以 Last-Event-ID 重连。
 * - 处理注释行（heartbeat / stream-ready）与业务事件；resync.required 或 cursor 错误时触发 REST 复核。
 * - SSE 只是提示：最终事实一律通过 onResync → React Query invalidate 前 REST 查询为准。
 * - 断线连续失败时降级轮询（仍通过 onResync 提示刷新）。
 */
import { API_PREFIX } from "@edu/auth-client";
export const STREAM_URL = `${API_PREFIX}/events/stream`;
const RESYNC_EVENTS = new Set(["resync.required"]);
const CURSOR_ERRORS = new Set(["SSE_CURSOR_EXPIRED", "SSE_RESYNC_REQUIRED"]);
const CHECKPOINT_UNSET = Symbol("unset-last-event-id");
export class PortalEventStream {
    sourceFactory;
    maxFailuresBeforePolling;
    source = null;
    lastEventId = CHECKPOINT_UNSET;
    pollTimer = null;
    failureCount = 0;
    status = "closed";
    closed = false;
    constructor(sourceFactory = (url) => new EventSource(url), maxFailuresBeforePolling = 3) {
        this.sourceFactory = sourceFactory;
        this.maxFailuresBeforePolling = maxFailuresBeforePolling;
    }
    get lastId() {
        if (this.lastEventId === CHECKPOINT_UNSET)
            return null;
        return this.lastEventId;
    }
    get currentStatus() {
        return this.status;
    }
    start(options) {
        this.closed = false;
        this.connect(options);
    }
    stop() {
        this.closed = true;
        this.source?.close();
        this.source = null;
        if (this.pollTimer)
            clearInterval(this.pollTimer);
        this.pollTimer = null;
        this.setStatus("closed");
    }
    setStatus(next) {
        if (this.status === next)
            return;
        this.status = next;
    }
    connect(options) {
        if (this.closed)
            return;
        this.setStatus("connecting");
        const source = this.sourceFactory(STREAM_URL);
        this.source = source;
        const handle = (type, data, id) => {
            this.failureCount = 0;
            this.setStatus("connected");
            if (id)
                this.lastEventId = id;
            const event = { id, type, data, traceId: typeof data.trace_id === "string" ? data.trace_id : undefined };
            options.onEvent(event);
            if (RESYNC_EVENTS.has(type))
                options.onResync("resync-required");
            if (CURSOR_ERRORS.has(type)) {
                this.reconnect(options);
                options.onResync("cursor-expired");
            }
        };
        source.onopen = () => {
            this.failureCount = 0;
            this.setStatus("connected");
        };
        source.onmessage = (event) => handle("message", safeJson(event.data), event.lastEventId || null);
        source.onerror = () => {
            this.source?.close();
            this.source = null;
            this.failureCount += 1;
            if (this.closed)
                return;
            if (options.onStatus)
                options.onStatus("reconnecting");
            this.setStatus("reconnecting");
            if (this.failureCount >= this.maxFailuresBeforePolling) {
                this.startPolling(options);
            }
            else {
                setTimeout(() => this.connect(options), backoffMs(this.failureCount));
            }
        };
        // 服务器可能用命名事件（如 publish.succeeded）；统一监听常用域 + 兜底 message
        for (const type of [
            "publish.succeeded", "publish.failed", "publish.closed", "publish.withdrawn",
            "task.assigned", "provisioning.completed", "provisioning.failed",
            "review.decided", "report.returned", "notification.created",
            "session.expired", "resync.required", "course.updated",
        ]) {
            source.addEventListener(type, (event) => {
                const messageEvent = event;
                handle(type, safeJson(messageEvent.data), messageEvent.lastEventId || null);
            });
        }
    }
    reconnect(options) {
        this.source?.close();
        this.source = null;
        setTimeout(() => this.connect(options), 200);
    }
    startPolling(options) {
        if (this.pollTimer)
            return;
        this.setStatus("polling");
        this.pollTimer = setInterval(() => {
            if (this.closed)
                return;
            // 降级轮询：让上层重新拉节点数据
            options.onResync("reconnect-degraded");
            // 尝试恢复真实 SSE
            this.failureCount = 0;
            if (this.pollTimer)
                clearInterval(this.pollTimer);
            this.pollTimer = null;
            this.connect(options);
        }, options.pollIntervalMs ?? 15_000);
        options.onResync("reconnect-degraded");
    }
}
function safeJson(raw) {
    try {
        const parsed = JSON.parse(raw);
        return typeof parsed === "object" && parsed !== null ? parsed : {};
    }
    catch {
        return {};
    }
}
function backoffMs(failureCount) {
    return Math.min(15_000, 1000 * 2 ** Math.min(4, failureCount));
}

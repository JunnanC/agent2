import { ApiError as AuthApiError, request } from "@edu/auth-client";
export * from "../../../../packages/api-client/src/index";
export class RequestIntent {
    key = crypto.randomUUID();
}
export class ApiError extends Error {
    status;
    payload;
    traceId;
    constructor(status, message, traceId) {
        super(message);
        this.status = status;
        this.name = "ApiError";
        this.traceId = traceId;
        this.payload = { error: { message, trace_id: traceId } };
    }
}
export async function apiRequestWithMetadata(path, init = {}) {
    const apiPath = path.replace(/^\/api\/v2/, "");
    const headers = new Headers(init.headers);
    let body;
    if (typeof init.body === "string" && headers.get("Content-Type")?.includes("application/json")) {
        body = JSON.parse(init.body);
    }
    else {
        body = init.body;
    }
    try {
        const response = await request(apiPath, {
            method: init.method,
            headers: Object.fromEntries(headers.entries()),
            body,
            ifMatch: init.ifMatch,
            idempotencyKey: init.intent?.key,
            signal: init.signal,
        });
        return { payload: response, etag: response.etag, traceId: String(response.meta.trace_id ?? "") };
    }
    catch (error) {
        if (error instanceof AuthApiError) {
            throw new ApiError(error.status, error.payload?.message ?? error.message, error.traceId);
        }
        throw error;
    }
}

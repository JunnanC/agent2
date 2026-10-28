/**
 * 工作区会话(含 X-Workspace-Token)的 sessionStorage 存取。
 * 仅在当前标签页生命周期内有效:刷新保留、关闭即失效,不含敏感展示。
 */
export interface StoredWorkspaceSession {
  session_id: string;
  token: string;
  expires_at: string | null;
  status: string;
  /** 后端 workspace_urls(capability → 相对路径),如 terminal: /workspace/{sid}/terminal/ */
  workspace_urls?: Record<string, string>;
  /** 后端 capabilities(布尔开关集合,如 terminal: true) */
  capabilities?: Record<string, unknown>;
}

const storeKey = (taskId: string): string => `edu.workspace.${taskId}`;

/** 工作台可声明的能力键(与后端 _session_capabilities 推导口径一致)。 */
export const WORKSPACE_CAPABILITY_KEYS = [
  "webide",
  "notebook",
  "terminal",
  "preview",
  "snapshot",
  "checkpoint",
] as const;

/**
 * 会话快照能力是否与后端约定的能力声明一致。
 * 不一致(如教师给模板补 terminal、或旧载荷缺键)时,工作台应重新 enter 轮换会话;
 * 一致则不轮换,避免对"模板本来就未声明 terminal"的任务反复建会话。
 */
export function sessionCapabilitiesStale(
  sessionCaps: Record<string, unknown> | undefined | null,
  templateCaps: Record<string, unknown> | undefined | null,
): boolean {
  if (!sessionCaps) return true;
  if (templateCaps == null) return false;
  return WORKSPACE_CAPABILITY_KEYS.some((key) => {
    const declared = templateCaps[key] === true;
    const stored = (sessionCaps as Record<string, unknown>)[key];
    return (typeof stored === "boolean" ? stored : false) !== declared;
  });
}

export function readWorkspaceSession(taskId: string): StoredWorkspaceSession | null {
  try {
    const raw = sessionStorage.getItem(storeKey(taskId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredWorkspaceSession>;
    if (!parsed || typeof parsed.session_id !== "string" || typeof parsed.token !== "string") return null;
    return {
      session_id: parsed.session_id,
      token: parsed.token,
      expires_at: typeof parsed.expires_at === "string" ? parsed.expires_at : null,
      status: typeof parsed.status === "string" ? parsed.status : "",
      workspace_urls:
        parsed.workspace_urls && typeof parsed.workspace_urls === "object"
          ? Object.fromEntries(
              Object.entries(parsed.workspace_urls).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
            )
          : undefined,
      capabilities:
        parsed.capabilities && typeof parsed.capabilities === "object"
          ? Object.fromEntries(
              Object.entries(parsed.capabilities).filter(
                (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
              ),
            )
          : undefined,
    };
  } catch {
    return null;
  }
}

export function storeWorkspaceSession(taskId: string, payload: StoredWorkspaceSession | null): void {
  if (!payload?.session_id || !payload.token) return;
  try {
    sessionStorage.setItem(storeKey(taskId), JSON.stringify(payload));
  } catch {
    /* 存储不可用时静默放弃；工作台会通过重建会话自愈 */
  }
}

import { describe, expect, it } from "vitest";
import { readWorkspaceSession, sessionCapabilitiesStale, storeWorkspaceSession } from "./workspace-session";

describe("sessionCapabilitiesStale", () => {
  const templateCaps = {
    webide: true,
    snapshot: true,
    checkpoint: true,
    require_gateway: true,
    terminal: true,
  };

  it("与会话能力一致时不轮换", () => {
    expect(
      sessionCapabilitiesStale(
        { webide: true, snapshot: true, checkpoint: true, terminal: true },
        templateCaps,
      ),
    ).toBe(false);
  });

  it("缺失的能力键按 false 对齐,模板未声明时不算过期", () => {
    expect(
      sessionCapabilitiesStale(
        { webide: true, snapshot: true, checkpoint: true },
        { webide: true, snapshot: true, checkpoint: true },
      ),
    ).toBe(false);
  });

  it("模板补充 terminal 而会话是 false/缺键时判过期", () => {
    expect(sessionCapabilitiesStale({ webide: true, terminal: false }, templateCaps)).toBe(true);
    expect(sessionCapabilitiesStale({ webide: true }, templateCaps)).toBe(true);
  });

  it("模板本来就未声明 terminal 时,false 会话不算过期(避免反复建会话)", () => {
    expect(sessionCapabilitiesStale({ webide: true, terminal: false }, { webide: true })).toBe(false);
  });

  it("快照缺 capabilities 对象时判过期", () => {
    expect(sessionCapabilitiesStale(undefined, templateCaps)).toBe(true);
    expect(sessionCapabilitiesStale(null as unknown as Record<string, unknown>, templateCaps)).toBe(true);
  });

  it("模板口径尚未加载时不判过期(避免误轮换)", () => {
    expect(sessionCapabilitiesStale({ webide: true }, undefined)).toBe(false);
    expect(sessionCapabilitiesStale({ webide: true }, null)).toBe(false);
  });

  it("require_gateway 不参与对齐(会话快照不包含该键)", () => {
    expect(
      sessionCapabilitiesStale(
        { webide: true, snapshot: true, checkpoint: true, terminal: true },
        { webide: true, snapshot: true, checkpoint: true, terminal: true, require_gateway: true },
      ),
    ).toBe(false);
  });
});

describe("readWorkspaceSession capabilities", () => {
  it("false 布尔能力保留(用于与模板口径对齐)", () => {
    storeWorkspaceSession("t-1", {
      session_id: "s-1",
      token: "tok",
      expires_at: null,
      status: "ACTIVE",
      capabilities: { webide: true, terminal: false },
    });
    const stored = readWorkspaceSession("t-1");
    expect(stored?.capabilities).toEqual({ webide: true, terminal: false });
  });

  it("非布尔值仍被过滤", () => {
    storeWorkspaceSession("t-2", {
      session_id: "s-2",
      token: "tok",
      expires_at: null,
      status: "ACTIVE",
      capabilities: { webide: true, terminal: "yes" } as unknown as Record<string, unknown>,
    });
    const stored = readWorkspaceSession("t-2");
    expect(stored?.capabilities).toEqual({ webide: true });
  });
});

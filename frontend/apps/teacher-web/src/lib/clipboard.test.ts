import { afterEach, expect, it, vi } from "vitest";
import { copyText } from "./clipboard";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("falls back to selected text when clipboard API is unavailable", async () => {
  vi.stubGlobal("navigator", {});
  const exec = vi.fn(() => true);
  Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
  expect(await copyText("invite-123")).toBe(true);
  expect(exec).toHaveBeenCalledWith("copy");
  expect(document.querySelector("textarea")).toBeNull();
  Reflect.deleteProperty(document, "execCommand");
});
it("returns failure when both clipboard paths are refused", async () => {
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn(async () => { throw new Error("denied"); }) } });
  expect(await copyText("invite")).toBe(false);
  expect(document.querySelector("textarea")).toBeNull();
});

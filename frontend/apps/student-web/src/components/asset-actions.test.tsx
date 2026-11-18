import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { fileApi } from "@edu/api-client";
import { AssetActions } from "./asset-actions";

vi.mock("@edu/api-client", () => ({ fileApi: { createDownloadGrant: vi.fn() } }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it("offers separate authorized preview and download, and closes failed previews", async () => {
  const replace = vi.fn(); const close = vi.fn();
  vi.spyOn(window, "open").mockReturnValue({ location: { replace }, close } as never);
  vi.mocked(fileApi.createDownloadGrant).mockResolvedValueOnce({ download_path: "/files/safe-token" } as never);
  render(<ToastProvider><AssetActions assetId="asset" title="讲义" /></ToastProvider>);
  expect(screen.getByRole("button", { name: "下载 讲义" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "预览 讲义" }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/files/safe-token?preview=1"));
  expect(fileApi.createDownloadGrant).toHaveBeenCalledWith("asset");
  vi.mocked(fileApi.createDownloadGrant).mockResolvedValueOnce({ download_path: "//evil.test/files/token" } as never);
  await waitFor(() => expect(screen.getByRole("button", { name: "预览 讲义" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "预览 讲义" }));
  expect(await screen.findByText("文件地址无效")).toBeInTheDocument();
  expect(close).toHaveBeenCalled();
});

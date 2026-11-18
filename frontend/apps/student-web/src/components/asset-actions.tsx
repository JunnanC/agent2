import { useState } from "react";
import { fileApi } from "@edu/api-client";
import { useToast } from "@edu/ui";

export function AssetActions({ assetId, title }: { assetId: string; title: string }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  async function open(preview: boolean) {
    // Open synchronously so browsers do not block the preview after awaiting the grant.
    const tab = preview ? window.open("about:blank", "_blank") : null;
    if (tab) tab.opener = null;
    setBusy(true);
    try {
      if (preview && !tab) throw new Error("请允许弹出窗口后重试预览");
      const grant = await fileApi.createDownloadGrant(assetId);
      if (!/^\/files\/[A-Za-z0-9_-]+$/.test(grant.download_path)) throw new Error("文件地址无效");
      if (tab) tab.location.replace(`${grant.download_path}?preview=1`);
      else window.location.assign(grant.download_path);
    } catch (error) {
      tab?.close();
      toast.notify(error instanceof Error ? error.message : "文件打开失败", "error");
    } finally { setBusy(false); }
  }
  return <span className="asset-actions">
    <button type="button" className="btn" disabled={busy} aria-label={`预览 ${title}`} onClick={() => void open(true)}>预览</button>
    <button type="button" className="btn" disabled={busy} aria-label={`下载 ${title}`} onClick={() => void open(false)}>下载</button>
  </span>;
}

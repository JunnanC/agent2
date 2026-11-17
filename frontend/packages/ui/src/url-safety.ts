const SAFE_PROTOCOLS = new Set(["http:", "https:"]);

/** 校验外部 URL 的协议，拒绝 javascript:/data: 等可执行方案，防止存储型 XSS。 */
export function isSafeUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  if (url.startsWith("/")) return true;
  try {
    return SAFE_PROTOCOLS.has(new URL(url).protocol);
  } catch {
    return false;
  }
}

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const devApiTarget = process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8080";
const devHost = process.env.VITE_DEV_HOST ?? "127.0.0.1";
// 网关按 Host 注入门户上下文，代理必须转发 admin.localhost（不允许伪造 X-Portal）
const portalHost = "admin.localhost";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: "@edu/ui/styles.css", replacement: path.resolve(__dirname, "../../packages/ui/src/styles.css") },
      { find: /^@edu\/ui$/, replacement: path.resolve(__dirname, "src/legacy/ui.tsx") },
      { find: "@edu/api-client", replacement: path.resolve(__dirname, "src/legacy/api-client.ts") },
      { find: "@edu/auth-client", replacement: path.resolve(__dirname, "../../packages/auth-client/src/index.ts") },
      { find: "@edu/event-client", replacement: path.resolve(__dirname, "src/legacy/event-client.ts") },
      { find: "@edu/query-keys", replacement: path.resolve(__dirname, "src/legacy/query-keys.ts") },
      { find: "@", replacement: path.resolve(__dirname, "src") },
    ],
  },
  server: {
    host: devHost,
    watch: { usePolling: process.env.CHOKIDAR_USEPOLLING === "true" },
    proxy: {
      "/api": { target: devApiTarget, headers: { host: portalHost, origin: `http://${portalHost}:8080` } },
      "/files": { target: devApiTarget, headers: { host: portalHost, origin: `http://${portalHost}:8080` } },
      "/workspace": { target: devApiTarget, headers: { host: portalHost, origin: `http://${portalHost}:8080` }, ws: true },
    },
  },
  build: {
    outDir: path.resolve(__dirname, "../../dist/admin-web"),
    emptyOutDir: true,
  },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const devApiTarget = process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8080";
const devHost = process.env.VITE_DEV_HOST ?? "127.0.0.1";
// 网关按 Host 注入门户上下文，代理必须转发 student.localhost（不允许伪造 X-Portal）
const portalHost = "student.localhost";

export default defineConfig({
  plugins: [react()],
  resolve: {
    extensions: [".tsx", ".ts", ".mjs", ".js", ".mts", ".jsx", ".json"],
    alias: [
      { find: "@edu/ui/styles.css", replacement: path.resolve(__dirname, "../../packages/ui/src/styles.css") },
      { find: /^@edu\/ui$/, replacement: path.resolve(__dirname, "../../packages/ui/src/index.tsx") },
      { find: "@edu/api-client", replacement: path.resolve(__dirname, "../../packages/api-client/src/index.ts") },
      { find: "@edu/auth-client", replacement: path.resolve(__dirname, "../../packages/auth-client/src/index.ts") },
      { find: "@edu/event-client", replacement: path.resolve(__dirname, "../../packages/event-client/src/index.ts") },
      { find: "@edu/query-keys", replacement: path.resolve(__dirname, "../../packages/query-keys/src/index.ts") },
      { find: "@", replacement: path.resolve(__dirname, "src") },
    ],
  },
  server: {
    host: devHost,
    watch: { usePolling: process.env.CHOKIDAR_USEPOLLING === "true" },
    proxy: {
      "/api": { target: devApiTarget, headers: { host: portalHost, origin: `http://${portalHost}:8080` }, ws: false },
      "/files": { target: devApiTarget, headers: { host: portalHost, origin: `http://${portalHost}:8080` } },
    },
  },
  build: {
    outDir: path.resolve(__dirname, "../../dist/student-web"),
    emptyOutDir: true,
  },
});

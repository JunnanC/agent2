/* eslint-env node */
import { defineConfig } from "vitest/config";
import path from "node:path";

const pkgRoot = (name: string, file: string) => path.resolve(__dirname, `packages/${name}/src/${file}`);

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["packages/ui/src/test-setup.ts"],
    include: ["packages/*/src/**/*.test.{ts,tsx}", "apps/*/src/**/*.test.{ts,tsx}"],
  },
  resolve: {
    extensions: [".tsx", ".ts", ".mjs", ".js", ".mts", ".jsx", ".json"],
    alias: [
      { find: "@edu/ui/styles.css", replacement: pkgRoot("ui", "styles.css") },
      { find: /^@edu\/ui$/, replacement: pkgRoot("ui", "index.tsx") },
      { find: "@edu/api-client", replacement: pkgRoot("api-client", "index.ts") },
      { find: "@edu/auth-client", replacement: pkgRoot("auth-client", "index.ts") },
      { find: "@edu/event-client", replacement: pkgRoot("event-client", "index.ts") },
      { find: "@edu/query-keys", replacement: pkgRoot("query-keys", "index.ts") },
      {
        find: /^@\/(.*)$/,
        replacement: "@app-src/$1",
        customResolver(id: string, importer?: string) {
          const appMatch = importer?.replace(/\\/g, "/").match(/apps\/([^/]+)\/src\//);
          if (!appMatch) return id.replace("@app-src/", "");
          return this.resolve(
            path.resolve(__dirname, "apps", appMatch[1], "src", id.replace("@app-src/", "")),
            importer,
            { skipSelf: true },
          );
        },
      },
    ],
  },
});

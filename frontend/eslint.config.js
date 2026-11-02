import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";

export default tseslint.config(
  { ignores: ["node_modules/**", "dist/**", "packages/api-client/src/generated/**", "playwright-report/**"] },
  {
    files: ["packages/**/*.{ts,tsx}", "apps/**/*.{ts,tsx}", "e2e/**/*.ts"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...globals.browser },
    },
    extends: [...tseslint.configs.recommended, reactHooks.configs["recommended-latest"], reactRefresh.configs.vite],
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "@typescript-eslint/no-explicit-any": "off",
    },
  },
  {
    files: ["packages/ui/src/index.tsx", "packages/ui/src/toast.tsx", "apps/admin-web/src/legacy/ui.tsx", "**/providers.tsx"],
    rules: { "react-refresh/only-export-components": "off" },
  },
);

import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import jsxA11y from "eslint-plugin-jsx-a11y";

export default tseslint.config(
  { ignores: ["node_modules/**", "dist/**", "packages/api-client/src/generated/**", "playwright-report/**"] },
  {
    files: ["packages/**/*.{ts,tsx}", "apps/**/*.{ts,tsx}", "e2e/**/*.ts"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...globals.browser },
    },
    extends: [...tseslint.configs.recommended, reactHooks.configs["recommended-latest"], reactRefresh.configs.vite, jsxA11y.flatConfigs.recommended],
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["packages/ui/src/index.tsx", "packages/ui/src/toast.tsx", "**/providers.tsx"],
    rules: { "react-refresh/only-export-components": "off" },
  },
);

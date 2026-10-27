/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_VERSION?: string;
  readonly VITE_OPENAPI_REVISION?: string;
  readonly VITE_GIT_REVISION?: string;
  readonly VITE_BUILD_TIME?: string;
  readonly VITE_DEV_API_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

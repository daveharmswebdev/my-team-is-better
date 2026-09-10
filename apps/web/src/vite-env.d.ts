/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Base URL of `apps/api`. Defaults to `http://localhost:8000` (the
   * FastAPI/uvicorn default) when unset -- see `src/lib/api/client.ts`.
   */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

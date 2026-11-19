/**
 * Type declarations for Vite's `import.meta.env` (spec 23 §5 "Config").
 * Why: TypeScript strict needs to know the one build-time variable the frontend reads.
 * Rules: only `VITE_API_MODE` (`http` | `fake`); no API base URL, the app is same-origin.
 */
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_MODE?: 'http' | 'fake'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

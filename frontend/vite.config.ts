/**
 * Vite and Vitest configuration for the Discovery Agent frontend (spec 10 §3.3, spec 23 §3.12.3).
 * Why: one file defines the dev server (with /api proxied to the FastAPI backend on :8000),
 * the production build into dist/ (served by FastAPI in the container) and the test runner.
 * Rules: a production build with VITE_API_MODE=fake fails (AC-23.48), so fake data never ships.
 * Must not: point at any external host; the app is same-origin in every stage.
 * Tests keep the text of src/index.css so the token contrast test can read it (spec 23 §3.13; AC-23.58).
 */
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import { assertBuildAllowed, resolveApiMode } from './src/config/apiMode'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, '.', 'VITE_')
  assertBuildAllowed(command, resolveApiMode(env.VITE_API_MODE))
  return {
    plugins: [react()],
    server: { port: 5173, proxy: { '/api': 'http://localhost:8000' } },
    build: { outDir: 'dist' },
    test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test/setup.ts'], css: { include: [/index\.css/] } },
  }
})

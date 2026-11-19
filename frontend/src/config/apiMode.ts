/**
 * The API mode switch, `VITE_API_MODE` = `http` (default) or `fake` (spec 23 §3.12.3; AC-23.48).
 * Why: the screens run against an in-memory fake until the backend is ready; the same code then
 * runs against the real API. `vite.config.ts` calls `assertBuildAllowed` so a production build in
 * fake mode fails instead of shipping fake data.
 * Rules: pure functions, no I/O; imported by the Vite config (Node) and safe in the browser.
 */
export type ApiMode = 'http' | 'fake'

export function resolveApiMode(value: string | undefined): ApiMode {
  return value?.trim().toLowerCase() === 'fake' ? 'fake' : 'http'
}

export function assertBuildAllowed(command: 'build' | 'serve', mode: ApiMode): void {
  if (command === 'build' && mode === 'fake') {
    throw new Error(
      'VITE_API_MODE=fake is for local development only: a production build refuses it (spec 23, AC-23.48). Use `npm run dev:fake`.',
    )
  }
}

# Frontend

The screens: React, TypeScript, Vite, Tailwind, React Query.

| Page | What it shows |
|---|---|
| `Home` | Start or resume an interview |
| `ProcessDiscovery` | The interview: chat on the left, the live form on the right, document upload, *Finish* |
| `DiscoveryReport` | The discovery report (also downloadable as PDF from the backend) |
| `Workspace` | For specialists: every session, its form, conversation and report |

Employees do not sign in: a random key in the browser scopes their sessions. Specialists sign in to the workspace.

## Run and test

```bash
npm ci
npm run dev        # http://localhost:5173, talks to the backend on :8000
npm run dev:fake   # no backend needed: a built-in fake API
npm test           # Vitest
npm run lint && npm run typecheck
```

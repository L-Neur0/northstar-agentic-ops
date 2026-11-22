# Frontend

This folder is part of the [AI Use Case Discovery Agent](../README.md), and it holds the screens that employees and specialists use. They are built with React, TypeScript, Vite, Tailwind and React Query.

| Page | What it shows |
|---|---|
| `Home` | Where an employee starts a new interview or resumes an earlier one |
| `ProcessDiscovery` | The interview itself: the chat on the left, the form filling in on the right, document upload, and the *Finish* button |
| `DiscoveryReport` | The discovery report, which can also be downloaded as a PDF from the backend |
| `Workspace` | The specialists' view, where they see every session with its form, conversation and report |

Employees do not need to sign in, because a random key stored in their browser keeps their sessions apart. Specialists sign in to reach the workspace.

## Run and test

```bash
npm ci
npm run dev        # http://localhost:5173, which talks to the backend on :8000
npm run dev:fake   # no backend needed, because it uses a built-in fake API
npm test           # runs the Vitest tests
npm run lint && npm run typecheck
```

Some tests compare the screens with real API samples in `src/test/fixtures/api/`. When the API changes, you regenerate them with `cd backend && uv run python scripts/export_api_samples.py`.

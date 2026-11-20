/**
 * Test fixtures of the workspace (spec 23 §23 "Fixtures"; AC-23.116–23.137).
 * Why: the table, grid and popup tests need list rows, a step grid with a differing first
 * version and a logged-in fake API, built the same way in every test file.
 * What: `reviewRow` / `reviewList` builders, a two-step `stepGrid`, the specialist login, and
 * `workspaceFake()`, the fake API with the five seed sessions and the token already stored.
 * Rules: test-only; the shapes follow `types/workspace.ts` (spec 21 §4.2, checked against the
 * recorded samples). Must not be imported by application code.
 */
import { createFakeApi, FAKE_SPECIALIST_TOKEN } from '../../services/fakeApi'
import { storeWorkspaceToken } from '../../access/workspaceToken'
import type { MapRenderer } from '../../components/report/ProcessMap'
import type { ReviewListOut, ReviewRow, StepGrid, WorkspaceLogin } from '../../types/workspace'

export const stubMap: MapRenderer = async () => '<svg></svg>'

export const specialistLogin = (): WorkspaceLogin => ({
  token: FAKE_SPECIALIST_TOKEN,
  role: 'specialist',
  name: 'Maria (IT)',
  expiresAt: new Date(Date.now() + 8 * 3_600_000).toISOString(),
})

/** The fake with the seed and a stored specialist token (the fake reads it per call). */
export function workspaceFake() {
  storeWorkspaceToken(specialistLogin())
  return createFakeApi({ delayMs: 0, persist: false, workspaceSeed: true })
}

export function reviewRow(overrides: Partial<ReviewRow> = {}): ReviewRow {
  return {
    id: 's1',
    createdAt: '2026-11-18T09:00:00Z',
    updatedAt: new Date(Date.now() - 2 * 3_600_000).toISOString(),
    processName: 'Monthly supplier invoice check',
    department: 'Finance',
    clusterCode: 'FIN',
    clusterName: 'Finance',
    region: 'Europe',
    status: 'finished',
    phase: 'finished',
    fieldsFilled: 52,
    fieldsTotal: 64,
    steps: 4,
    messageCount: 52,
    documentCount: 1,
    ...overrides,
  }
}

export function reviewList(rows: ReviewRow[], extra: Partial<ReviewListOut> = {}): ReviewListOut {
  const count = (s: string) => rows.filter((r) => r.status === s).length
  return {
    counts: { total: rows.length, active: count('active'), finished: count('finished'), noCandidate: count('no_candidate') },
    rows,
    matching: rows.length,
    truncated: false,
    ...extra,
  }
}

export const stepGrid: StepGrid = {
  stepNames: ['Collect cost data', 'Consolidate'],
  rows: [
    {
      key: 'name',
      id: 'S01',
      label: 'Step name',
      cells: [
        { value: 'Collect cost data', source: 'expert', status: 'complete' },
        { value: 'Consolidate', source: 'document', status: 'proposed' },
      ],
    },
    {
      key: 'systems',
      id: 'S06',
      label: 'Systems',
      cells: [
        { value: 'SAP\nExcel', source: 'expert', status: 'complete' },
        { value: '<img src=x onerror=alert(1)>', source: null, status: 'partial' },
      ],
    },
  ],
}

export const rawStepGrid: StepGrid = {
  stepNames: ['Collect cost data', 'Merge the files'],
  rows: stepGrid.rows.map((r) => ({ ...r, cells: r.cells.map((c) => ({ ...c })) })),
}

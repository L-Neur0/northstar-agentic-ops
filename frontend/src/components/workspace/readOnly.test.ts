/**
 * Source scan: the workspace never edits a session (spec 23 §19.4 rule 4, §21 behaviour 28;
 * AC-23.138).
 * Why: the workspace is read-only in this part; delete is its only write. A scan of the source
 * keeps a later change from slipping an edit call or a write route into these screens.
 * What: reads every non-test file of `components/workspace/` and `pages/Workspace.tsx`, and
 * checks that no `PUT`, `POST` or `PATCH` appears and that the only API calls are the read
 * methods, the login, the PDF and delete.
 * Must not: exempt a file.
 */
const sources = import.meta.glob(['./*.tsx', '!./*.test.tsx', '../../pages/Workspace.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const ALLOWED = ['workspaceLogin', 'reviewList', 'reviewSession', 'reviewConversation', 'getReviewReportPdf', 'deleteReviewSession', 'getTaxonomy', 'getConfig']

it('scans the workspace screens', () => {
  expect(Object.keys(sources).length).toBeGreaterThanOrEqual(7)
})

it.each(Object.entries(sources))('%s makes no write call other than delete (AC-23.138)', (_file, text) => {
  expect(text).not.toMatch(/['"](PUT|POST|PATCH)['"]/)
  const calls = [...text.matchAll(/\bapi\.(\w+)\(/g)].map((m) => m[1])
  expect(calls.filter((c) => !ALLOWED.includes(c))).toEqual([])
})

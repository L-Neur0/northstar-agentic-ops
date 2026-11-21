/**
 * Step helpers for the Steps tabs and the phase meter (spec 23 §3.8.9–10; AC-23.33).
 * Why: the step tab follows the interview walk (F-08.3): the first row with a scored view (S01–S11
 * and S13, short step walk) that is neither complete nor skipped. Keys are 1-based
 * (`process.substeps[1].roles` is step 1).
 * Rules: reads field view statuses only; S12 (`handover`) and S14 (`decision_criteria`, sent only for
 * a judgement or mix step; AC-23.151) are never scored and never keep a step open. Must not inspect
 * profile values to decide whether a cell is answered.
 */
import { SCORED_CELLS_PER_STEP, STEP_LEAVES, UNSCORED_STEP_LEAVES, type FieldView } from '../types/process-discovery'

const CELL_KEY = /^process\.substeps\[(\d+)\]\.(\w+)$/

export function parseCellKey(key: string): { step: number; leaf: string } | null {
  const m = CELL_KEY.exec(key)
  return m ? { step: Number(m[1]), leaf: m[2] } : null
}

/** The views of step k (1-based), in registry order (S01–S12, then S13, then S14 when sent). */
export function viewsForStep(views: FieldView[], k: number): FieldView[] {
  const byLeaf = new Map<string, FieldView>()
  for (const v of views) {
    const cell = parseCellKey(v.key)
    if (cell && cell.step === k) byLeaf.set(cell.leaf, v)
  }
  return STEP_LEAVES.map((leaf) => byLeaf.get(leaf)).filter((v): v is FieldView => v !== undefined)
}

const isScored = (v: FieldView) => !UNSCORED_STEP_LEAVES.includes(parseCellKey(v.key)?.leaf ?? '')

export function stepScore(stepViews: FieldView[]): { filled: number; total: number } {
  const scored = stepViews.filter(isScored)
  return { filled: scored.filter((v) => v.status === 'complete').length, total: SCORED_CELLS_PER_STEP }
}

function isSettled(stepViews: FieldView[]): boolean {
  return stepViews.filter(isScored).every((v) => v.status === 'complete' || v.status === 'skipped')
}

/** 0-based index of the step the walk is on; the last row when all are settled; 0 with none. */
export function activeStepIndex(views: FieldView[], rows: number): number {
  for (let k = 1; k <= rows; k += 1) {
    if (!isSettled(viewsForStep(views, k))) return k - 1
  }
  return Math.max(rows - 1, 0)
}

export function settledStepCount(views: FieldView[], rows: number): number {
  let n = 0
  for (let k = 1; k <= rows; k += 1) if (isSettled(viewsForStep(views, k))) n += 1
  return n
}

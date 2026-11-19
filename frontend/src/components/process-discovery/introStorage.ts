/**
 * The "intro seen" flag of the interview page (spec 23 §3.9; AC-23.44).
 * Why: the intro opens by itself only on the first visit. Kept apart from the dialog component so
 * the page can read it in a state initialiser.
 * Rules: fails closed: if storage throws the intro counts as seen, because a dialog that never
 * shows beats one that shows on every visit.
 */
export const INTRO_SEEN_KEY = 'discovery_intro_seen'

export function hasSeenIntro(): boolean {
  try {
    return localStorage.getItem(INTRO_SEEN_KEY) === 'true'
  } catch {
    return true
  }
}

export function markIntroSeen(): void {
  try {
    localStorage.setItem(INTRO_SEEN_KEY, 'true')
  } catch {
    /* storage blocked: nothing to remember */
  }
}

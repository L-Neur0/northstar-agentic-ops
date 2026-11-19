/**
 * WCAG contrast helper for the colour tokens (spec 23 §3.13.6; AC-23.58).
 * Why: the contrast rule is checked from the token values in `index.css`, so a palette change that
 * makes text unreadable fails a test instead of reaching a screen.
 * What: reads the `--name: R G B;` variables of one CSS block and computes the WCAG 2 contrast
 * ratio of two "R G B" triples.
 * Must not: be imported by application code; it is a test helper kept next to the theme it checks.
 */

/** The `--name: R G B` variables declared in the first block whose selector is exactly `selector`. */
export function parseTokens(css: string, selector: string): Record<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const block = new RegExp(`(?:^|[\\s,}])${escaped}\\s*\\{([^}]*)\\}`).exec(css)
  if (!block) throw new Error(`no CSS block for ${selector}`)
  const tokens: Record<string, string> = {}
  for (const m of block[1].matchAll(/--([\w-]+)\s*:\s*(\d+\s+\d+\s+\d+)\s*;/g)) tokens[m[1]] = m[2]
  return tokens
}

function luminance(rgb: string): number {
  const [r, g, b] = rgb
    .trim()
    .split(/\s+/)
    .map((v) => {
      const c = Number(v) / 255
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** WCAG contrast ratio of two "R G B" colours, from 1 to 21. */
export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

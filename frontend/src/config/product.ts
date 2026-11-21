/**
 * The product's user-facing name and tagline (product renamed 2026-11-21; spec 01 §1, spec 23 §2).
 * Why: one place for the name the screens show, so the header, the browser tab and the intro agree.
 * The server's copy (welcome, report, PDF) comes from `config/<company>/organisation.yaml`.
 * Rules: display text only. Code identifiers, routes and storage keys keep `process-discovery`.
 */
export const PRODUCT_NAME = 'AI Use Case Discovery Agent'

/** The header title under the `sm` breakpoint, where the full name does not fit. */
export const PRODUCT_SHORT_NAME = 'Use Case Discovery'

export const PRODUCT_TAGLINE = 'Find a workflow worth transforming, map it step by step, and see where AI can help'

"""ASSESS_STEPS: a per-step AI fit and a route from the company's solution catalogue, grounded by code (spec 26).

Why: besides the opportunities, the expert and the specialists need a step-by-step view: can AI do
this step, help with it, or should it stay with people, and with which of the company's tools. This
package holds the one model call (`steps`), its wire schema, its prompt, the pure grounding and the
pure recommended route. It never imports `analysis/`, `diagram/` or `labels/` (AC-26.19).
"""

"""OPPORTUNITIES: where automation or AI fits in a finished process, grounded in the expert's words (spec 18 §3.4–3.6).

Why: the assessment's main finding comes from one model call, and none of its content is trusted
until code has checked every step number and every quote against the profile. This package holds
that call (`analysis.run_opportunities`), its strict wire schema, its prompt and the grounding.
It never imports `artifacts/diagram`, so either package can be removed on its own (AC-18.40).
"""

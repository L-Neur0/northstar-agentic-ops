"""LABEL: the format of each step's inputs and the kind of each decision, grounded in the expert's words (spec 19 §3.3–3.4).

Why: the Data and Rules readiness dimensions are counted from these labels, and the model's only
part is reading the words; code checks every step, input name and quote. This package holds the
call (`labels.run_labels`), its strict wire schema, its prompt and the pure grounding. It never
imports `analysis/`, `diagram/` or `step_assessment/`, so each can be removed on its own.
"""

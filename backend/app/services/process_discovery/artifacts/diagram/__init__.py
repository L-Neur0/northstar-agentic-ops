"""MAP: the BPMN-style process map, proposed by the model and grounded in the profile by code (spec 18 §3.7–3.8).

Why: a finished profile must always have a map, and a map must only show steps, roles and systems
the expert named. This package holds the call (`diagram.run_map`), its strict wire schema, its
prompt, the grounding that repairs or replaces the model's graph, and the linear map drawn by code.
It never imports `artifacts/analysis`, so either package can be removed on its own (AC-18.40).
"""

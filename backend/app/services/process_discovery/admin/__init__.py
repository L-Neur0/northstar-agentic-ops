"""The admin side of the engine: what the specialist's workspace reads about every session (spec 21).

Why: specialists review every expert's sessions, and what they see must come from the same
profile rules as the interview, so the list and the read-only session view are built here, in
the engine, from the stored session; edits with provenance come later (spec 21 §8).
What: `listing` (the session list, filters and counts) and `view` (the session view and its step
grids). Pure: no I/O, no clock; an engine peer that imports only `domain`, `profile` and the models.
"""

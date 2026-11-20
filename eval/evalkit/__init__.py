"""The evaluation kit: persona files, the simulated expert, the drivers, the scorers and the scorecard (spec 24).

Why: each part has one job and its own tests, so a change in scoring cannot silently change how
personas are played. What: modules only; nothing runs at import time. Spec 24 §3.1, §4.
"""

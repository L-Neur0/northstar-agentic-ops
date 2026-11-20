"""The evaluation package: simulated experts play the real API and the runner scores the result (spec 24).

Why: it lives outside the backend so it can only reach the product the way a browser does (HTTP),
plus the four backend pieces spec 24 §2 allows. What: `run.py` is the command line; `evalkit/`
holds the runner, the scorers and the scorecard. Spec 24 §2, §3.1.
"""

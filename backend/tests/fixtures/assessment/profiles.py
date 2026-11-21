"""Shared fixture profiles for the assessment tests: the monthly cost review, Europe and North America.

Why: the assessment specs (18, 19, 20, 26) all use the same worked example, and a hand-typed copy in
each test file would drift from the stored one. The JSON files beside this module are full `Profile`
dumps (spec 12), so every test reads exactly what the store would hold.
What: `load_profile("eu" | "na")` returns a fresh dict each call, `nig_config()` loads the real NIG
configuration and `nig_vocabulary()` builds the `Vocabulary` the way the app lifespan does.
Must not: patch, fake or edit the configuration; tests change their own copy of a profile only.
Spec 18 §3.1.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Literal

from app.core.config import CompanyConfig, load_company_config
from app.services.process_discovery.domain.field_spec import Vocabulary

HERE = Path(__file__).resolve().parent
NIG = HERE.parents[3] / "config" / "nig"


def load_profile(variant: Literal["eu", "na"] = "eu") -> dict[str, Any]:
    """A fresh copy of the cost-review fixture profile."""
    return json.loads((HERE / f"monthly_cost_review_{variant}.json").read_text(encoding="utf-8"))


def load_cv_screening() -> dict[str, Any]:
    """The p05 CV-screening profile from evaluation run 20261121-094609, with the demo's live correction
    applied (steps 3 and 4 once per role; criteria set by the hiring manager, partly written). Spec 27."""
    return json.loads((HERE / "cv_screening_p05.json").read_text(encoding="utf-8"))


@cache
def nig_config() -> CompanyConfig:
    return load_company_config(NIG)


def nig_vocabulary() -> Vocabulary:
    config = nig_config()
    return Vocabulary(taxonomy=config.taxonomy, regions=config.organisation.regions, wording=config.wording)

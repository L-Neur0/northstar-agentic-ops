"""Shared fixtures for the domain tests (spec 12 §7).

Why: validators and reason sentences read the company vocabulary (regions, clusters, wording), and
tests must use the real NIG configuration rather than a hand-typed copy that can drift from it.
What: `nig_config` loads `config/nig` through the real loader; `nig_vocabulary` builds the frozen
`Vocabulary` from it, exactly as the app lifespan does. It must not patch or fake any of the files.
"""

from pathlib import Path

import pytest

from app.core.config import CompanyConfig, load_company_config
from app.services.process_discovery.domain.field_spec import Vocabulary

NIG = Path(__file__).resolve().parents[5] / "config" / "nig"


@pytest.fixture(scope="session")
def nig_config() -> CompanyConfig:
    return load_company_config(NIG)


@pytest.fixture(scope="session")
def nig_vocabulary(nig_config: CompanyConfig) -> Vocabulary:
    return Vocabulary(
        taxonomy=nig_config.taxonomy,
        regions=nig_config.organisation.regions,
        wording=nig_config.wording,
    )

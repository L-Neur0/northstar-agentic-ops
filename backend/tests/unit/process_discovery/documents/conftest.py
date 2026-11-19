"""Shared fixtures for the document tests (spec 17 §7).

Why: the limits, the vocabulary and the fixture files must be the real ones (`config/nig`,
`tests/fixtures/documents/`), never a hand-typed copy that drifts from what the product loads.
What: `nig_config`, `vocab` and `docs_config` load `config/nig` through the real loader;
`fixture_bytes` reads one fixture file by name.
Must not: patch or fake a configuration file, or build fixtures at import time (the files are
built by `tests/fixtures/documents/make_fixtures.py`). Supports AC-17.1 to AC-17.44.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.config import CompanyConfig, DocumentsConfig, load_company_config
from app.services.process_discovery.domain.field_spec import Vocabulary

BACKEND = Path(__file__).resolve().parents[4]
NIG = BACKEND.parent / "config" / "nig"
FIXTURES = BACKEND / "tests" / "fixtures" / "documents"


@pytest.fixture(scope="session")
def nig_config() -> CompanyConfig:
    return load_company_config(NIG)


@pytest.fixture(scope="session")
def vocab(nig_config: CompanyConfig) -> Vocabulary:
    return Vocabulary(taxonomy=nig_config.taxonomy, regions=nig_config.organisation.regions, wording=nig_config.wording)


@pytest.fixture(scope="session")
def docs_config(nig_config: CompanyConfig) -> DocumentsConfig:
    return nig_config.documents


@pytest.fixture(scope="session")
def fixture_bytes() -> Callable[[str], bytes]:
    def read(name: str) -> bytes:
        return (FIXTURES / name).read_bytes()

    return read

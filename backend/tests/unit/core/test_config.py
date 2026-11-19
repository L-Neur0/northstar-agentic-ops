"""Tests for the company configuration loader (spec 10 §3.6).

Why: everything that differs between companies lives in YAML. A typo there must stop the app with
every problem listed at once, not show up as a wrong question in an interview.
What: loads the real NIG folder, then broken copies of it. Implements AC-10.7 to AC-10.10.
"""

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.core.config import ConfigError, load_company_config

NIG = Path(__file__).resolve().parents[4] / "config" / "nig"


@pytest.fixture
def nig_copy(tmp_path):
    target = tmp_path / "nig"
    shutil.copytree(NIG, target)
    return target


def edit(folder: Path, name: str, change):
    path = folder / name
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_the_nig_configuration_loads():
    """AC-10.7."""
    cfg = load_company_config(NIG)
    assert len(cfg.organisation.regions) == 4
    assert cfg.organisation.languages == ("en", "de")
    assert cfg.rates.default_hourly_rate == 90
    assert (cfg.rates.realisation.conservative, cfg.rates.realisation.expected) == (0.5, 0.75)
    assert len(cfg.rates.saving_share) == 8
    with pytest.raises(ValidationError):
        cfg.rates.default_hourly_rate = 1  # frozen


def test_every_problem_is_listed_at_once(nig_copy):
    """AC-10.8: a missing file, a bad colour and a share above 0.9, reported together."""
    (nig_copy / "documents.yaml").unlink()
    edit(nig_copy, "organisation.yaml", lambda d: d["branding"].update(primary_colour="blue"))
    edit(nig_copy, "rates.yaml", lambda d: d["saving_share"].update(rpa=1.2))
    with pytest.raises(ConfigError) as err:
        load_company_config(nig_copy)
    problems = err.value.problems
    assert any("documents.yaml" in p for p in problems)
    assert any("organisation.yaml" in p and "primary_colour" in p for p in problems)
    assert any("rates.yaml" in p and "rpa" in p for p in problems)


def test_ok_is_never_a_yes_word(nig_copy):
    """AC-10.9."""
    edit(nig_copy, "language.yaml", lambda d: d["languages"]["en"]["yes"].append("ok"))
    with pytest.raises(ConfigError, match="ok"):
        load_company_config(nig_copy)


def test_an_unknown_key_is_rejected(nig_copy):
    """AC-10.10: no silent typos."""
    edit(nig_copy, "rates.yaml", lambda d: d.update(defualt_hourly_rate=80))
    with pytest.raises(ConfigError, match="defualt_hourly_rate"):
        load_company_config(nig_copy)


def test_a_missing_folder_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_company_config(tmp_path / "nowhere")

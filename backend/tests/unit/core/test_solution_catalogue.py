"""Tests for the solution catalogue (spec 26 §3.1, §4.3; AC-26.1).

Why: the step assessment may only route a step to a solution the company lists, so the list is
company configuration checked at start-up. A duplicate id, an unknown category or a catalogue with
no "stays with people" entry would let a step be routed wrongly or not at all.
What: loads the company `solutions.yaml` (the assumed tool set: `placeholder: false`, `assumed: true`),
then broken copies, through the shared loader, so each problem is a `ConfigError` naming the file.
"""

import shutil
from pathlib import Path

import pytest
import yaml

from app.core.config import ConfigError, SolutionCatalogue, load_company_config

NIG = Path(__file__).resolve().parents[4] / "config" / "nig"


@pytest.fixture
def nig_copy(tmp_path):
    target = tmp_path / "nig"
    shutil.copytree(NIG, target)
    return target


def edit_solutions(folder: Path, change) -> None:
    path = folder / "solutions.yaml"
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_the_nig_catalogue_loads():
    """AC-26.1 (amended by the 2026-11-19 decision: an assumed set, not a placeholder)."""
    catalogue = load_company_config(NIG).solutions
    assert isinstance(catalogue, SolutionCatalogue)
    assert catalogue.placeholder is False and catalogue.assumed is True
    assert catalogue.version
    assert len(catalogue.solutions) == 13
    internal = [s.id for s in catalogue.solutions if s.category == "existing_internal"]
    assert len(internal) == 6
    assert any("human" in s.fits for s in catalogue.solutions)


def test_get_finds_an_entry_by_id():
    """§4.3: `get` returns the entry or None."""
    catalogue = load_company_config(NIG).solutions
    first = catalogue.solutions[0]
    assert catalogue.get(first.id) is first
    assert catalogue.get("no-such-route") is None


def first_entry(data) -> dict:
    return data["solutions"][0]


@pytest.mark.parametrize(
    ("change", "where"),
    [
        (lambda d: d["solutions"].append(dict(first_entry(d))), "duplicate id"),
        (lambda d: first_entry(d).update(id="Bad Slug"), "id"),
        (lambda d: first_entry(d).update(category="magic"), "category"),
        (lambda d: first_entry(d).update(fits=[]), "fits"),
        (lambda d: first_entry(d).update(fits=["maybe"]), "fits"),
        (lambda d: first_entry(d).update(choose_when=[]), "choose_when"),
        (lambda d: d["solutions"].extend(dict(first_entry(d), id=f"extra-{i}") for i in range(30)), "solutions"),
        (lambda d: d.update(solutions=[s for s in d["solutions"] if "human" not in s["fits"]]), "human"),
        (lambda d: first_entry(d).update(name=""), "name"),
        (lambda d: first_entry(d).update(good_for="x" * 401), "good_for"),
        (lambda d: first_entry(d).update(avoid_when=["x"] * 6), "avoid_when"),
        (lambda d: d.update(assumed="sometimes"), "assumed"),
        (lambda d: d.update(owner="someone"), "owner"),
    ],
    ids=[
        "duplicate-id",
        "bad-slug",
        "unknown-category",
        "empty-fits",
        "unknown-fit",
        "empty-choose-when",
        "more-than-30",
        "no-human-entry",
        "empty-name",
        "good-for-too-long",
        "six-avoid-when",
        "assumed-not-bool",
        "unknown-key",
    ],
)
def test_a_bad_catalogue_stops_start_up(nig_copy, change, where):
    """AC-26.1: every rule of §3.1 is checked at start-up."""
    edit_solutions(nig_copy, change)
    with pytest.raises(ConfigError) as err:
        load_company_config(nig_copy)
    assert any("solutions.yaml" in p and where in p for p in err.value.problems), err.value.problems


def test_a_missing_catalogue_stops_start_up(nig_copy):
    """Spec 26 §5: a missing file stops the app like any other config file."""
    (nig_copy / "solutions.yaml").unlink()
    with pytest.raises(ConfigError, match="solutions.yaml: file is missing"):
        load_company_config(nig_copy)

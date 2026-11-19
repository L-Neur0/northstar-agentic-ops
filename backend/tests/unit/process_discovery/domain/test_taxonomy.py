"""Tests for the cluster taxonomy: the NIG file, its validation and its lookups (spec 12 §3.8).

Why: the clusters are company configuration (F-22), and a bad file must stop the app at start-up
rather than misplace processes. Placement without a model call (F-07.1) is only safe if no
keyword can fire in two clusters, which the validator must guarantee.
What: loads `config/nig/taxonomy.yaml` through the real loader, rejects each documented fault
(parametrised) with a message naming the cluster, and checks the keyword matcher and the spoken
lookups. Implements AC-12.29 to AC-12.32.
"""

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.services.process_discovery.domain.taxonomy import GENERIC_TERMS, UNKNOWN_CODE, Taxonomy, keyword_hit

TAXONOMY_FILE = Path(__file__).resolve().parents[5] / "config" / "nig" / "taxonomy.yaml"


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(TAXONOMY_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def taxonomy(raw) -> Taxonomy:
    return Taxonomy.model_validate(raw)


# --- AC-12.29: the NIG file ------------------------------------------------------------------


def test_nig_taxonomy_has_the_nine_clusters_in_order(nig_config):
    """AC-12.29: codes and names exactly as the company names them, in display order."""
    assert [(c.code, c.name) for c in nig_config.taxonomy.clusters] == [
        ("FIN", "Finance"),
        ("HR", "People & HR"),
        ("LEG", "Legal"),
        ("IT", "IT & Security"),
        ("PRO", "Procurement"),
        ("COM", "Comms & Growth"),
        ("KNW", "Knowledge & Ops"),
        ("ANL", "Analytics & Strategy"),
        ("GWT", "Sales & Marketing"),
    ]
    assert isinstance(nig_config.taxonomy, Taxonomy)
    assert nig_config.taxonomy.codes() == ["FIN", "HR", "LEG", "IT", "PRO", "COM", "KNW", "ANL", "GWT"]


def test_prompt_block(taxonomy):
    """§3.8: one `CODE · name: description` line per cluster."""
    lines = taxonomy.prompt_block().splitlines()
    assert len(lines) == 9
    assert lines[0] == (
        "FIN · Finance: Planning, recording and reporting money - budgets, invoices, costs and the monthly close."
    )


def test_taxonomy_is_frozen(taxonomy):
    """§4: the taxonomy is frozen once loaded."""
    with pytest.raises(ValidationError):
        taxonomy.clusters = ()


# --- AC-12.30: faults ------------------------------------------------------------------------


def _cluster(data: dict, code: str) -> dict:
    return next(c for c in data["clusters"] if c["code"] == code)


def dup_code(d):
    _cluster(d, "HR")["code"] = "FIN"


def dup_name(d):
    _cluster(d, "HR")["name"] = "finance"


def unknown_code(d):
    _cluster(d, "HR")["code"] = UNKNOWN_CODE


def bad_code(d):
    _cluster(d, "HR")["code"] = "Hr"


def no_keywords(d):
    _cluster(d, "HR")["keywords"] = []


def shared_keyword(d):
    _cluster(d, "HR")["keywords"].append("invoice")


def generic_term(d):
    _cluster(d, "HR")["keywords"].append("report")


def fires_inside(d):
    _cluster(d, "HR")["keywords"].append("purchase")


def uppercase_keyword(d):
    _cluster(d, "HR")["keywords"].append("Shift Plan")


def untrimmed_keyword(d):
    _cluster(d, "HR")["keywords"].append(" shift plan")


def long_description(d):
    _cluster(d, "HR")["description"] = " ".join(["word"] * 26)


def names_another(d):
    _cluster(d, "HR")["description"] = "Hiring people, and the finance side of paying them."


def description_is_name(d):
    _cluster(d, "HR")["description"] = "People & HR"


def name_is_a_code(d):
    _cluster(d, "HR")["name"] = "fin"


FAULTS = [
    dup_code,
    dup_name,
    unknown_code,
    bad_code,
    no_keywords,
    shared_keyword,
    generic_term,
    fires_inside,
    uppercase_keyword,
    untrimmed_keyword,
    long_description,
    names_another,
    description_is_name,
    name_is_a_code,
]


@pytest.mark.parametrize("fault", FAULTS, ids=lambda f: f.__name__)
def test_a_faulty_taxonomy_is_rejected_naming_the_cluster(raw, fault):
    """AC-12.30: each fault is a validation error whose message names the cluster."""
    data = copy.deepcopy(raw)
    fault(data)
    with pytest.raises(ValidationError) as caught:
        Taxonomy.model_validate(data)
    message = str(caught.value)
    assert "People & HR" in message or "HR" in message
    assert "cluster" in message.lower()


def test_an_empty_taxonomy_is_rejected():
    """§3.8: at least one cluster."""
    with pytest.raises(ValidationError):
        Taxonomy.model_validate({"clusters": []})


def test_unknown_keys_are_rejected(raw):
    """Config models reject unknown keys (spec 10)."""
    data = copy.deepcopy(raw)
    data["clusters"][0]["group"] = "Back office"
    with pytest.raises(ValidationError):
        Taxonomy.model_validate(data)


def test_generic_terms_are_the_documented_list():
    """§3.8: the code constant of terms too vague to place anything."""
    assert GENERIC_TERMS == frozenset(
        "process report review approval data system email meeting document request team manager plan update check "
        "project".split()
    )


# --- AC-12.31: lookups -----------------------------------------------------------------------


def test_by_code(taxonomy):
    """AC-12.31: case-insensitive; unknown is `None`."""
    assert taxonomy.by_code("fin").code == "FIN"
    assert taxonomy.by_code(" GWT ").code == "GWT"
    assert taxonomy.by_code("XYZ") is None
    assert taxonomy.by_code(None) is None


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("it and security", "IT"),
        ("IT", "IT"),
        ("IT & Security", "IT"),
        ("Finance", "FIN"),
        ("I confirm Finance (FIN)", "FIN"),
        ("I confirm Finance", "FIN"),
        ("sales and marketing", "GWT"),
        ("hr", "HR"),
    ],
)
def test_by_spoken_resolves_what_people_type(taxonomy, text, code):
    """AC-12.31."""
    cluster = taxonomy.by_spoken(text)
    assert cluster is not None and cluster.code == code


@pytest.mark.parametrize("text", ["we use it every day", "", None, "finance is hard", "yes"])
def test_by_spoken_never_matches_inside_prose(taxonomy, text):
    """AC-12.31: running prose is not a pick."""
    assert taxonomy.by_spoken(text) is None


# --- AC-12.32: keyword matcher ---------------------------------------------------------------


def test_keyword_hit_boundaries():
    """AC-12.32: short keywords need both boundaries; long ones only the left."""
    assert not keyword_hit("nda", "the standard applies")
    assert keyword_hit("nda", "sign an NDA")
    assert keyword_hit("invoice", "approving invoices")
    assert not keyword_hit("invoice", "we reinvoice the client")


def test_single_and_multiple_matches(taxonomy):
    """AC-12.32: one hit places without a model; two hits do not."""
    assert taxonomy.single_match("the monthly cost review").code == "FIN"
    assert [c.code for c in taxonomy.match_keywords("approving vendor invoices")] == ["FIN", "PRO"]
    assert taxonomy.single_match("approving vendor invoices") is None
    assert taxonomy.match_keywords("the weekly team meeting") == []
    assert taxonomy.match_keywords(None) == []
    assert taxonomy.single_match("") is None

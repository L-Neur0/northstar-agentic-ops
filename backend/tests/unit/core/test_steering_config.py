"""Tests for the steering configuration (spec 14 §3.15 item 11; AC-14.71).

Why: the weights and limits that rank the expert's candidate processes are company configuration.
A weight set that does not add up, or a question limit above three, would quietly change which
process the agent recommends or how long the find phase lasts, so a bad file must stop start-up.
What: loads the company `steering.yaml` with the spec defaults, then broken copies of it, through the
same loader as every other company file (a problem is a `ConfigError` naming the file).
"""

import shutil
from pathlib import Path

import pytest
import yaml

from app.core.config import ConfigError, load_company_config

NIG = Path(__file__).resolve().parents[4] / "config" / "nig"


@pytest.fixture
def nig_copy(tmp_path):
    target = tmp_path / "nig"
    shutil.copytree(NIG, target)
    return target


def edit_steering(folder: Path, change) -> None:
    path = folder / "steering.yaml"
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_the_nig_steering_file_loads_with_the_spec_defaults():
    """AC-14.71: the item 11 file loads."""
    steering = load_company_config(NIG).steering
    assert (steering.weights.hours, steering.weights.people, steering.weights.data) == (0.5, 0.2, 0.3)
    assert (steering.hours_full_score, steering.people_full_score) == (500, 5)
    assert (steering.min_known_signals, steering.max_candidates, steering.max_questions) == (2, 3, 3)
    assert "spreadsheet" in steering.input_cues.digital and "phone" in steering.input_cues.paper_verbal
    assert "just me" in steering.solo_phrases


@pytest.mark.parametrize(
    ("change", "where"),
    [
        (lambda d: d["weights"].update(hours=0.6), "weights"),
        (lambda d: d["weights"].update(hours=0.9, people=-0.2), "people"),
        (lambda d: d.update(people_full_score=1), "people_full_score"),
        (lambda d: d.update(max_questions=4), "max_questions"),
        (lambda d: d.update(max_questions=0), "max_questions"),
        (lambda d: d["input_cues"].update(digital=[]), "digital"),
        (lambda d: d["input_cues"].update(paper_verbal=[]), "paper_verbal"),
        (lambda d: d.update(hours_full_score=0), "hours_full_score"),
        (lambda d: d.update(min_known_signals=4), "min_known_signals"),
        (lambda d: d.update(max_candidates=6), "max_candidates"),
        (lambda d: d.update(unknown_key=1), "unknown_key"),
    ],
    ids=[
        "weights-sum",
        "negative-weight",
        "people-below-2",
        "questions-above-3",
        "questions-below-1",
        "empty-digital-cues",
        "empty-paper-cues",
        "hours-zero",
        "known-signals-above-3",
        "candidates-above-5",
        "unknown-key",
    ],
)
def test_a_bad_steering_file_stops_start_up(nig_copy, change, where):
    """AC-14.71: weights not summing to 1, a negative weight, people below 2, questions outside 1-3, an empty cue list."""
    edit_steering(nig_copy, change)
    with pytest.raises(ConfigError) as err:
        load_company_config(nig_copy)
    assert any("steering.yaml" in p and where in p for p in err.value.problems), err.value.problems


def test_weights_within_the_tolerance_load(nig_copy):
    """Item 11: the sum is 1 within ± 0.001."""
    edit_steering(nig_copy, lambda d: d["weights"].update(hours=0.5005))
    assert load_company_config(nig_copy).steering.weights.hours == 0.5005


def test_a_missing_steering_file_stops_start_up(nig_copy):
    """Spec 10: a missing file stops the app like any other config file."""
    (nig_copy / "steering.yaml").unlink()
    with pytest.raises(ConfigError, match="steering.yaml: file is missing"):
        load_company_config(nig_copy)

"""Persona files and the calibration file are checked before any model call (spec 24 §3.2, §3.8; AC-24.1, AC-24.2, AC-24.18).

Why: a bad persona makes every score meaningless, so loading must stop with the file and the key
named. What: broken copies of the tiny persona, the four real personas, the QUICK selection, and
the calibration file's shape rule. Must not: call a model.
"""

from __future__ import annotations

import pytest
import yaml

from eval.evalkit.calibrate import CalibrationFileError, load_pairs
from eval.evalkit.persona import EVAL_DIR, PersonaError, load_personas

from .conftest import FIXTURES, tiny_data


def _write(tmp_path, data, name="bad.yaml"):
    folder = tmp_path / "personas"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(yaml.safe_dump(data), encoding="utf-8")
    return folder


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["truth"]["fields"].update({"process.colour": "red"}), "process.colour"),
        (lambda d: d["truth"]["fields"].update({"process.substep_count": 3}), "process.substep_count"),
        (lambda d: d["truth"]["fields"].update({"process.cluster": "XYZ"}), "process.cluster"),
        (lambda d: d["expected"].update({"cluster": "XYZ"}), "expected.cluster"),
        (
            lambda d: d["expected"]["routes"].update({1: {"fit": ["assist"], "route": ["no-such-route"]}}),
            "no-such-route",
        ),
        (lambda d: d["expected"]["routes"].update({1: {"fit": ["human"], "route": ["fix-first"]}}), "allows none"),
        (lambda d: d["truth"]["steps"][0].update({"colour": "red"}), "truth.steps[1].colour"),
    ],
)
def test_ac_24_1_a_bad_persona_stops_the_run_naming_file_and_key(tmp_path, company, change, message):
    data = tiny_data()
    change(data)
    folder = _write(tmp_path, data)
    with pytest.raises(PersonaError) as error:
        load_personas(folder, quick=False, company=company, documents_dir=FIXTURES)
    assert "bad.yaml" in str(error.value) and message in str(error.value)


def test_ac_24_1_unknown_top_level_keys_are_refused(tmp_path, company):
    data = tiny_data() | {"surprise": 1}
    with pytest.raises(PersonaError, match="bad.yaml"):
        load_personas(_write(tmp_path, data), quick=False, company=company, documents_dir=FIXTURES)


def test_ac_24_2_the_four_personas_load_and_quick_selects_two(company):
    every = load_personas(EVAL_DIR / "personas", quick=False, company=company)
    assert [p.id for p in every] == ["p01-cooperative", "p02-vague", "p03-task-mixed-week", "p04-stale-document"]
    quick = load_personas(EVAL_DIR / "personas", quick=True, company=company)
    assert [p.id for p in quick] == ["p01-cooperative", "p02-vague"]
    p01 = every[0]
    assert p01.truth_field_count == 71  # §3.7 item 5
    assert [p.kind for p in every] == ["cooperative", "difficult", "difficult", "cooperative"]


def test_ac_24_18_calibration_file_shape():
    pairs = load_pairs(EVAL_DIR / "judge_calibration.yaml")
    assert 25 <= len(pairs) <= 40
    assert sum(p.label for p in pairs) >= 12 and sum(not p.label for p in pairs) >= 12


def test_ac_24_18_a_calibration_file_with_too_few_false_pairs_is_refused(tmp_path):
    pair = {"field": "Goal", "hidden": "a", "captured": "a", "label": True}
    path = tmp_path / "cal.yaml"
    path.write_text(yaml.safe_dump({"pairs": [pair] * 30}), encoding="utf-8")
    with pytest.raises(CalibrationFileError):
        load_pairs(path)

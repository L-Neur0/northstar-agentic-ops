"""Unit tests for the discovery report model, `build_report` (spec 20 §3.3).

Why: the report is what the expert takes away; every number in it must equal the calculator it
came from, every missing answer must read as missing (never invented), each part must fail on its
own, and nothing private (display name, messages, document text) may reach it.
What: `build_report` on the EU cost review finished by a scripted *Finish* (`export/cases.py`), on
edited copies of it, and on a thin session; assertions on the parts' numbers, titles, notes and
formatted values, and a sentinel test over the JSON.
Must not: call a model or re-test the calculators (specs 18, 19, 26 do).
Covers AC-20.18 to AC-20.31, AC-20.43, AC-20.46 to AC-20.48.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.models.process_discovery_schemas import (
    Message,
    ScopeState,
    ScopeVerdict,
)
from app.models.process_discovery_wire import DiscoveryReport, FeasibilityPart
from app.services.process_discovery.artifacts import report as report_module
from app.services.process_discovery.artifacts.report import build_report, cell_text
from tests.fixtures.assessment.profiles import load_profile
from tests.fixtures.assessment_19.cases import example_catalogue
from tests.unit.process_discovery.export.cases import AT, CATALOGUE, ORG, VOCAB, eu_assessment, eu_session, thin_session

TITLES = [
    "Summary", "The process", "Volume and measures", "Process map and steps", "Step-by-step AI assessment",
    "AI readiness and feasibility",
]  # fmt: skip  # spec 27 §3.1
STANDARD_LINE = (
    'Agree one way of working (one template) across teams and regions. What differs today: "each site sends '
    'its own spreadsheet layout".'
)
HEADLINE = (
    'Start with step 2 "Consolidate into the master file" (about 96 h a year) using Custom AI app or agent built '
    'by the AI engineering team (placeholder). Fix first: step 1 "Collect site spreadsheets".'
)


def _report(session: Any = None, catalogue: Any = CATALOGUE) -> DiscoveryReport:
    return build_report(session or eu_session(), ORG, VOCAB, catalogue)


def _json(report: DiscoveryReport) -> str:
    return report.model_dump_json(by_alias=True)


def _keys(node: Any):
    if isinstance(node, dict):
        for k, v in node.items():  # pyright: ignore[reportUnknownVariableType]
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:  # pyright: ignore[reportUnknownVariableType]
            yield from _keys(v)


def test_ac_20_21_the_process_shows_the_cluster_and_the_task_and_one_off_notes():
    part = _report().process
    cluster = next(f for f in part.fields if f.key == "process.cluster")
    description = VOCAB.taxonomy.by_code("FIN").description  # pyright: ignore[reportOptionalMemberAccess]
    assert cluster.value == f"Finance: {description}"
    assert part.notes == []
    task = ScopeState(verdict=ScopeVerdict(verdict="task", score=1, signals={}))
    assert [n.kind for n in _report(eu_session(scope=task)).process.notes] == ["task"]
    one_off = ScopeState(verdict=ScopeVerdict(verdict="process", score=4, signals={"recurring": False}))
    notes = _report(eu_session(scope=one_off)).process.notes
    assert [n.text for n in notes] == ["This looks like a one-off project, not recurring work."]


def test_ac_20_22_measures_say_not_measured_yet_none_and_the_variation_words():
    profile = load_profile("eu")
    profile["process"]["target_metric"] = {"value": "", "unit": ""}
    fields = {f.key: f.value for f in _report(eu_session(profile)).measures.fields}
    assert fields["process.target_metric"] == "Not measured yet"
    assert fields["process.sensitive_data"] == "None"
    assert fields["process.variation"] == "No — each site sends its own spreadsheet layout"
    assert fields["process.volume"] == "1 per month"
    assert fields["process.baseline_metric"] == "5 working days (estimated)"


def test_ac_20_23_the_step_table_formats_every_cell_and_hides_internals():
    profile = load_profile("eu")
    step3 = profile["process"]["substeps"][2]
    step3["handover"] = ""
    step3["__skipped"] = ["handover"]
    profile["process"]["substeps"][1]["__meta"] = {
        "goal": {"source": "document", "status": "proposed", "documentId": "d1", "quote": "merge", "at": AT}
    }
    part = _report(eu_session(profile)).map
    assert len(part.columns) == 5 and all(len(c.cells) == 13 for c in part.columns)
    cells = {c.key: c.value for col in part.columns for c in col.cells}
    assert cells["process.substeps[1].roles"] == "Site controller (sends the site cost spreadsheet)"
    assert cells["process.substeps[2].exceptions"] == "totals do not match SAP → back to step 1"
    assert cells["process.substeps[1].data"] == "In: site cost spreadsheets. Out: set of site files"
    assert cells["process.substeps[5].approvals"] == "Head of Controlling (waits 1 day)"
    assert cells["process.substeps[2].effort"] == "1 day, each time"
    assert cell_text("decision_type", {"kind": "mix", "evidence": "I judge the outliers"}, skipped=False,
                     proposed=False) == "Mix: I judge the outliers"  # fmt: skip
    assert cells["process.substeps[3].handover"] == "— (skipped)"
    assert cells["process.substeps[2].goal"].endswith(" (proposed, not confirmed)")
    assert part.systems == ["Outlook", "Excel", "SAP S/4HANA"]
    text = _json(_report(eu_session(profile)))
    assert "__meta" not in text and "__skipped" not in text


def test_cell_text_caps_a_runaway_cell_and_shows_an_empty_one_as_a_dash():
    assert cell_text("goal", "x" * 5000, skipped=False, proposed=False) == "x" * 1499 + "…"
    assert cell_text("goal", "", skipped=False, proposed=False) == "—"
    assert cell_text("activities", ["a", "b"], skipped=False, proposed=False) == "a; b"
    assert cell_text("roles", [{"none": True}], skipped=False, proposed=False) == "None"


def test_ac_20_24_a_simplified_map_has_its_caption_and_a_missing_one_its_note():
    assessment = eu_assessment()
    assert assessment.diagram is not None
    assessment.diagram = assessment.diagram.model_copy(update={"simplified": True})
    part = _report(eu_session(assessment=assessment)).map
    assert part.caption is not None and part.caption.startswith("Simplified map built from the steps")
    assessment.diagram = None
    part = _report(eu_session(assessment=assessment)).map
    assert part.note is not None and part.note.text == "The process map could not be drawn."


def test_ac_20_30_a_part_that_fails_to_build_says_so_and_the_rest_is_complete(monkeypatch: pytest.MonkeyPatch):
    def boom(_c: Any) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setattr(report_module, "_feasibility", boom)
    report = _report()
    assert report.feasibility.note is not None and report.feasibility.note.text == "This part could not be built."
    assert (report.feasibility.number, report.feasibility.title) == (6, "AI readiness and feasibility")
    assert any("342 hours a year" in x for x in report.summary.sentences) and report.steps.rows


def test_ac_20_31_display_name_and_messages_never_reach_the_report():
    session = eu_session(
        display_name="ZEBRA-NAME",
        messages=[Message.model_validate({"role": "expert", "text": "ZEBRA-MESSAGE", "at": AT})],
    )
    text = _json(_report(session))
    assert "ZEBRA-NAME" not in text and "ZEBRA-MESSAGE" not in text


def test_ac_20_43_a_thin_session_builds_a_report():
    report = _report(thin_session())
    assert report.cover.process_name == "Tiny" and report.cover.owner == "—"
    assert report.steps.note is not None and report.feasibility.note is not None
    assert report.map.note is not None and len(report.map.columns) == 1
    assert not any("hours a year go into" in x for x in report.summary.sentences)


def test_ac_20_46_part_5_rows_hours_fit_words_route_names_and_evidence():
    assessment = eu_assessment()
    assert assessment.step_assessment is not None
    steps = assessment.step_assessment.steps
    steps[3] = steps[3].model_copy(update={"route_id": None})
    steps[4] = steps[4].model_copy(update={"fit": None})
    part = _report(eu_session(assessment=assessment)).steps
    assert [r.hours for r in part.rows] == ["72 h", "96 h", "72 h", "30 h", "72 h"]
    assert [r.fit_label for r in part.rows] == ["AI assists a person", "AI can do it", "AI can do it",
                                                "AI can do it", "Not assessed"]  # fmt: skip
    assert part.rows[1].route_name == "Custom AI app or agent built by the AI engineering team (placeholder)"
    assert part.rows[3].route_name == "No route"
    assert part.rows[0].evidence_label == "the expert's words"

    failed = eu_assessment()
    failed.step_assessment = None
    failed.outcomes["steps"] = "failed"
    report = _report(eu_session(assessment=failed))
    assert report.steps.note is not None and report.steps.note.text.startswith("The step-by-step assessment")
    assert report.feasibility.note is not None  # no step assessment, no questions (spec 27)
    assert any("342 hours a year" in x for x in report.summary.sentences)


def test_ac_20_48_the_placeholder_note_follows_the_catalogue():
    report = _report()
    assert report.steps.catalogue_note == "Routes come from a placeholder solution list, not the company's real tools."
    real = example_catalogue().model_copy(update={"placeholder": False})
    report = _report(catalogue=real)
    assert report.steps.catalogue_note is None


# --- Report v2 (spec 27) ---------------------------------------------------------------------------


def test_ac_27_9_the_cover_and_six_parts_in_order():
    report = _report()
    assert [p.number for p in report.parts()] == list(range(1, 7))
    assert [p.title for p in report.parts()] == TITLES
    cover = report.cover
    assert (cover.process_name, cover.department, cover.cluster, cover.region) == (
        "Monthly cost review",
        "Finance",
        "FIN · Finance",
        "Europe",
    )
    assert (cover.owner, cover.date, cover.status) == ("Head of Controlling", "20 November 2026", "Mapped")


def test_ac_27_9_summary_figures_come_from_code_and_no_money_is_shown():
    report = _report()
    sentences = report.summary.sentences
    assert sentences[0].startswith("We mapped Monthly cost review in Finance (Finance): 5 steps")
    assert any(x.startswith("AI fit: ") for x in sentences)
    assert "About 342 hours a year go into this process today: a moderate process." in sentences
    assert [r.hours for r in report.steps.rows] == ["72 h", "96 h", "72 h", "30 h", "72 h"]
    text = _json(report)
    assert "€" not in text
    keys = json.dumps(list(_keys(json.loads(text)))).casefold()
    for word in ("cost", "freed", "saving", "valueexpected", "valueconservative", "opportunit"):
        assert word not in keys


def test_ac_27_9_feasibility_blocks_a_to_c():
    part = _report().feasibility
    assert [q.key for q in part.questions] == ["q1", "q2", "q3"]
    assert [q.question for q in part.questions] == [
        "Is this a good AI use case?",
        "A dedicated AI solution, or a general assistant?",
        "Is it worth it?",
    ]
    assert all(q.level_label and q.why for q in part.questions)
    assert [r.label for r in part.readiness] == ["Defined", "Standard", "Data", "Systems", "Rules", "Risk and size"]
    assert len(part.bullets) <= 5
    assert part.gaps.startswith("Gaps: ") and "Sources: the interview only." in part.gaps
    for name in (*DiscoveryReport.model_fields, *FeasibilityPart.model_fields):
        assert not {"score", "verdict", "overall"} & set(name.split("_"))
    words = " ".join(f"{q.level} {q.level_label}" for q in part.questions).casefold().split()
    assert not {"yes", "no", "go", "no-go"} & set(words)  # AC-27.6


def test_ac_27_9_step_rows_carry_the_q1_level():
    rows = _report().steps.rows
    assert all(r.level in ("strong", "partial", "weak", "not_rated") for r in rows)
    assert all(r.level_label for r in rows)


def test_ac_27_9_an_old_assessment_without_questions_still_builds():
    old = eu_assessment()
    old.questions = None
    report = _report(eu_session(assessment=old))
    assert report.feasibility.note is not None and "re-run the assessment" in report.feasibility.note.text
    assert report.summary.note is not None
    assert report.feasibility.readiness and report.summary.sentences

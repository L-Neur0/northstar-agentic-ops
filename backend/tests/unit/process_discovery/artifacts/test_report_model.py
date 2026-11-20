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
    DocumentRecord,
    Message,
    ReadinessDimension,
    ScopeState,
    ScopeVerdict,
)
from app.models.process_discovery_wire import DiscoveryReport, ReadinessPart
from app.services.process_discovery.artifacts import report as report_module
from app.services.process_discovery.artifacts.report import build_report, cell_text
from app.services.process_discovery.artifacts.value import compute_value
from tests.fixtures.assessment.profiles import load_profile, nig_config
from tests.fixtures.assessment_19.cases import example_catalogue
from tests.unit.process_discovery.export.cases import AT, CATALOGUE, ORG, VOCAB, eu_assessment, eu_session, thin_session

TITLES = [
    "At a glance", "The process", "Volume and measures", "Process map and steps", "Step-by-step AI assessment",
    "Recommended route", "Transformation assessment", "Hours a year", "Readiness checklist", "Suggested path",
    "Gaps and sources",
]  # fmt: skip
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


def test_ac_20_18_the_cover_and_eleven_parts_in_order():
    report = _report()
    assert [p.number for p in report.parts()] == list(range(1, 12))
    assert [p.title for p in report.parts()] == TITLES
    cover = report.cover
    assert (cover.product_name, cover.company_name) == (ORG.product_name, ORG.company_name)
    assert (cover.process_name, cover.department, cover.cluster, cover.region) == (
        "Monthly cost review",
        "Finance",
        "FIN · Finance",
        "Europe",
    )
    assert (cover.owner, cover.date, cover.status) == ("Head of Controlling", "20 November 2026", "Mapped")


def test_ac_20_19_every_figure_comes_from_the_value_result_and_no_money_is_shown():
    report = _report()
    assert report.at_a_glance.hours == "About 342 hours a year."
    assert report.potential.totals.hours == "342 h"
    assert [(t.id, t.hours) for t in report.at_a_glance.top] == [("o1", "168 h"), ("o2", "72 h"), ("o3", "30 h")]
    assert [r.hours_per_year for r in report.potential.steps] == ["72 h", "96 h", "72 h", "30 h", "72 h"]
    text = _json(report)
    assert "€" not in text
    keys = json.dumps(list(_keys(json.loads(text)))).casefold()
    for word in ("cost", "freed", "saving", "valueexpected", "valueconservative"):
        assert word not in keys


def _keys(node: Any):
    if isinstance(node, dict):
        for k, v in node.items():  # pyright: ignore[reportUnknownVariableType]
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:  # pyright: ignore[reportUnknownVariableType]
            yield from _keys(v)


def test_ac_20_20_at_a_glance_top_three_route_headline_and_what_to_prepare():
    part = _report().at_a_glance
    assert [t.id for t in part.top] == ["o1", "o2", "o3"]  # not the standardise o4
    assert part.top[0].steps_label == "Steps 1–2"
    assert part.route_headline == HEADLINE
    assert part.prepare[0] == STANDARD_LINE and part.prepare[1] == "Agree one site template"
    assert len(part.prepare) <= 3


def test_ac_20_20_incomplete_hours_name_the_fields_they_need():
    profile = load_profile("eu")
    profile["process"]["substeps"][3]["effort"]["duration"] = "a while"
    assessment = eu_assessment()
    assessment.value = compute_value(profile, assessment.opportunities, nig_config().rates)
    part = _report(eu_session(profile, assessment=assessment)).at_a_glance
    assert part.hours == "" and part.note is not None
    assert part.note.text == "Hours need: Effort of step 4."


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
    assert len(part.columns) == 5 and all(len(c.cells) == 12 for c in part.columns)
    cells = {c.key: c.value for col in part.columns for c in col.cells}
    assert cells["process.substeps[1].roles"] == "Site controller (sends the site cost spreadsheet)"
    assert cells["process.substeps[2].exceptions"] == "totals do not match SAP → back to step 1"
    assert cells["process.substeps[1].data"] == "In: site cost spreadsheets. Out: set of site files"
    assert cells["process.substeps[5].approvals"] == "Head of Controlling (waits 1 day)"
    assert cells["process.substeps[2].effort"] == "1 day, each time"
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


def test_ac_20_25_opportunities_hide_rejected_show_whole_process_and_document_evidence():
    assessment = eu_assessment()
    opps = assessment.opportunities
    opps[1] = opps[1].model_copy(update={"review": "rejected"})
    opps[2] = opps[2].model_copy(update={"substeps": [], "evidence_source": "document",
                                         "evidence_key": "process.substeps[2].goal"})  # fmt: skip
    profile = load_profile("eu")
    profile["process"]["substeps"][1]["__meta"] = {
        "goal": {"source": "document", "status": "confirmed", "documentId": "d1", "quote": "merge", "at": AT}
    }
    doc = DocumentRecord(id="d1", name="Cost review procedure.pdf", kind="pdf", bytes=10, chars=10,
                         uploaded_at=AT, outcome="read")  # fmt: skip
    part = _report(eu_session(profile, assessment=assessment, documents=[doc])).assessment
    assert [o.id for o in part.opportunities] == ["o1", "o3", "o4"]
    o3 = part.opportunities[1]
    assert o3.steps_label == "Whole process" and o3.evidence_label == "from Cost review procedure.pdf"
    assert part.opportunities[0].steps_label == (
        "Steps 1–2: Collect site spreadsheets, Consolidate into the master file"
    )
    assert part.opportunities[0].evidence_label == "the expert's words"

    failed = eu_assessment()
    failed.outcomes["opportunities"] = "failed"
    failed.opportunities = []
    note = _report(eu_session(assessment=failed)).assessment.note
    assert note is not None and note.kind == "failed"
    empty = eu_assessment()
    empty.opportunities = []
    note = _report(eu_session(assessment=empty)).assessment.note
    assert note is not None and note.kind == "empty" and note.text.startswith("No opportunity was found.")


def test_ac_20_26_incomplete_hours_list_the_problems_and_never_show_zero():
    profile = load_profile("eu")
    profile["process"]["substeps"][3]["effort"]["duration"] = "a while"
    assessment = eu_assessment()
    assessment.value = compute_value(profile, assessment.opportunities, nig_config().rates)
    part = _report(eu_session(profile, assessment=assessment)).potential
    assert not part.complete and part.totals.hours == "—"
    assert part.problems == ['Effort of step 4 ("a while") could not be read as a duration.']
    assert part.note is not None and part.note.text == "Total needs: Effort of step 4."
    assert part.parked_line == "Euro value and savings are not shown yet: the method is still being agreed."
    assert _report().potential.parked_line == part.parked_line


def test_ac_20_27_readiness_has_six_rows_with_words_and_no_verdict():
    assessment = eu_assessment()
    assert assessment.readiness is not None
    dims = [d if d.key != "data" else ReadinessDimension(key="data", level="unknown", reason="Not rated.")
            for d in assessment.readiness.dimensions]  # fmt: skip
    assessment.readiness.dimensions = dims
    part = _report(eu_session(assessment=assessment)).readiness
    assert [r.label for r in part.dimensions] == ["Defined", "Standard", "Data", "Systems", "Rules", "Risk and size"]
    assert [r.level_label for r in part.dimensions] == ["High", "Low", "Unknown", "Medium", "High", "High"]
    assert part.dimensions[1].question.startswith("Done the same way")
    assert part.footer == "A guide to what would make the change easier. Not a verdict."
    for name in (*DiscoveryReport.model_fields, *ReadinessPart.model_fields):
        assert not {"score", "verdict", "overall"} & set(name.split("_"))


def test_ac_20_28_the_suggested_path_groups_of_the_eu_example():
    groups = {g.key: g for g in _report().path.groups}
    first = groups["prepare_first"]
    assert first.prepare_lines == [STANDARD_LINE]
    assert [i.opportunity_id for i in first.items] == ["o4", "o1"]
    assert [(i.opportunity_id, i.step_hours) for i in groups["quick_wins"].items] == [("o2", "72 h"), ("o3", "30 h")]
    assert groups["bigger_changes"].items == [] and groups["bigger_changes"].empty_text == "Nothing here."


def test_ac_20_29_gaps_list_open_fields_documents_and_the_closing_note():
    profile = load_profile("eu")
    profile["process"]["target_metric"] = {"value": "", "unit": ""}
    profile["process"]["substeps"][2]["handover"] = ""
    profile["process"]["substeps"][2]["__skipped"] = ["handover"]
    profile["process"]["substeps"][1]["__meta"] = {
        "goal": {"source": "document", "status": "proposed", "documentId": "d1", "quote": "merge", "at": AT}
    }
    profile["process"]["baseline_metric"] = {"value": "", "unit": "", "qualitative": "", "estimated": False}
    session = eu_session(profile, documents=[
        DocumentRecord(id="d1", name="Cost review procedure.pdf", kind="pdf", bytes=10, chars=10,
                       text="SECRET DOCUMENT TEXT", uploaded_at=AT, outcome="read"),
    ])  # fmt: skip
    session.counters.field_asks = {"process.target_metric": 3, "process.baseline_metric": 5}
    part = _report(session).gaps
    statuses = {f.key: f.status for f in part.fields}
    assert statuses["process.target_metric"] == "deferred"
    assert statuses["process.baseline_metric"] == "given_up"
    assert statuses["process.substeps[3].handover"] == "skipped"
    assert statuses["process.substeps[2].goal"] == "proposed"
    assert next(f for f in part.fields if f.key == "process.substeps[3].handover").label == "Hand-over of step 3"
    assert [(d.name, d.outcome) for d in part.documents] == [("Cost review procedure.pdf", "read")]
    assert part.closing_note.startswith("This is a first assessment from one expert's account in a short "
                                        "interview, with 1 document.")  # fmt: skip
    assert "SECRET DOCUMENT TEXT" not in _json(_report(session))
    assert ", with" not in _report().gaps.closing_note


def test_ac_20_30_a_part_that_fails_to_build_says_so_and_the_rest_is_complete(monkeypatch: pytest.MonkeyPatch):
    def boom(_c: Any) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setattr(report_module, "_potential", boom)
    report = _report()
    assert report.potential.note is not None and report.potential.note.text == "This part could not be built."
    assert (report.potential.number, report.potential.title) == (8, "Hours a year")
    assert report.at_a_glance.hours == "About 342 hours a year." and len(report.readiness.dimensions) == 6


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
    assert report.steps.note is not None and report.route.note is not None and report.assessment.note is not None
    assert report.map.note is not None and len(report.map.columns) == 1
    assert report.potential.totals.hours == "—"


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
    assert report.route.note is not None and report.route.note.text.startswith("No recommended route")
    assert report.at_a_glance.route_headline is None and report.at_a_glance.hours == "About 342 hours a year."


def test_ac_20_47_part_6_groups_of_the_eu_example():
    part = _report().route
    assert part.headline == HEADLINE
    groups = {g.key: [i.number for i in g.items] for g in part.groups}
    assert groups == {"start_with": [2, 3], "later": [5, 4], "fix_first": [1]}
    assert part.groups[0].items[0].route_name.startswith("Custom AI app")
    assert part.prepare == ["A written rule for each decision", "Connector access to the systems involved",
                            "A sponsor and an implementation brief"]  # fmt: skip


def test_ac_20_48_the_placeholder_note_follows_the_catalogue():
    report = _report()
    assert report.steps.catalogue_note == report.route.catalogue_note
    assert report.steps.catalogue_note == "Routes come from a placeholder solution list, not the company's real tools."
    real = example_catalogue().model_copy(update={"placeholder": False})
    report = _report(catalogue=real)
    assert report.steps.catalogue_note is None and report.route.catalogue_note is None

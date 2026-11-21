"""Unit tests for the PDF of the discovery report, `export/report_pdf.py` (spec 20 §3.4).

Why: the PDF must render for every session (long answers, odd characters, a broken stored map),
carry the brand from configuration, and never show money while R5 is parked; and a layout problem
must give a short note document, never an error page.
What: `write_pdf` on the EU report (text checked with `pypdf`), on edited copies (special
characters, long step and question reasons (spec 27), a 10,000-character cover field, a malformed map, a drawing that
raises, a forced `LayoutError`, a thin session); the step-table planner (`grid_pages`) and the map
page (`diagram_page`) directly.
Must not: call a model or re-test the report model (see `test_report_model.py`).
Covers AC-20.32 to AC-20.39, AC-20.43 (PDF side).
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from pypdf import PdfReader
from reportlab.platypus import PageBreak, Paragraph, Spacer

from app.models.process_discovery_wire import DiscoveryReport, ReportField, StepColumn
from app.services.process_discovery.artifacts.report import build_report
from app.services.process_discovery.export import report_pdf
from app.services.process_discovery.export.branding import Brand
from app.services.process_discovery.export.report_pdf import grid_pages, write_pdf
from tests.fixtures.assessment.profiles import load_profile
from tests.unit.process_discovery.artifacts.test_report_model import TITLES
from tests.unit.process_discovery.export.cases import CATALOGUE, ORG, VOCAB, eu_assessment, eu_session, thin_session

BRAND = Brand.from_config(ORG)


def _report(session: Any = None) -> DiscoveryReport:
    return build_report(session or eu_session(), ORG, VOCAB, CATALOGUE)


def _reader(pdf: bytes) -> PdfReader:
    assert pdf.startswith(b"%PDF")
    return PdfReader(io.BytesIO(pdf))


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in _reader(pdf).pages)


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_ac_20_32_the_eu_pdf_holds_every_part_the_hours_and_no_euro():
    pdf = write_pdf(_report(), BRAND)
    text = _flat(_text(pdf))
    assert "Monthly cost review" in text
    for number, title in enumerate(TITLES, start=1):
        assert f"{number}. {title}" in text
    assert "342 h" in text or "72 h" in text
    assert "About 342 hours a year go into this process today" in text  # spec 27 §3.5
    assert "Is this a good AI use case?" in text and "Before starting and risks" in text or "Readiness" in text
    assert "€" not in text
    reader = _reader(pdf)
    assert reader.metadata is not None and reader.metadata.title == "Monthly cost review"
    assert not reader.metadata.get("/Author")


def test_ac_20_32_the_map_and_the_step_table_are_on_landscape_pages():
    reader = _reader(write_pdf(_report(), BRAND))
    shapes = [(float(p.mediabox.width) > float(p.mediabox.height), p.extract_text()) for p in reader.pages]
    assert not shapes[0][0]  # the cover is portrait
    landscape_texts = [t for wide, t in shapes if wide]
    assert any("Process map" in t for t in landscape_texts)
    assert any("Step table — steps 1–4 of 5 (page 1 of 2)" in t for t in landscape_texts)
    assert not shapes[-1][0]  # back to portrait for the rest


def test_ac_20_33_the_cover_footer_and_banner_follow_the_config():
    org = ORG.model_copy(update={"product_name": "Process Finder", "company_name": "Example Works",
                                 "branding": ORG.branding.model_copy(update={"primary_colour": "#AA0000"})})  # fmt: skip
    pdf = write_pdf(build_report(eu_session(), org, VOCAB, CATALOGUE), Brand.from_config(org))
    text = _text(pdf)
    assert "Process Finder · Discovery report · Monthly cost review" in text
    assert "Example Works" in text and ORG.company_name not in text
    assert pdf != write_pdf(_report(), BRAND)


def test_ac_20_34_special_characters_emoji_and_chinese_render():
    profile = load_profile("eu")
    profile["process"]["name"] = "R&D <Special> process 发票 🚀"
    profile["process"]["trigger"] = "Amount < 500 & no manager available ✓"
    profile["process"]["substeps"][0]["activities"] = ["Check A & B < C", "Prüfung — 发票"]
    pdf = write_pdf(_report(eu_session(profile)), BRAND)
    text = _text(pdf)
    assert "R&D <Special> process" in text and "Amount < 500 & no manager available" in text


def _columns(count: int, rows: int, text: str) -> tuple[list[StepColumn], list[str]]:
    labels = [f"Field {i}" for i in range(rows)]
    columns = [StepColumn(number=n, name=f"S{n}",
                          cells=[ReportField(key=f"k{i}", label=labels[i], value=text) for i in range(rows)])
               for n in range(1, count + 1)]  # fmt: skip
    return columns, labels


def _tables(flowables: list[Any]) -> list[Any]:
    return [f for f in flowables if not isinstance(f, (Paragraph, PageBreak, Spacer))]


def test_ac_20_35_a_table_that_fits_is_one_table():
    columns, labels = _columns(2, 3, "ok")
    assert len(grid_pages(columns, labels, 500, 800, BRAND)) == 1


def test_ac_20_35_the_chunk_narrows_before_rows_are_split():
    text = ("This is a fairly long sentence of free text describing the field content in detail so that it "
            "wraps onto several lines. " * 2).strip()  # fmt: skip
    columns, labels = _columns(4, 12, text)
    flowables = grid_pages(columns, labels, 700, 400, BRAND)
    captions = [f.getPlainText() for f in flowables if isinstance(f, Paragraph)]
    assert captions == ["Step table — steps 1–2 of 4 (page 1 of 2)", "Step table — steps 3–4 of 4 (page 2 of 2)"]
    assert len(_tables(flowables)) == 2


def test_ac_20_35_rows_split_rather_than_run_off_the_page():
    columns, labels = _columns(2, 4, "x")
    flowables = grid_pages(columns, labels, 500, 1, BRAND)
    assert len(_tables(flowables)) == 4  # one row per table, nothing dropped
    assert len([f for f in flowables if isinstance(f, PageBreak)]) == 3


def test_ac_20_36_long_assessment_text_flows_across_pages():
    """AC-20.36, as amended by spec 27: long step reasons and question reasons flow across pages."""
    assessment = eu_assessment()
    assert assessment.step_assessment is not None and assessment.questions is not None
    capped = ("Evidence & <detail>. " * 30)[:600]  # MAX_REASON_CHARS: grounding caps a step reason at 600
    assessment.step_assessment.steps = [
        r.model_copy(update={"reason": capped}) for r in assessment.step_assessment.steps
    ]
    long = "Evidence & <detail>. " * 75
    assessment.questions.q1 = assessment.questions.q1.model_copy(update={"reasons": [long] * 6})
    reader = _reader(write_pdf(_report(eu_session(assessment=assessment)), BRAND))
    assert len(reader.pages) > 4 and "could not be laid out" not in _text(
        write_pdf(_report(eu_session(assessment=assessment)), BRAND)
    )


def test_ac_20_37_a_runaway_cover_field_still_renders_the_full_report():
    profile = load_profile("eu")
    words = ("Finance Operations " * 600)[:10_000]
    profile["department"] = words
    profile["process"]["process_owner"]["role"] = words
    pdf = write_pdf(_report(eu_session(profile)), BRAND)
    reader = _reader(pdf)
    assert len(reader.pages) > 1
    assert "This report could not be laid out" not in _text(pdf)


def test_ac_20_38_a_layout_error_gives_a_one_page_note_document(monkeypatch: pytest.MonkeyPatch):
    from reportlab.platypus import BaseDocTemplate
    from reportlab.platypus.doctemplate import LayoutError

    calls = {"n": 0}
    real_build = BaseDocTemplate.build

    def flaky(self: Any, flowables: Any, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise LayoutError("too tall")
        return real_build(self, flowables, *args, **kwargs)

    monkeypatch.setattr(BaseDocTemplate, "build", flaky)
    pdf = write_pdf(_report(), BRAND)
    assert calls["n"] == 2 and len(_reader(pdf).pages) == 1
    assert "could not be laid out in full" in _flat(_text(pdf))


@pytest.mark.parametrize("broken", [{"nodes": "x"}, {"lanes": None, "nodes": [None, 3], "flows": [{"source": 1}]}])
def test_ac_20_39_a_malformed_stored_map_gives_the_note_and_the_pdf_renders(broken: dict[str, Any]):
    report = _report()
    report.map.diagram = report.map.diagram.model_construct(**broken)  # pyright: ignore[reportOptionalMemberAccess]
    text = _flat(_text(write_pdf(report, BRAND)))
    assert "The process map could not be drawn." in text


def test_ac_20_39_a_drawing_that_raises_gives_the_note(monkeypatch: pytest.MonkeyPatch):
    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("drawing bug")

    monkeypatch.setattr(report_pdf.bpmn, "build_drawing", boom)
    text = _flat(_text(write_pdf(_report(), BRAND)))
    assert "The process map could not be drawn." in text and "6. AI readiness and feasibility" in text


def test_ac_20_39_the_map_page_never_asks_for_a_non_positive_height(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, float] = {}
    real = report_pdf.bpmn.build_drawing

    def spy(diagram: Any, width: float, height: float, brand: Brand, name: str = "") -> Any:
        seen["height"] = height
        return real(diagram, width, height, brand, name)

    monkeypatch.setattr(report_pdf.bpmn, "build_drawing", spy)
    report_pdf.diagram_page(_report().map, BRAND, 500, 1)
    assert seen["height"] >= report_pdf.MIN_DIAGRAM_HEIGHT_MM * report_pdf.mm


def test_a_simplified_map_prints_its_caption():
    assessment = eu_assessment()
    assessment.diagram = assessment.diagram.model_copy(update={"simplified": True})  # pyright: ignore[reportOptionalMemberAccess]
    text = _flat(_text(write_pdf(_report(eu_session(assessment=assessment)), BRAND)))
    assert "Simplified map built from the steps" in text


def test_ac_20_43_a_thin_session_renders():
    text = _flat(_text(write_pdf(_report(thin_session()), BRAND)))
    assert "Tiny" in text and "6. AI readiness and feasibility" in text

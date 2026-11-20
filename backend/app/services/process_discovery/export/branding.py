"""The report's look in reportlab: the company brand from configuration on a fixed light palette (spec 20 §3.4).

Why: product rule 8, company specifics are configuration. The PDF must carry the product name,
the company name, the colours and the logo of whoever runs the tool, and changing
`organisation.yaml` must change the PDF with no code change. Everything that draws (the cover,
section headings, cards, tables, the footer, the map) takes its colours and styles from here, so
no hex value or company word is repeated in another module.
What: `Brand.from_config(org, config_dir)` (product and company name, primary and accent colours,
optional logo resolved against the config folder; a missing or unreadable logo means a text-only
banner, logged once); the neutral light palette; paragraph styles; the drawn banner, the
accent-bar section heading, the card, and the per-page footer callback.
Must not: hold a company name, a brand colour or a closing call-to-action; read the session.
Spec 20 §3.4 (Branding); AC-20.33.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Spacer, Table, TableStyle

from app.core.config import Organisation

logger = logging.getLogger("app.export")

# --- the fixed light palette ------------------------------------------------------------------------
PAGE = colors.white
TEXT = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#5B6573")
BORDER = colors.HexColor("#D5DAE1")
CARD = colors.HexColor("#F4F6F8")

PAGE_SIZE = A4
BANNER_HEIGHT = 18 * mm
FOOTER_NAME_CHARS = 60
_logged_logos: set[str] = set()


@dataclass(frozen=True)
class Brand:
    product_name: str
    company_name: str
    primary: Color
    accent: Color
    logo: Path | None = None
    styles: dict[str, ParagraphStyle] = field(default_factory=lambda: {}, compare=False, repr=False)

    @classmethod
    def from_config(cls, org: Organisation, config_dir: Path | None = None) -> Brand:
        """The brand of `organisation.yaml`; the logo only when the file can be read."""
        logo: Path | None = None
        raw = org.branding.logo_path
        if raw:
            path = Path(raw) if Path(raw).is_absolute() or config_dir is None else Path(config_dir) / raw
            try:
                from reportlab.lib.utils import ImageReader

                ImageReader(str(path)).getSize()
                logo = path
            except Exception:
                if str(path) not in _logged_logos:
                    _logged_logos.add(str(path))
                    logger.warning("report_logo_unreadable", extra={"path": str(path)})
        primary = colors.HexColor(org.branding.primary_colour)
        accent = colors.HexColor(org.branding.accent_colour)
        return cls(org.product_name, org.company_name, primary, accent, logo, _styles(primary))

    def style(self, name: str) -> ParagraphStyle:
        return (self.styles or _styles(self.primary))[name]


def _styles(primary: Color) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("ReportTitle", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=TEXT),
        "part": ParagraphStyle("ReportPart", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=primary,
                               spaceBefore=6 * mm, spaceAfter=3 * mm),
        "body": ParagraphStyle("ReportBody", fontName="Helvetica", fontSize=10, leading=13, textColor=TEXT,
                               spaceAfter=2 * mm),
        "muted": ParagraphStyle("ReportMuted", fontName="Helvetica-Oblique", fontSize=10, leading=13,
                                textColor=MUTED, spaceAfter=2 * mm),
        "label": ParagraphStyle("ReportLabel", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=TEXT,
                                spaceBefore=2 * mm, spaceAfter=1 * mm),
        "cover_meta": ParagraphStyle("ReportCoverMeta", fontName="Helvetica", fontSize=11, leading=16,
                                     textColor=MUTED),
        "card_title": ParagraphStyle("ReportCardTitle", fontName="Helvetica-Bold", fontSize=18, leading=22,
                                     textColor=primary),
        "cell": ParagraphStyle("ReportCell", fontName="Helvetica", fontSize=8, leading=10, textColor=TEXT),
        "cell_head": ParagraphStyle("ReportCellHead", fontName="Helvetica-Bold", fontSize=8, leading=10,
                                    textColor=primary),
    }  # fmt: skip


class _Banner(Flowable):
    """A primary-colour band with the product name and the company name, and the logo when configured."""

    def __init__(self, brand: Brand, width: float, height: float = BANNER_HEIGHT) -> None:
        super().__init__()
        self.brand, self.width, self.height = brand, width, height

    def draw(self) -> None:
        canvas: Any = self.canv
        canvas.setFillColor(self.brand.primary)
        canvas.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        x = 4 * mm
        if self.brand.logo is not None:
            size = self.height - 4 * mm
            canvas.drawImage(str(self.brand.logo), x, 2 * mm, width=size, height=size, preserveAspectRatio=True,
                             mask="auto")  # fmt: skip
            x += size + 3 * mm
        canvas.setFillColor(PAGE)
        canvas.setFont("Helvetica-Bold", 14)
        canvas.drawString(x, self.height / 2 - 1, self.brand.product_name)
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, self.height / 2 - 12, self.brand.company_name)


def banner_flowable(brand: Brand, width: float) -> Flowable:
    return _Banner(brand, width)


class _SectionHeading(Flowable):
    """A primary accent bar, the heading in bold, a thin rule beneath."""

    def __init__(self, brand: Brand, text: str, width: float) -> None:
        super().__init__()
        self.brand, self.text, self.width, self.height = brand, text, width, 8 * mm

    def draw(self) -> None:
        canvas: Any = self.canv
        canvas.saveState()
        canvas.setFillColor(self.brand.primary)
        canvas.rect(0, 1.5 * mm, 1 * mm, 5 * mm, fill=1, stroke=0)
        canvas.setFillColor(TEXT)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(4 * mm, 2.7 * mm, self.text)
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.4)
        canvas.line(0, 0, self.width, 0)
        canvas.restoreState()


def section_heading_flowables(brand: Brand, text: str, width: float) -> list[Flowable]:
    """A heading as `[Spacer, heading, Spacer]`, so every section gets the same room above and below."""
    return [Spacer(1, 4 * mm), _SectionHeading(brand, text, width), Spacer(1, 3 * mm)]


def card_flowable(brand: Brand, content: Any, width: float) -> Table:
    """`content` in a light card with a primary top bar: notes, the cover cards."""
    table = Table([[content]], colWidths=[width])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEABOVE", (0, 0), (-1, 0), 2, brand.primary),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
    ]))  # fmt: skip
    return table


def table_style(brand: Brand) -> TableStyle:
    """The data tables: accent rules, a card-coloured header row, cells aligned to the top."""
    return TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, brand.accent),
        ("BACKGROUND", (0, 0), (-1, 0), CARD),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ])  # fmt: skip


def page_decoration(brand: Brand, footer_text: str) -> Any:
    """The `onPage` callback: a thin primary rule and the footer, "<text>" left and "Page N" right.

    Reads the page size from the canvas (set by the active template), not the document, because the
    report mixes landscape pages in.
    """

    def decorate(canvas: Any, _doc: Any) -> None:
        width, _height = canvas._pagesize  # pyright: ignore[reportPrivateUsage]
        canvas.saveState()
        canvas.setStrokeColor(brand.primary)
        canvas.setLineWidth(0.6)
        canvas.line(15 * mm, 14 * mm, width - 15 * mm, 14 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(15 * mm, 10 * mm, footer_text)
        canvas.drawRightString(width - 15 * mm, 10 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    return decorate

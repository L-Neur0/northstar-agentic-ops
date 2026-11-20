"""Unit tests for the report brand, `export/branding.py` (spec 20 §3.4 Branding).

Why: product rule 8, company specifics are configuration: the PDF's names, colours and logo must
come from `organisation.yaml`, a broken logo must not break the report, and no company word or
brand colour may hide in the code.
What: `Brand.from_config` with the NIG config, with changed colours and names, with a missing and
a real logo; a grep over the export and report modules for the configured company strings.
Must not: edit the real configuration (tests change their own copy).
Covers AC-20.33.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors

from app.services.process_discovery.export.branding import Brand
from tests.unit.process_discovery.export.cases import ORG

ENGINE = Path(__file__).resolve().parents[4] / "app" / "services" / "process_discovery"


def _org(**branding: object):
    return ORG.model_copy(update={"branding": ORG.branding.model_copy(update=branding)})


def test_ac_20_33_the_brand_comes_from_the_organisation_config():
    brand = Brand.from_config(ORG)
    assert (brand.product_name, brand.company_name) == (ORG.product_name, ORG.company_name)
    assert brand.primary == colors.HexColor(ORG.branding.primary_colour)
    assert brand.accent == colors.HexColor(ORG.branding.accent_colour)
    assert brand.logo is None


def test_ac_20_33_a_missing_logo_means_a_text_only_banner(tmp_path: Path):
    assert Brand.from_config(_org(logo_path="nowhere.png"), tmp_path).logo is None
    (tmp_path / "bad.png").write_bytes(b"not an image")
    assert Brand.from_config(_org(logo_path="bad.png"), tmp_path).logo is None


def test_ac_20_33_a_readable_logo_is_resolved_against_the_config_folder(tmp_path: Path):
    from PIL import Image

    Image.new("RGB", (8, 8), "white").save(tmp_path / "logo.png")
    assert Brand.from_config(_org(logo_path="logo.png"), tmp_path).logo == tmp_path / "logo.png"


def test_ac_20_33_no_company_string_or_brand_colour_is_in_the_code():
    words = {ORG.company_name, ORG.branding.primary_colour.lower(), ORG.branding.accent_colour.lower(), "NorthStar"}
    files = [*(ENGINE / "export").glob("*.py"), ENGINE / "artifacts" / "report.py", ENGINE / "artifacts" / "assess.py"]
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        assert not [w for w in words if w.lower() in text], path.name

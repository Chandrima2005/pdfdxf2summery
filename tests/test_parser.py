import pytest

from cad_copilot.parsing.dxf_parser import parse_dxf, to_compact_text
from cad_copilot.parsing.pdf_parser import parse_pdf
from cad_copilot.parsing.render import render_png


def test_units_and_layers(samples, manifests):
    d = parse_dxf(samples / "plan-001.dxf")
    assert d.units == "mm"
    assert set(manifests["plan-001"]["layers"]) <= set(d.layers)


def test_room_polylines_match_manifest(samples, manifests):
    for name, m in manifests.items():
        if m["kind"] != "floorplan":
            continue
        df = parse_dxf(samples / m["file"]).entities
        rooms = df[(df.layer == "ROOMS") & df.closed]
        assert sorted(round(a / 1e6, 3) for a in rooms.area) == sorted(r["area_m2"] for r in m["rooms"])


def test_dimensions_are_measured(samples, manifests):
    df = parse_dxf(samples / "plan-002.dxf").entities
    dims = sorted(df[df.type == "DIMENSION"].measurement)
    m = manifests["plan-002"]
    assert dims == sorted([m["width"], m["depth"]])


def test_render_returns_png(samples):
    assert render_png(samples / "brk-001.dxf", dpi=40)[:4] == b"\x89PNG"


def test_compact_text_truncates(samples):
    txt = to_compact_text(parse_dxf(samples / "plan-001.dxf"), max_chars=200)
    assert txt.startswith("UNITS: mm") and txt.endswith("[truncated]")


def test_pdf_pages(samples):
    pages = parse_pdf(samples / "building_spec.pdf")
    assert len(pages) >= 3 and any("1100 mm" in p.text for p in pages)


def test_bad_file_raises(tmp_path):
    bad = tmp_path / "bad.dxf"
    bad.write_text("not a dxf")
    with pytest.raises(Exception):
        parse_dxf(bad)


def _scanned_copy(src, dst):
    import pymupdf
    out = pymupdf.open()
    for pg in pymupdf.open(str(src)):
        page = out.new_page(width=pg.rect.width, height=pg.rect.height)
        page.insert_image(page.rect, pixmap=pg.get_pixmap(dpi=60))
    out.save(str(dst))
    return dst


def test_scanned_pdf_needs_ocr(samples, tmp_path):
    import pytest
    from cad_copilot.parsing.pdf_parser import ScannedPdfError
    scan = _scanned_copy(samples / "building_spec.pdf", tmp_path / "scan.pdf")
    with pytest.raises(ScannedPdfError):
        parse_pdf(scan)
    pages = parse_pdf(scan, ocr=lambda png: "3.2 Corridor width not less than 1100 mm")
    assert pages and pages[0].page == 1 and "1100" in pages[0].text

import math

from cad_copilot.parsing.dxf_parser import parse_dxf
from cad_copilot.tools.geometry_tools import TOOL_SCHEMAS, DrawingTools


def tools_for(samples, name):
    return DrawingTools(parse_dxf(samples / name))


def test_every_schema_has_a_method():
    for s in TOOL_SCHEMAS:
        assert callable(getattr(DrawingTools, s["name"]))


def test_counts(samples, manifests):
    m = manifests["plan-001"]
    t = tools_for(samples, "plan-001.dxf")
    assert t.count_entities(layer="WINDOWS")["count"] == m["counts"]["windows"]
    assert t.block_inserts(block_name="DOOR")["count"] == m["counts"]["doors"]
    assert t.labeled_regions(label_contains="BEDROOM")["count"] == m["counts"]["bedrooms"]


def test_doors_map_to_rooms(samples, manifests):
    for key in ("plan-001", "plan-002", "plan-003"):
        m = manifests[key]
        t = tools_for(samples, m["file"])
        got = {i["in_region"]: i["scale"] for i in t.block_inserts()["inserts"]}
        assert got == {r["name"]: r["door_width"] for r in m["rooms"]}


def test_corridor_width_and_walls(samples, manifests):
    m = manifests["plan-004"]
    t = tools_for(samples, "plan-004.dxf")
    assert t.labeled_regions(label_contains="CORRIDOR")["regions"][0]["min_side"] == m["corridor_width"]
    assert math.isclose(t.total_length(layer="WALLS")["total_length"], m["total_wall_length"])
    assert t.layer_extents("WALLS")["width"] == m["width"]


def test_windows_per_room(samples, manifests):
    m = manifests["plan-002"]
    got = {r["label"]: r["count"] for r in tools_for(samples, "plan-002.dxf").count_per_region("WINDOWS", "ROOMS")["regions"]}
    assert got == {r["name"]: len(r["windows"]) for r in m["rooms"]}


def test_holes(samples, manifests):
    m = manifests["brk-001"]
    t = tools_for(samples, "brk-001.dxf")
    assert t.circles(layer="HOLES")["count"] == len(m["holes"])
    d = m["holes"][0]["d"]
    assert t.count_entities(entity_type="CIRCLE", diameter=d)["count"] == sum(h["d"] == d for h in m["holes"])


def test_errors_are_returned_not_raised(samples):
    t = tools_for(samples, "plan-001.dxf")
    assert "error" in t.call("does_not_exist")
    assert "error" in t.call("count_entities", {"nonsense": 1})
    assert "error" in t.call("_filter")

"""Connectivity and schematic tools, checked against the generator's ground truth."""
from cad_copilot.parsing.dxf_parser import parse_dxf
from cad_copilot.tools.geometry_tools import DrawingTools


def test_domain_detection(samples):
    assert parse_dxf(samples / "db-001.dxf").summary()["domain"] == "electrical/electronic schematic"
    assert parse_dxf(samples / "ckt-001.dxf").summary()["domain"] == "electrical/electronic schematic"
    assert parse_dxf(samples / "plan-001.dxf").summary()["domain"] == "building floor plan"
    assert parse_dxf(samples / "brk-001.dxf").summary()["domain"] == "mechanical part"


def test_attributes_are_parsed(samples, manifests):
    df = parse_dxf(samples / "db-002.dxf").entities
    mcbs = df[(df.type == "INSERT") & (df.block == "MCB")]
    got = {a["TAG"]: int(a["RATING_A"]) for a in mcbs.attribs}
    assert got == {c["tag"]: c["rating_a"] for c in manifests["db-002"]["circuits"]}


def test_every_circuit_feeds_the_right_things(samples, manifests):
    for key in ("db-001", "db-002", "db-003", "db-004"):
        m = manifests[key]
        t = DrawingTools(parse_dxf(samples / m["file"]))
        assert t.net.source == "SUPPLY"
        for c in m["circuits"]:
            d = t.downstream(c["tag"])
            expected = {l["tag"] for l in c["loads"]} | {c["cable_tag"]} | ({c["rcd"]["tag"]} if c["rcd"] else set())
            assert {x["tag"] for x in d["downstream"]} == expected, (key, c["tag"])
            assert d["total_LOAD_W"] == c["load_w"]


def test_circuits_are_not_downstream_of_each_other(samples):
    t = DrawingTools(parse_dxf(samples / "db-001.dxf"))
    ds = {x["tag"] for x in t.downstream("C1")["downstream"]}
    assert not any(tag.startswith("C") and tag[1:].isdigit() for tag in ds)
    assert "C2" not in ds and "MAIN" not in ds


def test_electronic_neighbours(samples, manifests):
    for key in ("ckt-001", "ckt-002"):
        m = manifests[key]
        t = DrawingTools(parse_dxf(samples / m["file"]))
        for tag, expected in m["neighbours"].items():
            assert sorted(x["tag"] for x in t.connected_to(tag)["connected"]) == expected, (key, tag)


def test_bom_and_sums(samples, manifests):
    m = manifests["db-003"]
    t = DrawingTools(parse_dxf(samples / "db-003.dxf"))
    assert t.sum_attribute("LENGTH_M", "CABLE")["total"] == m["total_cable_length_m"]
    bom = t.bill_of_materials()
    assert bom["total_components"] == len(t.net.components)
    assert t.components(component_type="SOCKET")["count"] == m["counts"]["sockets"]


def test_path_and_unknown_tags(samples):
    t = DrawingTools(parse_dxf(samples / "db-001.dxf"))
    assert t.path_between("SUPPLY", "C1")["path"][:2] == ["SUPPLY", "MAIN"]
    assert "error" in t.component_details("NOPE")
    assert "error" in t.downstream("NOPE")

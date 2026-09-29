"""Build the benchmark from the generator's manifests (independent ground truth).

Each compute template has a *canonical* phrasing and a *paraphrase*; one is
picked per drawing at random. Keyword rules tend to handle the canonical form
and miss the paraphrase, which is exactly what the eval should expose.

    python -m cad_copilot.eval.generate_questions --samples data/samples --out data/eval/questions.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import random
from pathlib import Path

from cad_copilot.spec_content import ELECTRICAL_RULES, HABITABLE_TYPES, RULES, SPECS

PLAN_TEMPLATES = [
    ("rooms", ["How many rooms are in this plan?", "What's the total number of rooms shown on the drawing?"]),
    ("doors", ["How many doors are there in the plan?", "What is the door count for this layout?"]),
    ("windows", ["How many windows does the drawing have?", "What's the window total for this plan?"]),
    ("bedrooms", ["How many bedrooms are there?", "How many sleeping rooms does this unit have?"]),
    ("room_area", ["What is the area of the {R} in square metres?", "What floor space does the {R} cover, in square metres?"]),
    ("corridor", ["What is the width of the corridor in mm?", "How wide is the hallway, in millimetres?"]),
    ("door_width", ["What is the width of the door into the {R} in mm?", "How wide is the {R}'s door opening in millimetres?"]),
    ("walls", ["What is the total length of walls in metres?", "Add up all the wall lines: how many metres is that?"]),
    ("bldg_width", ["What is the overall width of the building in mm?", "How wide is the building footprint from end to end, in mm?"]),
    ("largest", ["Which room is the largest?", "Which space has the most floor area, not counting the corridor?"]),
]

COMPLIANCE_TEMPLATES = [
    ("corridor", "Does the corridor meet the minimum width required by the spec?"),
    ("doors", "Do all doors meet the minimum clear width in the specification?"),
    ("areas", "Do all rooms meet the minimum floor areas in the spec?"),
    ("windows", "Does every habitable room have a window as the spec requires?"),
]

BOARD_TEMPLATES = [
    ("circuits", ["How many circuits are in this distribution board?", "How many outgoing ways does the board feed?"]),
    ("sockets", ["How many sockets are on the drawing?", "What's the socket outlet total?"]),
    ("lights", ["How many lights are there?", "How many luminaires does the schematic show?"]),
    ("rating", ["What is the rating of breaker {C} in amps?", "{C} is protected at how many amps?"]),
    ("load", ["What is the total connected load of circuit {C} in watts?", "How much power do the loads fed by {C} draw altogether, in W?"]),
    ("cable", ["What cable size feeds circuit {C} in sq mm?", "Which conductor cross-section is used on {C}'s run, in sq mm?"]),
    ("cable_len", ["What is the total cable length in metres?", "Summing every cable run, how many metres of cable are there?"]),
    ("highest", ["Which circuit has the highest connected load?", "Which final circuit draws the most power?"]),
    ("main", ["What is the main switch rating in amps?", "How big is the incoming isolator, in amps?"]),
]

CIRCUIT_TEMPLATES = [
    ("resistors", ["How many resistors are in the circuit?", "What's the resistor count?"]),
    ("capacitors", ["How many capacitors are there?", "How many caps does the board use?"]),
    ("r_value", ["What is the value of {R} in ohms?", "How many ohms is {R}?"]),
    ("neighbours", ["How many components are directly connected to {X}?", "How many parts share a connection with {X}?"]),
    ("components", ["How many components are on the schematic?", "What is the total part count?"]),
]

ELECTRICAL_COMPLIANCE = [
    ("breaker_cable", "Are all breakers correctly sized for their cables according to the spec?"),
    ("load", "Do all circuits stay within the connected load limit in the specification?"),
    ("rcd", "Are all socket circuits protected by an RCD as the spec requires?"),
    ("lighting", "Do all lighting circuits meet the breaker rating limit in the spec?"),
    ("length", "Do all cable runs meet the maximum length in the specification?"),
]

VISUAL_QUESTIONS = [
    "Where is the kitchen located relative to the corridor?",
    "Which rooms are adjacent to the living room?",
    "Describe the overall layout of the plan.",
    "Is the bathroom on the left or the right side of the plan?",
    "What is next to BEDROOM 1?",
    "Which side of the corridor are most bedrooms on?",
]


VISUAL_ELECTRICAL = [
    "Where is the main switch drawn relative to the busbar?",
    "Which circuit is drawn furthest to the right?",
    "Describe the layout of this single line diagram.",
]


def _plan_answer(key: str, m: dict, room: dict):
    rooms = m["rooms"]
    if key == "rooms":
        return len(rooms), "number"
    if key == "doors":
        return m["counts"]["doors"], "number"
    if key == "windows":
        return m["counts"]["windows"], "number"
    if key == "bedrooms":
        return m["counts"]["bedrooms"], "number"
    if key == "room_area":
        return room["area_m2"], "number"
    if key == "corridor":
        return m["corridor_width"], "number"
    if key == "door_width":
        return room["door_width"], "number"
    if key == "walls":
        return round(m["total_wall_length"] / 1000, 3), "number"
    if key == "bldg_width":
        return m["width"], "number"
    if key == "largest":
        top = max(rooms, key=lambda r: r["area_m2"])
        ties = [r["name"] for r in rooms if math.isclose(r["area_m2"], top["area_m2"])]
        return "|".join(ties), "label"
    raise KeyError(key)


def _compliance_truth(key: str, m: dict) -> str:
    rooms = m["rooms"]
    if key == "corridor":
        ok = m["corridor_width"] >= RULES["corridor_min_width_mm"]
    elif key == "doors":
        ok = all(r["door_width"] >= (RULES["bath_door_min_width_mm"] if r["name"] == "BATH" else RULES["door_min_width_mm"])
                 for r in rooms)
    elif key == "areas":
        ok = all(r["area_m2"] >= RULES["min_area_m2"].get(r["name"].split()[0], 0) for r in rooms)
    else:
        ok = all(r["windows"] for r in rooms if r["name"].split()[0] in HABITABLE_TYPES)
    return "PASS" if ok else "FAIL"


def _board_answer(key: str, m: dict, c: dict):
    cs = m["circuits"]
    if key == "circuits":
        return m["counts"]["circuits"], "number"
    if key == "sockets":
        return m["counts"]["sockets"], "number"
    if key == "lights":
        return m["counts"]["lights"], "number"
    if key == "rating":
        return c["rating_a"], "number"
    if key == "load":
        return c["load_w"], "number"
    if key == "cable":
        return c["cable_size"], "number"
    if key == "cable_len":
        return m["total_cable_length_m"], "number"
    if key == "highest":
        top = max(x["load_w"] for x in cs)
        return "|".join(x["tag"] for x in cs if x["load_w"] == top), "label"
    if key == "main":
        return m["main_rating_a"], "number"
    raise KeyError(key)


def _electrical_truth(key: str, m: dict) -> str:
    R = ELECTRICAL_RULES
    cs = m["circuits"]
    if key == "breaker_cable":
        ok = all(c["rating_a"] <= R["cable_capacity_a"][c["cable_size"]] for c in cs)
    elif key == "load":
        ok = all(c["load_w"] <= R["load_factor"] * c["rating_a"] * R["voltage_v"] for c in cs)
    elif key == "rcd":
        ok = all(c["rcd"] and c["rcd"]["sens_ma"] <= R["rcd_max_ma_for_sockets"] for c in cs if c["type"] == "SOCKETS")
    elif key == "lighting":
        ok = all(c["rating_a"] <= R["lighting_max_breaker_a"] for c in cs if c["type"] == "LIGHTING")
    else:
        ok = all(c["cable_length_m"] <= R["cable_max_length_m"][c["cable_size"]] for c in cs)
    return "PASS" if ok else "FAIL"


def _circuit_answer(key: str, m: dict, rng: random.Random):
    comps = m["components"]
    if key == "resistors":
        return {}, m["counts"]["resistors"]
    if key == "capacitors":
        return {}, m["counts"]["capacitors"]
    if key == "r_value":
        r = rng.choice([c for c in comps if c["type"] == "RESISTOR"])
        return {"R": r["tag"]}, r["attrs"]["VALUE_OHM"]
    if key == "neighbours":
        x = rng.choice(["U1", "J1"] + [c["tag"] for c in comps[2:]])
        return {"X": x}, len(m["neighbours"][x])
    return {}, m["counts"]["components"]


def build(samples: str = "data/samples", seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    qs: list[dict] = []
    for f in sorted(glob.glob(f"{samples}/*.json")):
        m = json.loads(Path(f).read_text())
        dxf = m["file"]
        spec = m.get("spec")
        if m["kind"] == "electrical":
            for key, variants in BOARD_TEMPLATES:
                c = rng.choice(m["circuits"])
                v = rng.randrange(2)
                exp, atype = _board_answer(key, m, c)
                qs.append({"kind": "compute", "domain": "electrical", "template": key, "variant": ["canonical", "paraphrase"][v],
                           "drawing": dxf, "spec": spec, "question": variants[v].format(C=c["tag"]),
                           "expected": exp, "answer_type": atype, "expected_route": "compute"})
            for key, q in ELECTRICAL_COMPLIANCE:
                qs.append({"kind": "compliance", "domain": "electrical", "template": key, "drawing": dxf, "spec": spec,
                           "question": q, "expected": _electrical_truth(key, m), "answer_type": "verdict",
                           "expected_route": "compliance"})
            continue
        if m["kind"] == "electronic":
            for key, variants in CIRCUIT_TEMPLATES:
                fmt, exp = _circuit_answer(key, m, rng)
                v = rng.randrange(2)
                qs.append({"kind": "compute", "domain": "electronic", "template": key, "variant": ["canonical", "paraphrase"][v],
                           "drawing": dxf, "spec": None, "question": variants[v].format(**fmt),
                           "expected": exp, "answer_type": "number", "expected_route": "compute"})
            continue
        if m["kind"] == "floorplan":
            for key, variants in PLAN_TEMPLATES:
                room = rng.choice([r for r in m["rooms"]])
                v = rng.randrange(2)
                exp, atype = _plan_answer(key, m, room)
                qs.append({"kind": "compute", "domain": "building", "template": key, "variant": ["canonical", "paraphrase"][v],
                           "drawing": dxf, "spec": spec, "question": variants[v].format(R=room["name"]),
                           "expected": exp, "answer_type": atype, "expected_route": "compute"})
            for key, q in COMPLIANCE_TEMPLATES:
                qs.append({"kind": "compliance", "domain": "building", "template": key, "drawing": dxf, "spec": spec, "question": q,
                           "expected": _compliance_truth(key, m), "answer_type": "verdict",
                           "expected_route": "compliance"})
        else:
            d = rng.choice(sorted({h["d"] for h in m["holes"]}))
            part_qs = [
                ("holes", "How many holes does the part have?", m["counts"]["holes"]),
                ("holes_d", f"How many {d} mm holes are there?", sum(h["d"] == d for h in m["holes"])),
                ("plate_area", "What is the plate outline area in mm²?", m["plate_area_mm2"]),
            ]
            for key, q, exp in part_qs:
                qs.append({"kind": "compute", "domain": "mechanical", "template": key, "variant": "canonical", "drawing": dxf,
                           "spec": None, "question": q, "expected": exp, "answer_type": "number", "expected_route": "compute"})

    example_drawing = {"building": "plan-001.dxf", "electrical": "db-001.dxf"}
    for name, cfg in SPECS.items():
        for q, clause in cfg["qa"]:
            qs.append({"kind": "spec", "domain": name, "template": "spec", "drawing": example_drawing[name], "spec": name,
                       "question": q, "expected": clause, "answer_type": "clause", "expected_route": "spec"})
        for q in cfg["unanswerable"]:
            qs.append({"kind": "unanswerable", "domain": name, "template": "unanswerable", "drawing": example_drawing[name],
                       "spec": name, "question": q, "expected": "NOT_FOUND", "answer_type": "not_found", "expected_route": "spec"})
    for q in VISUAL_QUESTIONS:
        qs.append({"kind": "visual", "domain": "building", "template": "visual", "drawing": "plan-001.dxf", "spec": "building",
                   "question": q, "expected": None, "answer_type": "manual", "expected_route": "visual"})
    for q in VISUAL_ELECTRICAL:
        qs.append({"kind": "visual", "domain": "electrical", "template": "visual", "drawing": "db-001.dxf", "spec": "electrical",
                   "question": q, "expected": None, "answer_type": "manual", "expected_route": "visual"})
    for i, q in enumerate(qs):
        q["id"] = f"q{i:03d}"
    return qs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="data/samples")
    ap.add_argument("--out", default="data/eval/questions.jsonl")
    a = ap.parse_args()
    qs = build(a.samples)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(json.dumps(q) for q in qs) + "\n")
    kinds = {}
    for q in qs:
        kinds[q["kind"]] = kinds.get(q["kind"], 0) + 1
    print(f"Wrote {len(qs)} questions to {a.out}: {kinds}")

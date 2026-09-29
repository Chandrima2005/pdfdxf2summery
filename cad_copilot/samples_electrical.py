"""Synthetic electrical and electronic schematics with ground-truth manifests.

Distribution boards (DB-xxx): the electrical side of a construction project.
  SUPPLY -> MAIN switch -> BUSBAR -> one MCB per final circuit -> [RCD] -> CABLE -> loads
  Loads: lights, socket outlets, air conditioners, water heaters.
  Some boards contain deliberate faults (oversized breakers, overloads, missing
  RCDs, long cable runs) so compliance checks have real FAIL cases.

Electronic circuits (CKT-xxx): a connector and regulator feeding branches of
  resistors, capacitors and LEDs between a VCC rail and a GND rail.

Conventions (also stated in the electrical spec):
  - devices/loads are blocks whose attributes carry the data (TAG, RATING_A, LOAD_W...)
  - conductors are lines on layer WIRES, the busbar is on layer BUSBAR
  - a wire is connected to a device when its end point touches the device symbol
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import ezdxf

EL_LAYERS = {"BUSBAR": 1, "WIRES": 5, "DEVICES": 7, "LOADS": 3, "TAGS": 8, "LABELS": 170, "ANNOTATION": 6}
CKT_LAYERS = {"WIRES": 5, "COMPONENTS": 7, "TAGS": 8, "ANNOTATION": 6}
SPACING = 45

# symbol name -> (height, draw function, attribute names). Top pin at (0,0), bottom pin at (0,-h).
def _rect(b, x0, y0, x1, y1):
    b.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True)


def _sym_supply(b):
    b.add_circle((0, -5), 5)
    b.add_line((-2.5, -5), (2.5, -5))


def _sym_switch(b, w=4):
    _rect(b, -w, -14, w, 0)
    b.add_line((-w + 1, -11), (w - 1, -3))


def _sym_rcd(b):
    _rect(b, -4, -14, 4, 0)
    b.add_circle((0, -7), 2)


def _sym_cable(b):
    b.add_lwpolyline([(0, 0), (2, -3), (0, -6), (-2, -3)], close=True)


def _sym_light(b):
    b.add_circle((0, -4), 4)
    b.add_line((-2.8, -1.2), (2.8, -6.8))
    b.add_line((-2.8, -6.8), (2.8, -1.2))


def _sym_socket(b):
    _rect(b, -4, -8, 4, 0)
    b.add_circle((-1.5, -4), 0.8)
    b.add_circle((1.5, -4), 0.8)


def _sym_box(label):
    def f(b):
        _rect(b, -5, -8, 5, 0)
        b.add_text(label, height=3).set_placement((0, -4), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    return f


def _sym_resistor(b):
    b.add_line((0, 0), (0, -2))
    _rect(b, -2, -10, 2, -2)
    b.add_line((0, -10), (0, -12))


def _sym_capacitor(b):
    b.add_line((0, 0), (0, -5))
    b.add_line((-3, -5), (3, -5))
    b.add_line((-3, -7), (3, -7))
    b.add_line((0, -7), (0, -12))


def _sym_led(b):
    b.add_line((0, 0), (0, -3))
    b.add_lwpolyline([(-3, -3), (3, -3), (0, -8)], close=True)
    b.add_line((-3, -8), (3, -8))
    b.add_line((0, -8), (0, -12))


def _sym_connector(b):
    _rect(b, -3, -20, 3, 0)
    b.add_circle((0, -5), 1.2)
    b.add_circle((0, -15), 1.2)


def _sym_regulator(b):
    _rect(b, 0, -5, 14, 5)
    b.add_text("REG", height=3).set_placement((7, 0), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)


SYMBOLS = {
    "SUPPLY": (10, _sym_supply, ["TAG", "VOLTAGE_V"]),
    "MAIN_SWITCH": (14, lambda b: _sym_switch(b, 4), ["TAG", "RATING_A"]),
    "MCB": (14, lambda b: _sym_switch(b, 3), ["TAG", "RATING_A", "CURVE"]),
    "RCD": (14, _sym_rcd, ["TAG", "RATING_A", "SENS_MA"]),
    "CABLE": (6, _sym_cable, ["TAG", "SIZE_SQMM", "LENGTH_M"]),
    "LIGHT": (8, _sym_light, ["TAG", "LOAD_W"]),
    "SOCKET": (8, _sym_socket, ["TAG", "LOAD_W"]),
    "AC_UNIT": (8, _sym_box("AC"), ["TAG", "LOAD_W"]),
    "WATER_HEATER": (8, _sym_box("WH"), ["TAG", "LOAD_W"]),
    "RESISTOR": (12, _sym_resistor, ["TAG", "VALUE_OHM", "POWER_W"]),
    "CAPACITOR": (12, _sym_capacitor, ["TAG", "VALUE_UF", "VOLTAGE_V"]),
    "LED": (12, _sym_led, ["TAG", "COLOR"]),
    "CONNECTOR": (20, _sym_connector, ["TAG", "PINS"]),
    "REGULATOR": (0, _sym_regulator, ["TAG", "PART", "VOUT_V"]),
}


def _define(doc, names):
    for name in names:
        _, draw, attrs = SYMBOLS[name]
        blk = doc.blocks.new(name)
        draw(blk)
        x0 = 16 if name == "REGULATOR" else 6
        for i, a in enumerate(attrs):
            blk.add_attdef(a, (x0, -2.5 - i * 3.2), dxfattribs={"height": 2.2, "layer": "TAGS"})


def _place(msp, name, pos, layer, values: dict):
    ref = msp.add_blockref(name, pos, dxfattribs={"layer": layer})
    ref.add_auto_attribs({k: str(v) for k, v in values.items()})
    return ref


def _wire(msp, a, b):
    msp.add_line(a, b, dxfattribs={"layer": "WIRES"})


def _new(layers):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 0  # schematic: not to scale
    for n, c in layers.items():
        doc.layers.add(n, color=c)
    return doc


# ---------------------------------------------------------------- distribution boards
def _design_circuit(rng: random.Random, idx: int, ctype: str) -> dict:
    c = {"tag": f"C{idx}", "type": ctype, "rcd": None}
    if ctype == "LIGHTING":
        k = rng.randint(3, 12)
        w = rng.choice([12, 18, 24, 36])
        c.update(rating_a=rng.choice([6, 10, 10, 16]), cable_size=rng.choice([1.5, 1.5, 1.5, 2.5]),
                 loads=[{"tag": f"LT{idx}-{j + 1}", "type": "LIGHT", "load_w": w} for j in range(k)])
    elif ctype == "SOCKETS":
        k = rng.randint(2, 10)
        w = rng.choice([200, 300, 400])
        c.update(rating_a=rng.choice([16, 20, 20, 25, 32]), cable_size=rng.choice([2.5, 2.5, 2.5, 4.0]),
                 loads=[{"tag": f"SK{idx}-{j + 1}", "type": "SOCKET", "load_w": w} for j in range(k)])
        r = rng.random()
        c["rcd"] = {"tag": f"RCD{idx}", "sens_ma": 30} if r < 0.72 else ({"tag": f"RCD{idx}", "sens_ma": 100} if r < 0.86 else None)
    elif ctype == "AC":
        c.update(rating_a=rng.choice([16, 20]), cable_size=rng.choice([2.5, 4.0]),
                 loads=[{"tag": f"AC{idx}", "type": "AC_UNIT", "load_w": rng.choice([1500, 2000, 2500, 3500])}])
    else:
        c.update(rating_a=rng.choice([16, 20, 25]), cable_size=rng.choice([2.5, 4.0]),
                 loads=[{"tag": f"WH{idx}", "type": "WATER_HEATER", "load_w": rng.choice([2000, 3000])}])
    c["cable_tag"] = f"W{idx}"
    c["cable_length_m"] = rng.randint(5, 30)
    c["load_w"] = sum(l["load_w"] for l in c["loads"])
    return c


def make_board(seed: int, out_dir: Path) -> dict:
    rng = random.Random(2000 + seed)
    board = f"DB-{seed:03d}"
    n = rng.randint(4, 8)
    types = ["LIGHTING", "SOCKETS"] + [rng.choice(["LIGHTING", "SOCKETS", "SOCKETS", "AC", "WATER_HEATER"]) for _ in range(n - 2)]
    rng.shuffle(types)
    circuits = [_design_circuit(rng, i + 1, t) for i, t in enumerate(types)]
    main_rating = rng.choice([63, 80, 100, 100, 50])

    doc = _new(EL_LAYERS)
    _define(doc, ["SUPPLY", "MAIN_SWITCH", "MCB", "RCD", "CABLE", "LIGHT", "SOCKET", "AC_UNIT", "WATER_HEATER"])
    msp = doc.modelspace()

    # supply -> main switch -> busbar
    _place(msp, "SUPPLY", (-40, 44), "DEVICES", {"TAG": "SUPPLY", "VOLTAGE_V": 230})
    _wire(msp, (-40, 34), (-40, 28))
    _place(msp, "MAIN_SWITCH", (-40, 28), "DEVICES", {"TAG": "MAIN", "RATING_A": main_rating})
    _wire(msp, (-40, 14), (-40, 0))
    x_end = SPACING * (n - 1) + 10
    msp.add_line((-40, 0), (x_end, 0), dxfattribs={"layer": "BUSBAR"})

    for i, c in enumerate(circuits):
        x = SPACING * i
        y = -10
        _wire(msp, (x, 0), (x, y))
        _place(msp, "MCB", (x, y), "DEVICES", {"TAG": c["tag"], "RATING_A": c["rating_a"], "CURVE": "B"})
        y -= 14
        if c["rcd"]:
            _wire(msp, (x, y), (x, y - 6))
            y -= 6
            _place(msp, "RCD", (x, y), "DEVICES", {"TAG": c["rcd"]["tag"], "RATING_A": 40, "SENS_MA": c["rcd"]["sens_ma"]})
            y -= 14
        _wire(msp, (x, y), (x, y - 6))
        y -= 6
        _place(msp, "CABLE", (x, y), "DEVICES", {"TAG": c["cable_tag"], "SIZE_SQMM": c["cable_size"], "LENGTH_M": c["cable_length_m"]})
        y -= 6
        for load in c["loads"]:
            _wire(msp, (x, y), (x, y - 6))
            y -= 6
            _place(msp, load["type"], (x, y), "LOADS", {"TAG": load["tag"], "LOAD_W": load["load_w"]})
            y -= 8
        msp.add_text(f"{c['tag']} {c['type']}", height=2.5, dxfattribs={"layer": "LABELS"}).set_placement((x - 4, y - 6))

    for i, t in enumerate([f"DISTRIBUTION BOARD {board}", "SINGLE LINE DIAGRAM", "SUPPLY 230 V 1PH", "REV A"]):
        msp.add_text(t, height=4, dxfattribs={"layer": "ANNOTATION"}).set_placement((-45, 80 - i * 6))

    path = out_dir / f"{board.lower()}.dxf"
    doc.saveas(path)
    counts = {"circuits": n,
              "lights": sum(l["type"] == "LIGHT" for c in circuits for l in c["loads"]),
              "sockets": sum(l["type"] == "SOCKET" for c in circuits for l in c["loads"]),
              "ac_units": sum(l["type"] == "AC_UNIT" for c in circuits for l in c["loads"]),
              "water_heaters": sum(l["type"] == "WATER_HEATER" for c in circuits for l in c["loads"]),
              "rcds": sum(c["rcd"] is not None for c in circuits)}
    manifest = {"id": board, "kind": "electrical", "spec": "electrical", "file": path.name, "units": "unitless",
                "main_rating_a": main_rating, "circuits": circuits, "counts": counts,
                "total_cable_length_m": sum(c["cable_length_m"] for c in circuits),
                "total_load_w": sum(c["load_w"] for c in circuits),
                "layers": list(EL_LAYERS)}
    (out_dir / f"{board.lower()}.json").write_text(json.dumps(manifest, indent=2))
    return manifest


# ---------------------------------------------------------------- electronic circuits
PATTERNS = [["RESISTOR", "LED"], ["CAPACITOR"], ["RESISTOR", "RESISTOR"], ["RESISTOR"], ["CAPACITOR", "RESISTOR"]]


def make_circuit(seed: int, out_dir: Path) -> dict:
    rng = random.Random(3000 + seed)
    cid = f"CKT-{seed:03d}"
    doc = _new(CKT_LAYERS)
    _define(doc, ["RESISTOR", "CAPACITOR", "LED", "CONNECTOR", "REGULATOR"])
    msp = doc.modelspace()
    counters = {"RESISTOR": 0, "CAPACITOR": 0, "LED": 0}
    prefix = {"RESISTOR": "R", "CAPACITOR": "C", "LED": "D"}
    comps = [{"tag": "J1", "type": "CONNECTOR", "attrs": {"PINS": 2}},
             {"tag": "U1", "type": "REGULATOR", "attrs": {"PART": "REG-5V", "VOUT_V": 5}}]
    nets = {"VIN": {"J1", "U1"}, "VCC": {"U1"}, "GND": {"J1"}}

    m = rng.randint(3, 5)
    x_end = 40 + 25 * (m - 1) + 10
    _place(msp, "CONNECTOR", (0, 40), "COMPONENTS", {"TAG": "J1", "PINS": 2})
    msp.add_lwpolyline([(0, 40), (0, 60), (10, 60)], dxfattribs={"layer": "WIRES"})
    _place(msp, "REGULATOR", (10, 60), "COMPONENTS", {"TAG": "U1", "PART": "REG-5V", "VOUT_V": 5})
    _wire(msp, (24, 60), (x_end, 60))
    _wire(msp, (0, 20), (0, 0))
    _wire(msp, (0, 0), (x_end, 0))

    for k in range(m):
        x = 40 + 25 * k
        pattern = rng.choice(PATTERNS)
        tags = []
        for t in pattern:
            counters[t] += 1
            tag = f"{prefix[t]}{counters[t]}"
            if t == "RESISTOR":
                attrs = {"VALUE_OHM": rng.choice([220, 330, 470, 1000, 4700, 10000]), "POWER_W": rng.choice([0.125, 0.25, 0.5])}
            elif t == "CAPACITOR":
                attrs = {"VALUE_UF": rng.choice([0.1, 1, 10, 100]), "VOLTAGE_V": rng.choice([16, 25, 50])}
            else:
                attrs = {"COLOR": rng.choice(["RED", "GREEN", "BLUE"])}
            comps.append({"tag": tag, "type": t, "attrs": attrs})
            tags.append((tag, t, attrs))
        _wire(msp, (x, 60), (x, 52))
        (t1, ty1, a1) = tags[0]
        _place(msp, ty1, (x, 52), "COMPONENTS", {"TAG": t1, **a1})
        nets["VCC"].add(t1)
        if len(tags) == 2:
            (t2, ty2, a2) = tags[1]
            _wire(msp, (x, 40), (x, 34))
            _place(msp, ty2, (x, 34), "COMPONENTS", {"TAG": t2, **a2})
            nets[f"N{k}"] = {t1, t2}
            _wire(msp, (x, 22), (x, 0))
            nets["GND"].add(t2)
        else:
            _wire(msp, (x, 40), (x, 0))
            nets["GND"].add(t1)

    for i, t in enumerate([f"CIRCUIT {cid}", "5 V INDICATOR BOARD", "REV A"]):
        msp.add_text(t, height=3.5, dxfattribs={"layer": "ANNOTATION"}).set_placement((0, -12 - i * 5.5))

    path = out_dir / f"{cid.lower()}.dxf"
    doc.saveas(path)
    neighbours = {c["tag"]: sorted({o for net in nets.values() if c["tag"] in net for o in net} - {c["tag"]}) for c in comps}
    counts = {t.lower() + "s": sum(c["type"] == t for c in comps) for t in ("RESISTOR", "CAPACITOR", "LED")}
    counts["components"] = len(comps)
    manifest = {"id": cid, "kind": "electronic", "spec": None, "file": path.name, "units": "unitless",
                "components": comps, "nets": {k: sorted(v) for k, v in nets.items()},
                "neighbours": neighbours, "counts": counts, "layers": list(CKT_LAYERS)}
    (out_dir / f"{cid.lower()}.json").write_text(json.dumps(manifest, indent=2))
    return manifest

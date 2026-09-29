"""Synthetic sample-data generator (building plans and mechanical parts here;
electrical and electronic schematics in samples_electrical.py).

Real CAD files with verified answers are hard to find, so we generate our own.
Each drawing comes with a JSON *manifest* holding the true values (room areas,
door widths, hole counts...). The manifest is written by the generator, not by
our parser, so it is an independent ground truth for tests and evaluation.

Usage:
    python -m cad_copilot.samples --out data/samples
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import ezdxf

LAYERS = {
    "WALLS": 7,
    "ROOMS": 3,
    "ROOM_NAMES": 170,
    "CORRIDOR": 4,
    "DOORS": 1,
    "WINDOWS": 5,
    "DIMENSIONS": 8,
    "ANNOTATION": 6,
}
HABITABLE = ("LIVING", "BEDROOM", "STUDY", "KITCHEN")


def _new_doc(layers: dict[str, int]):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    for name, color in layers.items():
        doc.layers.add(name, color=color)
    return doc


def _cuts(rng: random.Random, total: int, pieces: int, min_size: int = 2400) -> list[int]:
    """Split [0, total] into `pieces` parts, each at least min_size, on a 100 mm grid."""
    for _ in range(500):
        cuts = sorted(rng.sample(range(min_size, total - min_size + 1, 100), pieces - 1))
        edges = [0, *cuts, total]
        if all(b - a >= min_size for a, b in zip(edges, edges[1:])):
            return edges
    step = total // pieces
    return [i * step for i in range(pieces)] + [total]


def make_floorplan(seed: int, out_dir: Path) -> dict:
    rng = random.Random(seed)
    plan_id = f"PLAN-{seed:03d}"
    W = rng.choice(range(10000, 16001, 500))
    D = rng.choice(range(8000, 12001, 500))
    cw = rng.choice([900, 1000, 1100, 1200, 1500])
    cy0 = int(round((D - cw) / 2 / 100.0) * 100)
    cy1 = cy0 + cw

    k_top, k_bot = rng.randint(2, 4), rng.randint(2, 4)
    n_rooms = k_top + k_bot
    names = ["LIVING", "KITCHEN", "BATH"]
    if n_rooms > 5 and rng.random() < 0.6:
        names.append("STUDY")
    names += [f"BEDROOM {i}" for i in range(1, n_rooms - len(names) + 1)]
    rng.shuffle(names)

    doc = _new_doc(LAYERS)
    blk = doc.blocks.new("DOOR")  # unit door: leaf + 90 degree swing, scaled on insert
    blk.add_line((0, 0), (0, 1))
    blk.add_arc((0, 0), 1, 0, 90)
    msp = doc.modelspace()

    # Walls (centre-lines, no thickness)
    walls = [((0, 0), (W, 0)), ((W, 0), (W, D)), ((W, D), (0, D)), ((0, D), (0, 0)),
             ((0, cy0), (W, cy0)), ((0, cy1), (W, cy1))]
    top_edges, bot_edges = _cuts(rng, W, k_top), _cuts(rng, W, k_bot)
    walls += [((x, cy1), (x, D)) for x in top_edges[1:-1]]
    walls += [((x, 0), (x, cy0)) for x in bot_edges[1:-1]]
    for a, b in walls:
        msp.add_line(a, b, dxfattribs={"layer": "WALLS"})
    wall_len = sum(math.dist(a, b) for a, b in walls)

    # Corridor
    msp.add_lwpolyline([(0, cy0), (W, cy0), (W, cy1), (0, cy1)], close=True,
                       dxfattribs={"layer": "CORRIDOR"})
    msp.add_text("CORRIDOR", height=200, dxfattribs={"layer": "ROOM_NAMES"}).set_placement(
        (W * 0.5, cy0 + cw / 2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    rooms = []
    name_iter = iter(names)
    for band, edges in (("top", top_edges), ("bottom", bot_edges)):
        y0, y1 = (cy1, D) if band == "top" else (0, cy0)
        for x0, x1 in zip(edges, edges[1:]):
            name = next(name_iter)
            msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
                               dxfattribs={"layer": "ROOMS"})
            msp.add_text(name, height=250, dxfattribs={"layer": "ROOM_NAMES"}).set_placement(
                ((x0 + x1) / 2, (y0 + y1) / 2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

            dw = 750 if name == "BATH" else rng.choice([750, 800, 850, 900, 900])
            if band == "top":
                msp.add_blockref("DOOR", (x0 + 300, cy1),
                                 dxfattribs={"layer": "DOORS", "xscale": dw, "yscale": dw})
            else:
                msp.add_blockref("DOOR", (x0 + 300 + dw, cy0),
                                 dxfattribs={"layer": "DOORS", "xscale": dw, "yscale": dw, "rotation": 180})

            windows = []
            no_window = name == "BATH" and rng.random() < 0.5 or rng.random() < 0.12
            if not no_window:
                wl = min(rng.choice([900, 1200, 1500]), (x1 - x0) - 600)
                wx = (x0 + x1) / 2
                wy = D if band == "top" else 0
                msp.add_line((wx - wl / 2, wy), (wx + wl / 2, wy), dxfattribs={"layer": "WINDOWS"})
                windows.append(wl)

            rooms.append({
                "name": name, "band": band, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "width": x1 - x0, "depth": y1 - y0,
                "area_m2": round((x1 - x0) * (y1 - y0) / 1e6, 3),
                "door_width": dw, "windows": windows,
            })

    big = {"dimtxt": 250, "dimasz": 200, "dimexo": 100, "dimexe": 150, "dimgap": 60, "dimlfac": 1}
    dim = msp.add_linear_dim(base=(0, -1200), p1=(0, 0), p2=(W, 0), dimstyle="EZDXF",
                             override=big, dxfattribs={"layer": "DIMENSIONS"})
    dim.render()
    dim = msp.add_linear_dim(base=(-1200, 0), p1=(0, 0), p2=(0, D), angle=90, dimstyle="EZDXF",
                             override=big, dxfattribs={"layer": "DIMENSIONS"})
    dim.render()
    for i, t in enumerate([f"FLOOR PLAN {plan_id}", "SCALE 1:100", "UNITS: MM"]):
        msp.add_text(t, height=300, dxfattribs={"layer": "ANNOTATION"}).set_placement((0, -2500 - i * 450))

    path = out_dir / f"{plan_id.lower()}.dxf"
    doc.saveas(path)
    manifest = {
        "id": plan_id, "kind": "floorplan", "spec": "building", "file": path.name, "units": "mm",
        "width": W, "depth": D, "corridor_width": cw,
        "rooms": rooms,
        "counts": {
            "rooms": len(rooms), "doors": len(rooms),
            "windows": sum(len(r["windows"]) for r in rooms),
            "bedrooms": sum(r["name"].startswith("BEDROOM") for r in rooms),
        },
        "total_wall_length": round(wall_len, 3),
        "layers": list(LAYERS),
    }
    (out_dir / f"{plan_id.lower()}.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def make_part(seed: int, out_dir: Path) -> dict:
    rng = random.Random(1000 + seed)
    part_id = f"BRK-{seed:03d}"
    layers = {"OUTLINE": 7, "HOLES": 1, "CENTERLINES": 4, "DIMENSIONS": 8, "ANNOTATION": 6}
    doc = _new_doc(layers)
    msp = doc.modelspace()
    W, H = rng.choice(range(80, 201, 10)), rng.choice(range(50, 121, 10))
    msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True, dxfattribs={"layer": "OUTLINE"})

    holes = []
    margin = 12
    diameters = [6, 8, 10, 12]
    corner_d = rng.choice(diameters)
    for x, y in [(margin, margin), (W - margin, margin), (W - margin, H - margin), (margin, H - margin)]:
        holes.append({"x": x, "y": y, "d": corner_d})
    for _ in range(rng.randint(0, 4)):
        d = rng.choice(diameters)
        for _try in range(50):
            x, y = rng.uniform(25, W - 25), rng.uniform(25, H - 25)
            if all(math.dist((x, y), (h["x"], h["y"])) > (d + h["d"]) for h in holes):
                holes.append({"x": round(x, 1), "y": round(y, 1), "d": d})
                break
    for h in holes:
        msp.add_circle((h["x"], h["y"]), h["d"] / 2, dxfattribs={"layer": "HOLES"})
        r = h["d"] * 0.8
        msp.add_line((h["x"] - r, h["y"]), (h["x"] + r, h["y"]), dxfattribs={"layer": "CENTERLINES"})
        msp.add_line((h["x"], h["y"] - r), (h["x"], h["y"] + r), dxfattribs={"layer": "CENTERLINES"})

    small = {"dimtxt": 4, "dimasz": 3, "dimexo": 1.5, "dimexe": 2, "dimgap": 1, "dimlfac": 1}
    msp.add_linear_dim(base=(0, -15), p1=(0, 0), p2=(W, 0), dimstyle="EZDXF", override=small,
                       dxfattribs={"layer": "DIMENSIONS"}).render()
    msp.add_linear_dim(base=(-15, 0), p1=(0, 0), p2=(0, H), angle=90, dimstyle="EZDXF",
                       override=small, dxfattribs={"layer": "DIMENSIONS"}).render()
    for i, t in enumerate([f"PART {part_id}", "MATERIAL: AL 6061", "THICKNESS: 5 MM"]):
        msp.add_text(t, height=4, dxfattribs={"layer": "ANNOTATION"}).set_placement((0, -30 - i * 7))

    path = out_dir / f"{part_id.lower()}.dxf"
    doc.saveas(path)
    hole_area = sum(math.pi * (h["d"] / 2) ** 2 for h in holes)
    manifest = {
        "id": part_id, "kind": "part", "spec": None, "file": path.name, "units": "mm",
        "width": W, "height": H, "holes": holes,
        "counts": {"holes": len(holes)},
        "plate_area_mm2": W * H, "net_area_mm2": round(W * H - hole_area, 2),
        "layers": list(layers),
    }
    (out_dir / f"{part_id.lower()}.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def generate(out: str | Path = "data/samples", plans: int = 12, parts: int = 4,
             boards: int = 8, circuits: int = 3) -> list[dict]:
    from cad_copilot.samples_electrical import make_board, make_circuit
    from cad_copilot.spec_content import SPECS, build_spec_pdf
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifests = [make_floorplan(i, out_dir) for i in range(1, plans + 1)]
    manifests += [make_part(i, out_dir) for i in range(1, parts + 1)]
    manifests += [make_board(i, out_dir) for i in range(1, boards + 1)]
    manifests += [make_circuit(i, out_dir) for i in range(1, circuits + 1)]
    for name, cfg in SPECS.items():
        build_spec_pdf(out_dir / cfg["file"], name)
    return manifests


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/samples")
    ap.add_argument("--plans", type=int, default=12)
    ap.add_argument("--parts", type=int, default=4)
    ap.add_argument("--boards", type=int, default=8)
    ap.add_argument("--circuits", type=int, default=3)
    a = ap.parse_args()
    ms = generate(a.out, a.plans, a.parts, a.boards, a.circuits)
    print(f"Wrote {len(ms)} drawings + specification PDFs to {a.out}")

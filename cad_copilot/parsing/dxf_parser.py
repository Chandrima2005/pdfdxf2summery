"""Parse a DXF drawing into a clean, queryable table.

Why a table? An LLM reading raw DXF group codes guesses at numbers. A pandas
DataFrame with one row per entity lets ordinary code do exact geometry, and the
LLM only has to decide *which* computation to run (see tools/geometry_tools.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
import pandas as pd
from ezdxf import bbox as ezbbox

UNITS = {0: "unitless", 1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
# factor to convert one drawing unit to metres
TO_METRES = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254, "ft": 0.3048}

COLUMNS = ["handle", "type", "layer", "x_min", "y_min", "x_max", "y_max", "cx", "cy",
           "length", "area", "closed", "radius", "text", "block", "scale", "rotation",
           "measurement", "vertices", "attribs"]


@dataclass
class Drawing:
    path: str
    entities: pd.DataFrame
    units: str
    layers: list[str]
    extents: tuple[float, float, float, float]
    warnings: list[str] = field(default_factory=list)

    @property
    def to_m(self) -> float | None:
        return TO_METRES.get(self.units)

    def summary(self) -> dict:
        df = self.entities
        by_layer = df.groupby("layer").size().sort_values(ascending=False).to_dict()
        by_type = df.groupby("type").size().sort_values(ascending=False).to_dict()
        texts = [t for t in df["text"].dropna().tolist() if t.strip()]
        x0, y0, x1, y1 = self.extents
        ins = df[df["type"] == "INSERT"]
        blocks = {}
        for b, g in ins.groupby("block"):
            keys = sorted({k for a in g["attribs"].dropna() for k in a})
            blocks[b] = {"count": int(len(g)), "attributes": keys}
        return {
            "file": Path(self.path).name,
            "domain": detect_domain(self),
            "blocks": blocks,
            "units": self.units,
            "entity_count": int(len(df)),
            "layers": by_layer,
            "entity_types": by_type,
            "extents": {"width": round(x1 - x0, 3), "height": round(y1 - y0, 3)},
            "text_annotations": texts[:60],
        }

    def summary_text(self) -> str:
        s = self.summary()
        lines = [f"Drawing {s['file']}: {s['domain']} ({s['units']}), {s['entity_count']} entities.",
                 f"Extents: {s['extents']['width']} x {s['extents']['height']} {s['units']}.",
                 "Layers: " + ", ".join(f"{k} ({v})" for k, v in s["layers"].items()),
                 "Entity types: " + ", ".join(f"{k} ({v})" for k, v in s["entity_types"].items()),
                 "Text: " + "; ".join(s["text_annotations"][:30])]
        if s["blocks"]:
            lines.insert(4, "Blocks: " + ", ".join(
                f"{b} x{v['count']}" + (f" [attributes: {', '.join(v['attributes'])}]" if v["attributes"] else "")
                for b, v in s["blocks"].items()))
        return "\n".join(lines)


CONDUCTOR_LAYER_HINTS = ("WIRE", "BUS", "NET", "CONDUCTOR", "CABLE_RUN")


def detect_domain(d: "Drawing") -> str:
    """Rough drawing type, used to give the LLM and the offline planner context."""
    df = d.entities
    layers = {l.upper() for l in d.layers}
    ins = df[df["type"] == "INSERT"]
    has_attr_blocks = ins["attribs"].notna().any() if len(ins) else False
    has_conductors = any(h in l for l in layers for h in CONDUCTOR_LAYER_HINTS)
    if has_attr_blocks and has_conductors:
        return "electrical/electronic schematic"
    if "ROOMS" in layers or ("WALLS" in layers and (df["closed"]).any()):
        return "building floor plan"
    if "HOLES" in layers or (df["type"] == "CIRCLE").sum() >= 3:
        return "mechanical part"
    return "general drawing"


def _shoelace(pts: list[tuple[float, float]]) -> float:
    n = len(pts)
    if n < 3:
        return 0.0
    s = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    return abs(s) / 2.0


def _polyline_length(pts: list[tuple[float, float]], closed: bool) -> float:
    segs = list(zip(pts, pts[1:] + (pts[:1] if closed else [])))
    return sum(math.dist(a, b) for a, b in segs)


def _row(e) -> dict:
    t = e.dxftype()
    r = {c: None for c in COLUMNS}
    r.update(handle=e.dxf.handle, type=t, layer=e.dxf.get("layer", "0"), closed=False)

    if t == "LINE":
        s, en = e.dxf.start, e.dxf.end
        r["length"] = math.dist((s.x, s.y), (en.x, en.y))
        r["vertices"] = [(s.x, s.y), (en.x, en.y)]
    elif t == "LWPOLYLINE":
        pts = [(p[0], p[1]) for p in e.get_points("xy")]
        closed = bool(e.closed)
        r.update(vertices=pts, closed=closed, length=_polyline_length(pts, closed))
        if closed:
            # Note: bulges (arc segments) are ignored in the area, which is exact for
            # straight-edged room outlines. Documented limitation.
            r["area"] = _shoelace(pts)
    elif t == "POLYLINE":
        pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
        closed = bool(e.is_closed)
        r.update(vertices=pts, closed=closed, length=_polyline_length(pts, closed))
        if closed:
            r["area"] = _shoelace(pts)
    elif t == "CIRCLE":
        rad = e.dxf.radius
        r.update(radius=rad, length=2 * math.pi * rad, area=math.pi * rad ** 2, closed=True)
    elif t == "ARC":
        rad = e.dxf.radius
        sweep = (e.dxf.end_angle - e.dxf.start_angle) % 360 or 360
        r.update(radius=rad, length=rad * math.radians(sweep))
    elif t in ("TEXT", "MTEXT"):
        r["text"] = e.plain_text() if t == "MTEXT" else e.dxf.text
    elif t == "INSERT":
        r.update(block=e.dxf.name, scale=abs(e.dxf.get("xscale", 1.0)),
                 rotation=e.dxf.get("rotation", 0.0))
        # Attributes carry the engineering data: TAG, RATING_A, LOAD_W, VALUE_OHM...
        attribs = {a.dxf.tag.upper(): a.dxf.text for a in e.attribs}
        r["attribs"] = attribs or None
    elif t == "DIMENSION":
        try:
            r["measurement"] = float(e.get_measurement())
        except Exception:
            r["measurement"] = None

    # Bounding box: text/inserts use their placement point as a fallback.
    try:
        if t == "INSERT":
            geo = [v for v in e.virtual_entities() if v.dxftype() not in ("ATTDEF", "ATTRIB", "TEXT", "MTEXT")]
            ext = ezbbox.extents(geo, fast=True)
        else:
            ext = ezbbox.extents([e], fast=True)
        if ext.has_data:
            r.update(x_min=ext.extmin.x, y_min=ext.extmin.y, x_max=ext.extmax.x, y_max=ext.extmax.y)
    except Exception:
        pass
    if r["x_min"] is None and e.dxf.hasattr("insert"):
        p = e.dxf.insert
        r.update(x_min=p.x, y_min=p.y, x_max=p.x, y_max=p.y)
    if t == "INSERT":
        p = e.dxf.insert  # the block's base point (e.g. a door's hinge)
        r["cx"], r["cy"] = p.x, p.y
    elif t in ("TEXT", "MTEXT") and e.dxf.hasattr("insert"):
        # For point-in-room tests, the alignment point is the text's anchor.
        p = e.dxf.align_point if t == "TEXT" and e.dxf.hasattr("align_point") and e.dxf.halign else e.dxf.insert
        r["cx"], r["cy"] = p.x, p.y
    elif r["x_min"] is not None:
        r["cx"], r["cy"] = (r["x_min"] + r["x_max"]) / 2, (r["y_min"] + r["y_max"]) / 2
    return r


def parse_dxf(path: str | Path) -> Drawing:
    """Read a DXF file and return a Drawing with one DataFrame row per modelspace entity."""
    path = str(path)
    warnings: list[str] = []
    try:
        doc = ezdxf.readfile(path)
    except ezdxf.DXFStructureError:
        from ezdxf import recover
        doc, auditor = recover.readfile(path)
        warnings.append(f"File needed recovery ({len(auditor.errors)} errors fixed).")

    rows = []
    for e in doc.modelspace():
        try:
            rows.append(_row(e))
        except Exception as exc:  # never let one odd entity kill the whole parse
            warnings.append(f"Skipped {e.dxftype()} {e.dxf.handle}: {exc}")
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["closed"] = df["closed"].fillna(False).astype(bool)

    units = UNITS.get(doc.header.get("$INSUNITS", 0), "unitless")
    layers = sorted(df["layer"].dropna().unique().tolist())
    geo = df.dropna(subset=["x_min"])
    geo = geo[geo["type"] != "DIMENSION"] if len(geo[geo["type"] != "DIMENSION"]) else geo
    extents = ((geo["x_min"].min(), geo["y_min"].min(), geo["x_max"].max(), geo["y_max"].max())
               if len(geo) else (0.0, 0.0, 0.0, 0.0))
    return Drawing(path=path, entities=df, units=units, layers=layers,
                   extents=tuple(float(v) for v in extents), warnings=warnings)


def to_compact_text(drawing: Drawing, max_chars: int = 12000) -> str:
    """Raw-ish dump used by the *baseline* (LLM reads the drawing directly, no tools)."""
    df = drawing.entities
    parts = []
    for r in df.itertuples():
        if r.type == "LINE" and r.vertices:
            (a, b) = r.vertices
            parts.append(f"LINE {r.layer} ({a[0]:.0f},{a[1]:.0f})-({b[0]:.0f},{b[1]:.0f})")
        elif r.type in ("LWPOLYLINE", "POLYLINE") and r.vertices:
            pts = " ".join(f"({x:.0f},{y:.0f})" for x, y in r.vertices)
            parts.append(f"POLYLINE {r.layer} {'closed ' if r.closed else ''}{pts}")
        elif r.type == "CIRCLE":
            parts.append(f"CIRCLE {r.layer} c=({r.cx:.1f},{r.cy:.1f}) r={r.radius:.2f}")
        elif r.type in ("TEXT", "MTEXT"):
            parts.append(f"TEXT {r.layer} '{r.text}' at ({r.cx:.0f},{r.cy:.0f})")
        elif r.type == "INSERT":
            att = (" " + " ".join(f"{k}={v}" for k, v in r.attribs.items())) if r.attribs else ""
            parts.append(f"INSERT {r.layer} block={r.block} scale={r.scale:g} rot={r.rotation:g} at ({r.cx:.0f},{r.cy:.0f}){att}")
        elif r.type == "DIMENSION":
            parts.append(f"DIMENSION {r.layer} value={r.measurement}")
        elif r.type == "ARC":
            parts.append(f"ARC {r.layer} r={r.radius:.1f}")
    text = f"UNITS: {drawing.units}\n" + "\n".join(parts)
    return text[:max_chars] + ("\n...[truncated]" if len(text) > max_chars else "")

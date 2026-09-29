"""Deterministic geometry tools the LLM can call.

Design rule: every number the user sees is computed here by code, never guessed
by the model. The model's job is to choose the tool and explain the result.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from cad_copilot.parsing.dxf_parser import Drawing
from cad_copilot.tools.connectivity import Netlist

MAX_ITEMS = 60


def _point_in_poly(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def _near_boundary(x: float, y: float, poly: list[tuple[float, float]], tol: float) -> bool:
    n = len(poly)
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        if math.hypot(x - (ax + t * dx), y - (ay + t * dy)) <= tol:
            return True
    return False


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _r(v: float | None, nd: int = 3):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), nd)


class DrawingTools:
    def __init__(self, drawing: Drawing):
        self.d = drawing
        self.df = drawing.entities

    # ---------- helpers ----------
    def _filter(self, entity_type: str | None = None, layer: str | None = None) -> pd.DataFrame:
        df = self.df
        if entity_type:
            types = {t.strip().upper() for t in entity_type.split(",")}
            if "POLYLINE" in types:
                types.add("LWPOLYLINE")
            df = df[df["type"].isin(types)]
        if layer:
            df = df[df["layer"].str.upper() == layer.strip().upper()]
        return df

    def _area_out(self, a: float | None) -> dict:
        out = {"area": _r(a), "area_units": f"{self.d.units}^2"}
        if a is not None and self.d.to_m:
            out["area_m2"] = _r(a * self.d.to_m ** 2)
        return out

    # ---------- tools ----------
    def drawing_info(self) -> dict:
        return self.d.summary()

    def list_layers(self) -> dict:
        g = self.df.groupby("layer")
        return {"layers": [{"layer": k, "count": int(len(v)),
                            "types": v["type"].value_counts().to_dict()} for k, v in g]}

    def count_entities(self, entity_type: str | None = None, layer: str | None = None,
                       block_name: str | None = None, diameter: float | None = None,
                       text_contains: str | None = None) -> dict:
        df = self._filter(entity_type, layer)
        if block_name:
            df = df[df["block"].fillna("").str.upper() == block_name.upper()]
        if diameter is not None:
            df = df[(df["radius"].notna()) & ((df["radius"] * 2 - float(diameter)).abs() < 1e-6 * max(1.0, float(diameter)) + 1e-6)]
        if text_contains:
            df = df[df["text"].fillna("").str.upper().str.contains(text_contains.upper(), regex=False)]
        return {"count": int(len(df)),
                "filters": {k: v for k, v in dict(entity_type=entity_type, layer=layer, block_name=block_name,
                                                   diameter=diameter, text_contains=text_contains).items() if v is not None}}

    def total_length(self, layer: str | None = None, entity_type: str | None = None) -> dict:
        df = self._filter(entity_type, layer)
        total = float(df["length"].fillna(0).sum())
        out = {"total_length": _r(total), "units": self.d.units, "entities_counted": int(df["length"].notna().sum())}
        if self.d.to_m:
            out["total_length_m"] = _r(total * self.d.to_m)
        return out

    def find_text(self, pattern: str | None = None, layer: str | None = None) -> dict:
        df = self._filter("TEXT,MTEXT", layer)
        if pattern:
            df = df[df["text"].fillna("").str.upper().str.contains(pattern.upper(), regex=False)]
        items = [{"text": r.text, "layer": r.layer, "x": _r(r.cx, 1), "y": _r(r.cy, 1)} for r in df.itertuples()]
        return {"matches": items[:MAX_ITEMS], "count": len(items)}

    def list_dimensions(self) -> dict:
        df = self._filter("DIMENSION")
        return {"dimensions": [{"value": _r(r.measurement), "layer": r.layer} for r in df.itertuples()],
                "units": self.d.units}

    def labeled_regions(self, layer: str | None = None, label_contains: str | None = None) -> dict:
        """Closed polylines paired with the text label(s) placed inside them (e.g. rooms)."""
        polys = self._filter("LWPOLYLINE,POLYLINE", layer)
        polys = polys[polys["closed"]]
        texts = self._filter("TEXT,MTEXT").dropna(subset=["cx"])
        regions = []
        for p in polys.itertuples():
            labels = [t.text for t in texts.itertuples() if _point_in_poly(t.cx, t.cy, p.vertices)]
            label = " / ".join(labels) if labels else None
            if label_contains and (not label or label_contains.upper() not in label.upper()):
                continue
            regions.append({"label": label, "layer": p.layer,
                            "width": _r(p.x_max - p.x_min), "height": _r(p.y_max - p.y_min),
                            "min_side": _r(min(p.x_max - p.x_min, p.y_max - p.y_min)),
                            **self._area_out(p.area)})
        regions.sort(key=lambda r: -(r["area"] or 0))
        total = sum(r["area"] or 0 for r in regions)
        return {"regions": regions[:MAX_ITEMS], "count": len(regions), **{f"total_{k}": v for k, v in self._area_out(total).items()}}

    def block_inserts(self, block_name: str | None = None, layer: str | None = None) -> dict:
        """Block references (doors, fixtures...). For a unit-size block, `scale` is its real width.
        `in_region` is the labelled closed polyline the block opens into / sits in."""
        df = self._filter("INSERT", layer)
        if block_name:
            df = df[df["block"].fillna("").str.upper() == block_name.upper()]
        polys = self._filter("LWPOLYLINE,POLYLINE")
        polys = polys[polys["closed"]]
        texts = self._filter("TEXT,MTEXT").dropna(subset=["cx"])
        items = []
        for r in df.itertuples():
            # Probe a point inside the door swing: local (0.3, 0.3) scaled and rotated
            # from the base point. Assumes the block opens into +x/+y (true for DOOR).
            s, rot = float(r.scale or 1.0), math.radians(float(r.rotation or 0.0))
            px = r.cx + 0.3 * s * (math.cos(rot) - math.sin(rot))
            py = r.cy + 0.3 * s * (math.sin(rot) + math.cos(rot))
            region = None
            for p in polys.itertuples():
                if _point_in_poly(px, py, p.vertices):
                    labels = [t.text for t in texts.itertuples() if _point_in_poly(t.cx, t.cy, p.vertices)]
                    region = " / ".join(labels) if labels else p.layer
                    break
            items.append({"block": r.block, "layer": r.layer, "scale": _r(s), "rotation": _r(r.rotation, 1),
                          "x": _r(r.cx, 1), "y": _r(r.cy, 1), "in_region": region})
        return {"inserts": items[:MAX_ITEMS], "count": len(items), "units": self.d.units}

    def circles(self, layer: str | None = None) -> dict:
        df = self._filter("CIRCLE", layer)
        diams = (df["radius"] * 2).round(6)
        by_d = {str(_r(k)): int(v) for k, v in diams.value_counts().sort_index().items()}
        return {"count": int(len(df)), "by_diameter": by_d, "units": self.d.units,
                "total_area": _r(float(df["area"].fillna(0).sum()))}

    def entities_in_region(self, x_min: float, y_min: float, x_max: float, y_max: float,
                           layer: str | None = None) -> dict:
        df = self._filter(None, layer).dropna(subset=["cx"])
        df = df[(df["cx"] >= x_min) & (df["cx"] <= x_max) & (df["cy"] >= y_min) & (df["cy"] <= y_max)]
        return {"count": int(len(df)), "by_layer": df["layer"].value_counts().to_dict(),
                "by_type": df["type"].value_counts().to_dict()}

    def layer_extents(self, layer: str) -> dict:
        """Bounding box of everything on one layer, e.g. WALLS gives the building's overall size."""
        df = self._filter(None, layer).dropna(subset=["x_min"])
        if df.empty:
            return {"error": f"No geometry on layer '{layer}'"}
        w, h = df["x_max"].max() - df["x_min"].min(), df["y_max"].max() - df["y_min"].min()
        return {"layer": layer, "width": _r(w), "height": _r(h), "units": self.d.units}

    def count_per_region(self, layer: str, region_layer: str | None = None, tolerance: float | None = None) -> dict:
        """For each labelled closed region, count entities of `layer` whose centre is inside it or on
        its boundary (e.g. windows per room: layer=WINDOWS, region_layer=ROOMS)."""
        polys = self._filter("LWPOLYLINE,POLYLINE", region_layer)
        polys = polys[polys["closed"]]
        items = self._filter(None, layer).dropna(subset=["cx"])
        texts = self._filter("TEXT,MTEXT").dropna(subset=["cx"])
        x0, y0, x1, y1 = self.d.extents
        tol = tolerance if tolerance is not None else 1e-4 * max(x1 - x0, y1 - y0, 1.0)
        out = []
        for p in polys.itertuples():
            labels = [t.text for t in texts.itertuples() if _point_in_poly(t.cx, t.cy, p.vertices)]
            n = sum(1 for it in items.itertuples()
                    if _point_in_poly(it.cx, it.cy, p.vertices) or _near_boundary(it.cx, it.cy, p.vertices, tol))
            out.append({"label": " / ".join(labels) if labels else None, "count": n})
        return {"regions": out[:MAX_ITEMS], "layer": layer}

    # ---------- schematic tools (components = blocks with a TAG attribute) ----------
    @property
    def net(self) -> Netlist:
        if not hasattr(self, "_net"):
            self._net = Netlist(self.d)
        return self._net

    def _comp_out(self, tag: str) -> dict:
        c = self.net.components[tag]
        return {"tag": tag, "type": c["type"], **{k: v for k, v in c["attribs"].items() if k != "TAG"}}

    def components(self, component_type: str | None = None, attribute: str | None = None,
                   value: str | None = None) -> dict:
        """List tagged components, optionally filtered by block type and an attribute value."""
        out = []
        for tag, c in self.net.components.items():
            if component_type and c["type"].upper() != component_type.strip().upper():
                continue
            if attribute:
                v = c["attribs"].get(attribute.upper())
                if v is None or (value is not None and str(v).upper() != str(value).upper()
                                 and _num(v) != _num(value)):
                    continue
            out.append(self._comp_out(tag))
        return {"components": out[:MAX_ITEMS], "count": len(out)}

    def component_details(self, tag: str) -> dict:
        t = self.net.find(tag)
        if not t:
            return {"error": f"No component tagged '{tag}'"}
        return {**self._comp_out(t), "connected_to": sorted(self.net.adj[t])}

    def connected_to(self, tag: str) -> dict:
        """Components directly wired to this one (sharing a conductor)."""
        t = self.net.find(tag)
        if not t:
            return {"error": f"No component tagged '{tag}'"}
        nb = sorted(self.net.adj[t])
        return {"tag": t, "connected": [self._comp_out(x) for x in nb][:MAX_ITEMS], "count": len(nb)}

    def downstream(self, tag: str, sum_attribute: str = "LOAD_W") -> dict:
        """Everything fed from this component, away from the supply, and the total of a numeric attribute."""
        t = self.net.find(tag)
        if not t:
            return {"error": f"No component tagged '{tag}'"}
        if not self.net.source:
            return {"error": "No supply/source component found, so direction is undefined. Use connected_to."}
        tags = self.net.downstream(t)
        total = sum(_num(self.net.components[x]["attribs"].get(sum_attribute.upper())) or 0 for x in tags)
        by_type: dict[str, int] = {}
        for x in tags:
            ty = self.net.components[x]["type"]
            by_type[ty] = by_type.get(ty, 0) + 1
        return {"tag": t, "downstream": [self._comp_out(x) for x in tags][:MAX_ITEMS], "count": len(tags),
                "by_type": by_type, f"total_{sum_attribute.upper()}": _r(total)}

    def downstream_summary(self, component_type: str = "MCB", sum_attribute: str = "LOAD_W") -> dict:
        """One row per device of a type (e.g. every MCB = every circuit): what it feeds and the total load."""
        rows = []
        for tag, c in self.net.components.items():
            if c["type"].upper() != component_type.upper():
                continue
            ds = self.net.downstream(tag)
            by_type: dict[str, int] = {}
            extra = {}
            for x in ds:
                cx = self.net.components[x]
                by_type[cx["type"]] = by_type.get(cx["type"], 0) + 1
                if cx["type"].upper() in ("CABLE", "RCD", "RCBO"):
                    extra[cx["type"].lower()] = {k: v for k, v in cx["attribs"].items()}
            total = sum(_num(self.net.components[x]["attribs"].get(sum_attribute.upper())) or 0 for x in ds)
            rows.append({"tag": tag, **{k: v for k, v in c["attribs"].items() if k != "TAG"},
                         "feeds": by_type, f"total_{sum_attribute.upper()}": _r(total), **extra})
        return {"rows": rows[:MAX_ITEMS], "count": len(rows)}

    def bill_of_materials(self) -> dict:
        """Count of components per type, split by their main rating/value attribute."""
        bom: dict[tuple, int] = {}
        for c in self.net.components.values():
            a = c["attribs"]
            key_attr = next((k for k in ("RATING_A", "SIZE_SQMM", "VALUE_OHM", "VALUE_UF", "LOAD_W", "PART") if k in a), None)
            key = (c["type"], key_attr, a.get(key_attr) if key_attr else None)
            bom[key] = bom.get(key, 0) + 1
        rows = [{"type": t, "spec": f"{k}={v}" if k else None, "qty": n} for (t, k, v), n in sorted(bom.items(), key=str)]
        return {"items": rows[:MAX_ITEMS], "distinct_items": len(rows),
                "total_components": sum(r["qty"] for r in rows)}

    def sum_attribute(self, attribute: str, component_type: str | None = None) -> dict:
        """Sum a numeric attribute (e.g. LENGTH_M of all CABLE blocks, LOAD_W of all loads)."""
        vals = []
        for c in self.net.components.values():
            if component_type and c["type"].upper() != component_type.upper():
                continue
            v = _num(c["attribs"].get(attribute.upper()))
            if v is not None:
                vals.append(v)
        return {"attribute": attribute.upper(), "component_type": component_type, "count": len(vals),
                "total": _r(sum(vals)), "max": _r(max(vals)) if vals else None, "min": _r(min(vals)) if vals else None}

    def path_between(self, from_tag: str, to_tag: str) -> dict:
        a, b = self.net.find(from_tag), self.net.find(to_tag)
        if not a or not b:
            return {"error": "Unknown tag"}
        p = self.net.path(a, b)
        return {"path": p, "hops": max(0, len(p) - 1)} if p else {"error": f"{a} and {b} are not connected"}

    # ---------- dispatch ----------
    def call(self, name: str, args: dict[str, Any] | None = None) -> dict:
        fn = getattr(self, name, None)
        if name.startswith("_") or name == "call" or not callable(fn):
            return {"error": f"Unknown tool '{name}'"}
        try:
            return fn(**(args or {}))
        except TypeError as exc:
            return {"error": f"Bad arguments for {name}: {exc}"}
        except Exception as exc:  # surface errors to the model instead of crashing
            return {"error": f"{type(exc).__name__}: {exc}"}


_S = {"type": "string"}
_N = {"type": "number"}

TOOL_SCHEMAS: list[dict] = [
    {"name": "drawing_info", "description": "Overview of the drawing: units, layers with entity counts, entity types, extents and all text annotations. Call first if unsure what the drawing contains.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "list_layers", "description": "List every layer with its entity count and entity types.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "count_entities", "description": "Count entities, optionally filtered by entity type (LINE, LWPOLYLINE, CIRCLE, ARC, TEXT, INSERT, DIMENSION; comma-separated allowed), layer, block name, circle diameter, or text substring.",
     "parameters": {"type": "object", "properties": {"entity_type": _S, "layer": _S, "block_name": _S, "diameter": _N, "text_contains": _S}}},
    {"name": "total_length", "description": "Sum of lengths of lines/polylines/arcs/circles, optionally filtered by layer and entity type. Returns drawing units and metres.",
     "parameters": {"type": "object", "properties": {"layer": _S, "entity_type": _S}}},
    {"name": "find_text", "description": "Find text annotations containing a substring (case-insensitive), with positions.",
     "parameters": {"type": "object", "properties": {"pattern": _S, "layer": _S}}},
    {"name": "list_dimensions", "description": "All dimension entities and their measured values.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "labeled_regions", "description": "Closed polylines (rooms, corridors, outlines) with the text label inside each, plus width, height, min_side and area (in drawing units^2 and m^2). Use for room areas, room sizes and corridor width (min_side).",
     "parameters": {"type": "object", "properties": {"layer": _S, "label_contains": _S}}},
    {"name": "block_inserts", "description": "Block references such as doors, with scale (= real width for unit-size blocks like DOOR), rotation, position and the labelled room they open into (in_region).",
     "parameters": {"type": "object", "properties": {"block_name": _S, "layer": _S}}},
    {"name": "circles", "description": "Circles (e.g. holes) with count grouped by diameter and total area.",
     "parameters": {"type": "object", "properties": {"layer": _S}}},
    {"name": "entities_in_region", "description": "Count entities whose centre lies inside a rectangle (drawing coordinates).",
     "parameters": {"type": "object", "properties": {"x_min": _N, "y_min": _N, "x_max": _N, "y_max": _N, "layer": _S},
                    "required": ["x_min", "y_min", "x_max", "y_max"]}},
    {"name": "layer_extents", "description": "Overall width and height of everything on one layer (e.g. WALLS = building footprint size, OUTLINE = part size).",
     "parameters": {"type": "object", "properties": {"layer": _S}, "required": ["layer"]}},
    {"name": "count_per_region", "description": "For each labelled closed region (e.g. rooms), count entities of another layer located inside or on its boundary, e.g. windows per room.",
     "parameters": {"type": "object", "properties": {"layer": _S, "region_layer": _S}, "required": ["layer"]}},
    {"name": "components", "description": "SCHEMATICS: list tagged components (blocks with a TAG attribute) with all their attributes, optionally filtered by block type (e.g. MCB, SOCKET, LIGHT, RESISTOR) and an attribute value.",
     "parameters": {"type": "object", "properties": {"component_type": _S, "attribute": _S, "value": _S}}},
    {"name": "component_details", "description": "SCHEMATICS: all attributes of one component by tag (e.g. C3, R2, MAIN) and what it is wired to.",
     "parameters": {"type": "object", "properties": {"tag": _S}, "required": ["tag"]}},
    {"name": "connected_to", "description": "SCHEMATICS: components directly wired to the given component.",
     "parameters": {"type": "object", "properties": {"tag": _S}, "required": ["tag"]}},
    {"name": "downstream", "description": "SCHEMATICS: everything fed from a component, away from the supply (e.g. the RCD, cable and loads of breaker C3), with counts by type and the total of a numeric attribute (default LOAD_W, watts).",
     "parameters": {"type": "object", "properties": {"tag": _S, "sum_attribute": _S}, "required": ["tag"]}},
    {"name": "downstream_summary", "description": "SCHEMATICS: one row per device of a type (default MCB = one row per final circuit) with its attributes, what it feeds, its total LOAD_W, and its cable and RCD attributes. Best tool for per-circuit questions and compliance checks.",
     "parameters": {"type": "object", "properties": {"component_type": _S, "sum_attribute": _S}}},
    {"name": "bill_of_materials", "description": "SCHEMATICS: quantity of each component type grouped by its main rating or value.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "sum_attribute", "description": "SCHEMATICS: total, min and max of a numeric attribute across components, e.g. LENGTH_M over CABLE, LOAD_W over all loads.",
     "parameters": {"type": "object", "properties": {"attribute": _S, "component_type": _S}, "required": ["attribute"]}},
    {"name": "path_between", "description": "SCHEMATICS: chain of components connecting two tags.",
     "parameters": {"type": "object", "properties": {"from_tag": _S, "to_tag": _S}, "required": ["from_tag", "to_tag"]}},
]

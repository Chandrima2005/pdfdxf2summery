"""Build a connectivity graph from schematic geometry.

How it works:
1. Conductors are LINE / open LWPOLYLINE entities on wire-like layers
   (names containing WIRE, BUS, NET, CONDUCTOR or CABLE_RUN).
2. Conductor segments that touch (shared end points, or an end point landing on
   another segment, i.e. a T-junction onto a busbar) are merged into one
   conductor group with union-find.
3. A component (a block insert with a TAG/REF attribute) is attached to a
   conductor group when a segment end point touches the component's symbol box.
4. Two components are connected when they share a conductor group.

"Downstream" is defined by breadth-first distance from the source (a component
whose block name looks like SUPPLY / SOURCE / MAINS / INCOMER): component B is
downstream of A if the path from the source to B passes through A.
"""
from __future__ import annotations

import math
from collections import deque

import pandas as pd

from cad_copilot.parsing.dxf_parser import CONDUCTOR_LAYER_HINTS, Drawing

TAG_KEYS = ("TAG", "REF", "REFDES", "NAME", "ID")
SOURCE_HINTS = ("SUPPLY", "SOURCE", "MAINS", "INCOMER", "UTILITY", "GRID")


def component_tag(attribs: dict | None) -> str | None:
    if not attribs:
        return None
    for k in TAG_KEYS:
        if attribs.get(k):
            return attribs[k]
    return None


def _on_segment(p, a, b, tol) -> bool:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay) <= tol
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) <= tol


class Netlist:
    def __init__(self, drawing: Drawing, conductor_layers: list[str] | None = None):
        df = drawing.entities
        x0, y0, x1, y1 = drawing.extents
        self.tol = max(1e-6, 1e-4 * max(x1 - x0, y1 - y0, 1.0))
        layers = [l for l in drawing.layers if (l.upper() in {c.upper() for c in conductor_layers}
                                                 if conductor_layers else any(h in l.upper() for h in CONDUCTOR_LAYER_HINTS))]
        self.conductor_layers = layers

        # 1. segments
        segs = []
        cond = df[df["layer"].isin(layers) & df["type"].isin(["LINE", "LWPOLYLINE", "POLYLINE"])]
        for r in cond.itertuples():
            pts = r.vertices or []
            if r.closed and pts:
                pts = pts + pts[:1]
            segs += [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        self.segments = segs

        # 2. union-find over touching segments
        parent = list(range(len(segs)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i, (a, b) in enumerate(segs):
            for j in range(i + 1, len(segs)):
                c, d = segs[j]
                if (_on_segment(a, c, d, self.tol) or _on_segment(b, c, d, self.tol)
                        or _on_segment(c, a, b, self.tol) or _on_segment(d, a, b, self.tol)):
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj
        group_of = [find(i) for i in range(len(segs))]

        # 3. components and their attachment to groups
        ins = df[(df["type"] == "INSERT") & df["attribs"].notna()]
        self.components: dict[str, dict] = {}
        for r in ins.itertuples():
            tag = component_tag(r.attribs)
            if not tag or r.x_min is None or pd.isna(r.x_min):
                continue
            self.components[tag] = {"tag": tag, "type": r.block, "layer": r.layer, "attribs": dict(r.attribs),
                                    "box": (r.x_min, r.y_min, r.x_max, r.y_max)}
        self.attached: dict[str, set[int]] = {t: set() for t in self.components}
        t = self.tol
        for i, (a, b) in enumerate(segs):
            for p in (a, b):
                for tag, c in self.components.items():
                    bx0, by0, bx1, by1 = c["box"]
                    if bx0 - t <= p[0] <= bx1 + t and by0 - t <= p[1] <= by1 + t:
                        self.attached[tag].add(group_of[i])

        # 4. component adjacency
        members: dict[int, set[str]] = {}
        for tag, groups in self.attached.items():
            for g in groups:
                members.setdefault(g, set()).add(tag)
        self.adj: dict[str, set[str]] = {tag: set() for tag in self.components}
        for tags in members.values():
            for a in tags:
                self.adj[a] |= tags - {a}
        self.nets = [sorted(v) for v in members.values() if len(v) > 1]

        src = [tg for tg, c in self.components.items() if any(h in c["type"].upper() for h in SOURCE_HINTS)]
        self.source = src[0] if src else None
        self.dist = self._bfs(self.source) if self.source else {}

    def _bfs(self, start: str) -> dict[str, int]:
        dist = {start: 0}
        q = deque([start])
        while q:
            u = q.popleft()
            for v in self.adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    q.append(v)
        return dist

    def find(self, tag: str) -> str | None:
        if tag in self.components:
            return tag
        low = {t.upper(): t for t in self.components}
        return low.get(tag.strip().upper())

    def downstream(self, tag: str) -> list[str]:
        if not self.dist or tag not in self.dist:
            return []
        seen, q, out = {tag}, deque([tag]), []
        while q:
            u = q.popleft()
            for v in self.adj[u]:
                if v not in seen and self.dist.get(v, -1) > self.dist[u]:
                    seen.add(v)
                    out.append(v)
                    q.append(v)
        return out

    def path(self, a: str, b: str) -> list[str]:
        prev = {a: None}
        q = deque([a])
        while q:
            u = q.popleft()
            if u == b:
                break
            for v in self.adj[u]:
                if v not in prev:
                    prev[v] = u
                    q.append(v)
        if b not in prev:
            return []
        out, cur = [], b
        while cur is not None:
            out.append(cur)
            cur = prev[cur]
        return out[::-1]

"""Offline, rule-based answering (no LLM).

Two purposes:
1. The app and the eval run with zero API keys.
2. It is an honest baseline. Keyword rules handle the phrasings they were written
   for and fail on paraphrases, which is exactly the gap the LLM should close.

Returns (text, final, trace, sources) tuples.
"""
from __future__ import annotations

import re

from cad_copilot.retrieval.hybrid import HybridRetriever
from cad_copilot.tools.geometry_tools import DrawingTools

# Clause 1.4 of the sample spec defines these; kept as a constant for the offline path.
HABITABLE = ("LIVING", "BEDROOM", "STUDY", "KITCHEN")


def _fmt(v: float) -> str:
    return f"{v:g}" if abs(v) < 1e6 else f"{v:.0f}"


class HeuristicPlanner:
    def __init__(self, tools: DrawingTools):
        self.t = tools
        self.trace: list[dict] = []

    def _call(self, name: str, **args) -> dict:
        out = self.t.call(name, args)
        self.trace.append({"tool": name, "args": args, "result": out})
        return out

    def _has_layer(self, name: str) -> bool:
        return name.upper() in {l.upper() for l in self.t.d.layers}

    def _labels(self) -> list[str]:
        regs = self.t.labeled_regions()["regions"]
        return sorted({r["label"] for r in regs if r["label"]}, key=len, reverse=True)

    def _label_in(self, ql: str) -> str | None:
        for lab in self._labels():
            if re.search(r"(?<![a-z0-9])" + re.escape(lab.lower()) + r"(?![a-z0-9])", ql):
                return lab
        return None

    # ------------------------------------------------------------------ compute
    def compute(self, q: str):
        self.trace = []
        ql = q.lower()
        if "schematic" in self.t.d.summary()["domain"]:
            out = self._schematic(q, ql)
            if out:
                return out

        m = re.search(r"(\d+(?:\.\d+)?)\s*mm\s+(?:diameter\s+)?holes?|holes?\s+(?:of|with)\s+(?:a\s+)?(?:diameter\s+(?:of\s+)?)?(\d+(?:\.\d+)?)", ql)
        if m and ("how many" in ql or "number" in ql or "count" in ql):
            d = float(m.group(1) or m.group(2))
            n = self._call("count_entities", entity_type="CIRCLE", diameter=d)["count"]
            return self._ans(f"There are {n} holes of {d:g} mm diameter.", n)
        if re.search(r"\b(how many|number of|count)\b.*\bholes?\b", ql):
            n = self._call("circles", layer="HOLES" if self._has_layer("HOLES") else None)["count"]
            return self._ans(f"The part has {n} holes.", n)
        if re.search(r"\b(how many|number of|count)\b.*\bbedrooms?\b", ql):
            n = self._call("labeled_regions", label_contains="BEDROOM")["count"]
            return self._ans(f"There are {n} bedrooms.", n)
        if re.search(r"\b(how many|number of|count)\b.*\brooms?\b", ql):
            n = self._call("labeled_regions", layer="ROOMS")["count"]
            return self._ans(f"The plan has {n} rooms (closed polylines on layer ROOMS).", n)
        if re.search(r"\b(how many|number of|count)\b.*\bdoors?\b", ql):
            n = self._call("block_inserts", block_name="DOOR")["count"]
            return self._ans(f"There are {n} doors (DOOR block inserts).", n)
        if re.search(r"\b(how many|number of|count)\b.*\bwindows?\b", ql):
            n = self._call("count_entities", layer="WINDOWS")["count"]
            return self._ans(f"There are {n} windows on layer WINDOWS.", n)
        if re.search(r"\b(largest|biggest|smallest)\b", ql) and re.search(r"\broom\b", ql):
            regs = self._call("labeled_regions", layer="ROOMS")["regions"]
            pick = min(regs, key=lambda r: r["area"]) if "smallest" in ql else max(regs, key=lambda r: r["area"])
            return self._ans(f"The {'smallest' if 'smallest' in ql else 'largest'} room is {pick['label']} "
                             f"at {pick.get('area_m2', pick['area'])} m².", pick["label"])

        label = self._label_in(ql)
        if "door" in ql and label and re.search(r"\b(width|wide|opening)\b", ql):
            ins = self._call("block_inserts", block_name="DOOR")["inserts"]
            hit = [i for i in ins if i["in_region"] and i["in_region"].upper() == label.upper()]
            if hit:
                w = hit[0]["scale"]
                return self._ans(f"The door into {label} is {_fmt(w)} mm wide.", w)
        if label and label.upper() == "CORRIDOR" and re.search(r"\b(width|wide)\b", ql):
            r = self._call("labeled_regions", label_contains="CORRIDOR")["regions"][0]
            return self._ans(f"The corridor is {_fmt(r['min_side'])} mm wide.", r["min_side"])
        if label and re.search(r"\b(area|size|big)\b", ql):
            r = self._call("labeled_regions", label_contains=label)["regions"]
            r = [x for x in r if x["label"].upper() == label.upper()] or r
            a = r[0].get("area_m2", r[0]["area"])
            return self._ans(f"{label} has an area of {a} m².", a)
        if re.search(r"\bwalls?\b", ql) and re.search(r"\b(length|long)\b", ql):
            out = self._call("total_length", layer="WALLS")
            return self._ans(f"Total wall length is {out['total_length_m']} m.", out["total_length_m"])
        if re.search(r"\b(overall|building|footprint)\b", ql) and re.search(r"\b(width|wide|depth|deep|length|long)\b", ql):
            out = self._call("layer_extents", layer="WALLS")
            key = "height" if re.search(r"\b(depth|deep)\b", ql) else "width"
            return self._ans(f"The building's overall {'depth' if key == 'height' else 'width'} is {_fmt(out[key])} mm.", out[key])
        if re.search(r"\b(plate|outline|part)\b", ql) and "area" in ql:
            r = self._call("labeled_regions", layer="OUTLINE")["regions"][0]
            return self._ans(f"The plate outline area is {_fmt(r['area'])} mm².", r["area"])

        info = self._call("drawing_info")
        return (f"Offline mode couldn't map this question to a tool (configure an LLM provider for free-form "
                f"questions). Drawing overview: {info['entity_count']} entities on layers "
                f"{', '.join(info['layers'])}.", None, self.trace, [])

    TYPE_WORDS = {"socket": "SOCKET", "light": "LIGHT", "rcd": "RCD", "breaker": "MCB", "mcb": "MCB",
                  "cable": "CABLE", "resistor": "RESISTOR", "capacitor": "CAPACITOR", "led": "LED",
                  "air conditioner": "AC_UNIT", "water heater": "WATER_HEATER"}

    def _tag_in(self, q: str) -> str | None:
        for cand in re.findall(r"\b([A-Za-z]{1,4}\d+(?:-\d+)?|MAIN)\b", q):
            t = self.t.net.find(cand)
            if t:
                return t
        return None

    def _schematic(self, q: str, ql: str):
        tag = self._tag_in(q)
        if tag and re.search(r"\b(how many|number of)\b.*\bconnected to\b", ql):
            n = self._call("connected_to", tag=tag)["count"]
            return self._ans(f"{n} components are directly connected to {tag}.", n)
        if re.search(r"\b(how many|number of)\b\s+(final\s+)?circuits\b", ql):
            n = self._call("downstream_summary", component_type="MCB")["count"]
            return self._ans(f"The board has {n} final circuits (one per MCB).", n)
        if re.search(r"\b(how many|number of|count)\b.*\bcomponents?\b", ql):
            n = self._call("components")["count"]
            return self._ans(f"There are {n} tagged components.", n)
        m = re.search(r"\b(how many|number of|count)\b.*?\b(sockets?|lights?|rcds?|breakers?|mcbs?|cables?|resistors?|capacitors?|leds?)\b", ql)
        if m:
            word = m.group(2).rstrip("s")
            ctype = self.TYPE_WORDS.get(word, word.upper())
            n = self._call("components", component_type=ctype)["count"]
            return self._ans(f"There are {n} {ctype} components.", n)
        if re.search(r"\bmain switch\b.*\brating\b|\brating\b.*\bmain switch\b", ql):
            v = self._call("component_details", tag="MAIN").get("RATING_A")
            return self._ans(f"The main switch is rated {v} A.", v)
        if tag and re.search(r"\brating of\b", ql):
            v = self._call("component_details", tag=tag).get("RATING_A")
            return self._ans(f"{tag} is rated {v} A.", v)
        if tag and re.search(r"\b(connected load|total load)\b", ql):
            d = self._call("downstream", tag=tag)
            return self._ans(f"Circuit {tag} has a connected load of {_fmt(d['total_LOAD_W'])} W.", d["total_LOAD_W"])
        if tag and re.search(r"\bcable size\b", ql):
            d = self._call("downstream", tag=tag)
            cab = [c for c in d["downstream"] if c["type"] == "CABLE"]
            if cab:
                return self._ans(f"Circuit {tag} is wired in {cab[0]['SIZE_SQMM']} sq mm cable.", cab[0]["SIZE_SQMM"])
        if re.search(r"\btotal cable length\b", ql):
            v = self._call("sum_attribute", attribute="LENGTH_M", component_type="CABLE")["total"]
            return self._ans(f"Total cable length is {_fmt(v)} m.", v)
        if re.search(r"\b(highest|largest|biggest)\b.*\bload\b", ql):
            rows = self._call("downstream_summary", component_type="MCB")["rows"]
            top = max(rows, key=lambda r: r["total_LOAD_W"])
            return self._ans(f"{top['tag']} has the highest connected load ({_fmt(top['total_LOAD_W'])} W).", top["tag"])
        if tag and re.search(r"\bvalue of\b", ql):
            d = self._call("component_details", tag=tag)
            v = d.get("VALUE_OHM") or d.get("VALUE_UF")
            return self._ans(f"{tag} has a value of {v}.", v)
        return None

    def _ans(self, text: str, final):
        final_s = _fmt(final) if isinstance(final, (int, float)) else str(final)
        return f"{text}\nFINAL: {final_s}", final_s, self.trace, []


# ---------------------------------------------------------------------- spec
def spec_answer(q: str, retriever: HybridRetriever, k: int = 2):
    if not retriever.is_answerable(q):
        return "NOT_FOUND: The specification does not appear to cover this.", "NOT_FOUND", [], []
    hits = retriever.search(q, k)
    sources = [{"page": h.chunk.page, "section": h.chunk.section, "text": h.chunk.text} for h in hits]
    body = "\n".join(f"- (page {h.chunk.page}) {h.chunk.text}" for h in hits)
    return f"Most relevant clauses (offline mode shows excerpts, not a written answer):\n{body}", None, [], sources


# ---------------------------------------------------------------- compliance
def _clause(retriever: HybridRetriever, query: str, must: list[str]):
    """Best-ranked chunk containing all `must` words: (text, source, clause id)."""
    for h in retriever.search(query, 8):
        tl = h.chunk.text.lower()
        if all(w in tl for w in must):
            src = {"page": h.chunk.page, "section": h.chunk.section, "text": h.chunk.text}
            clause = re.search(r"(\d+\.\d+)\s", h.chunk.text)
            return h.chunk.text, src, (clause.group(1) if clause else "?")
    return None, None, "?"


def _rule(retriever: HybridRetriever, query: str, must: list[str]):
    text, src, cl = _clause(retriever, query, must)
    m = re.search(r"not less than ([\d.]+)", (text or "").lower())
    return (float(m.group(1)) if m else None), src, cl


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def electrical_compliance(q: str, planner: "HeuristicPlanner", retriever: HybridRetriever):
    ql = q.lower()
    fails: list[str] = []
    rows = planner._call("downstream_summary", component_type="MCB")["rows"]

    if "rcd" in ql or "earth leakage" in ql or ("socket" in ql and "protect" in ql):
        text, src, cl = _clause(retriever, "circuits supplying socket outlets residual current device RCD", ["socket", "rcd"])
        lim = _f(re.search(r"not exceeding (\d+) ma", (text or "").lower()).group(1)) if text else None
        for r in rows:
            if r["feeds"].get("SOCKET"):
                sens = _f((r.get("rcd") or {}).get("SENS_MA"))
                if sens is None:
                    fails.append(f"{r['tag']} has no RCD")
                elif lim is not None and sens > lim:
                    fails.append(f"{r['tag']} RCD is {sens:g} mA > {lim:g} mA")
        head = f"Clause {cl}: socket circuits need an RCD of at most {lim:g} mA."
    elif "lighting" in ql:
        text, src, cl = _clause(retriever, "lighting circuits protected by breakers rated not more than", ["lighting", "not more than"])
        lim = _f(re.search(r"not more than (\d+) a", (text or "").lower()).group(1)) if text else None
        for r in rows:
            if r["feeds"].get("LIGHT") and lim is not None and _f(r.get("RATING_A")) > lim:
                fails.append(f"{r['tag']} lighting breaker {r['RATING_A']} A > {lim:g} A")
        head = f"Clause {cl}: lighting breakers at most {lim:g} A."
    elif "length" in ql or "run" in ql:
        text, src, cl = _clause(retriever, "cable run lengths shall not exceed voltage drop", ["run lengths"])
        table = {float(a): float(b) for a, b in re.findall(r"([\d.]+) sq mm (\d+) m", text or "")}
        for r in rows:
            cab = r.get("cable") or {}
            size, length = _f(cab.get("SIZE_SQMM")), _f(cab.get("LENGTH_M"))
            if size in table and length > table[size]:
                fails.append(f"{r['tag']} cable {length:g} m > {table[size]:g} m for {size:g} sq mm")
        head = f"Clause {cl}: maximum run lengths {', '.join(f'{k:g} sq mm {v:g} m' for k, v in table.items())}."
    elif "load" in ql:
        text, src, cl = _clause(retriever, "connected load final circuit percent breaker rating multiplied", ["percent"])
        tl = (text or "").lower()
        pct = _f(re.search(r"(\d+) percent", tl).group(1)) / 100 if text else None
        volts = _f(re.search(r"(\d+) v\b", tl).group(1)) if text else None
        for r in rows:
            limit = pct * _f(r.get("RATING_A")) * volts
            if r["total_LOAD_W"] > limit:
                fails.append(f"{r['tag']} load {r['total_LOAD_W']:g} W > {limit:g} W")
        head = f"Clause {cl}: circuit load at most {pct:.0%} x breaker rating x {volts:g} V."
    elif "breaker" in ql and ("cable" in ql or "sized" in ql):
        text, src, cl = _clause(retriever, "circuit breaker rating shall not exceed current-carrying capacity of the cable",
                                ["capacit", "sq mm"])
        table = {float(a): float(b) for a, b in re.findall(r"([\d.]+) sq mm cable (\d+) a", (text or "").lower())}
        for r in rows:
            size = _f((r.get("cable") or {}).get("SIZE_SQMM"))
            rating = _f(r.get("RATING_A"))
            if size in table and rating > table[size]:
                fails.append(f"{r['tag']} {rating:g} A breaker on {size:g} sq mm cable (max {table[size]:g} A)")
        head = f"Clause {cl}: breaker rating must not exceed cable capacity."
    else:
        return None
    verdict = "FAIL" if fails else "PASS"
    detail = ("Failing circuits: " + "; ".join(fails) + ".") if fails else "All circuits comply."
    return f"{head} {detail}\nFINAL: {verdict}", verdict, planner.trace, [src] if src else []


def compliance_answer(q: str, planner: HeuristicPlanner, retriever: HybridRetriever):
    planner.trace = []
    ql = q.lower()
    if "schematic" in planner.t.d.summary()["domain"]:
        out = electrical_compliance(q, planner, retriever)
        if out:
            return out
        return ("Offline mode can check breaker sizing, circuit loads, RCD protection, lighting breakers and cable "
                "lengths. Configure an LLM for other compliance questions."), None, planner.trace, []
    fails: list[str] = []
    sources: list[dict] = []

    if "window" in ql:
        _, src, cl = _rule(retriever, "every habitable room window external wall", ["window", "habitable"])
        sources += [src] if src else []
        per = planner._call("count_per_region", layer="WINDOWS", region_layer="ROOMS")["regions"]
        fails = [r["label"] for r in per if r["label"] and r["label"].split()[0] in HABITABLE and r["count"] < 1]
        head = f"Clause {cl} requires a window in every habitable room."
    elif "door" in ql:
        hab, s1, c1 = _rule(retriever, "doors serving habitable rooms clear opening width", ["habitable", "opening"])
        bath, s2, c2 = _rule(retriever, "bathroom door clear opening width", ["bathroom", "opening"])
        sources += [s for s in (s1, s2) if s]
        for d in planner._call("block_inserts", block_name="DOOR")["inserts"]:
            room = (d["in_region"] or "?").upper()
            need = bath if room.startswith("BATH") else hab
            if need is not None and d["scale"] < need:
                fails.append(f"{room} door {d['scale']:g} mm < {need:g} mm")
        head = f"Clauses {c1}/{c2}: habitable-room doors >= {hab:g} mm, bathroom doors >= {bath:g} mm."
    elif "corridor" in ql:
        need, src, cl = _rule(retriever, "minimum clear width internal corridor", ["corridor", "not less than"])
        sources += [src] if src else []
        r = planner._call("labeled_regions", label_contains="CORRIDOR")["regions"]
        w = r[0]["min_side"] if r else None
        if w is None or need is None:
            return "Could not find the corridor or the rule.", None, planner.trace, sources
        if w < need:
            fails.append(f"corridor {w:g} mm < {need:g} mm")
        head = f"Clause {cl}: corridors >= {need:g} mm; this corridor is {w:g} mm."
    elif re.search(r"\b(area|size|rooms?)\b", ql):
        regs = planner._call("labeled_regions", layer="ROOMS")["regions"]
        cls = []
        for typ in HABITABLE:
            need, src, cl = _rule(retriever, f"minimum floor area {typ.lower()}", [typ.lower(), "square metres"])
            if need is None:
                continue
            sources.append(src)
            cls.append(f"{typ.title()} >= {need:g} m² ({cl})")
            for r in regs:
                if r["label"] and r["label"].upper().startswith(typ) and r["area_m2"] < need:
                    fails.append(f"{r['label']} {r['area_m2']:g} m² < {need:g} m²")
        head = "Room size rules: " + "; ".join(cls) + "."
    else:
        return ("Offline mode can check corridors, doors, room areas and windows. Configure an LLM for other "
                "compliance questions."), None, planner.trace, sources

    verdict = "FAIL" if fails else "PASS"
    detail = ("Failing items: " + "; ".join(fails) + ".") if fails else "All checked items comply."
    return f"{head} {detail}\nFINAL: {verdict}", verdict, planner.trace, sources

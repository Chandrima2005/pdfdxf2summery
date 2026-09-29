"""Decide which pipeline answers a question.

compute    - numbers/facts from the drawing        -> geometry / schematic tools
spec       - what the PDF specification says       -> hybrid RAG
visual     - layout / spatial / appearance         -> vision model on the render
compliance - drawing value checked against a rule  -> tools + RAG together
"""
from __future__ import annotations

import re

from cad_copilot.llm.client import LLMClient

ROUTES = ("compute", "spec", "visual", "compliance")

_COMPLIANCE = r"\b(compl(y|ies|iant|iance)|meet|meets|satisf(y|ies)|violat\w*|pass(es)?|fail(s)?|conform\w*|permitted by|allowed by|as the spec requires|per the spec|correctly|within|according to)\b"
_VISUAL = r"\b(where|located|location|layout|look like|looks like|describe the (drawing|plan|layout)|left|right|above|below|next to|adjacent|beside|arrangement|orient\w*|north|south|east|west|opposite|side of)\b"
_SPEC = r"\b(spec|specification|required|requirement|minimum|maximum|shall|allowed|permitted|must|need|needed|should|standard|clause|rule|submission|reviewer|alarm)\b"
_DRAWING = r"\b(this (drawing|plan|part|file)|the (drawing|plan|part)|in the plan|in the drawing|how many|count|total|largest|smallest|overall)\b"


def heuristic_route(q: str, has_drawing: bool = True, has_spec: bool = True) -> str:
    ql = q.lower()
    if not has_spec:
        return "visual" if re.search(_VISUAL, ql) else "compute"
    if not has_drawing:
        return "spec"
    if re.search(_COMPLIANCE, ql) and re.search(r"\b(spec|specification|minimum|required|requires|rule|clause|standard)\b", ql):
        return "compliance"
    if re.search(_VISUAL, ql):
        return "visual"
    if re.search(_SPEC, ql) and not re.search(_DRAWING, ql):
        return "spec"
    return "compute"


ROUTER_SYSTEM = """You route questions for a CAD assistant for construction drawings (building plans, electrical and electronic schematics). It has (a) a parsed DXF drawing with exact geometry and connectivity tools, (b) a PDF specification, and (c) a rendered image of the drawing.
Reply with exactly one word:
compute    - asks for a number or fact from the drawing (counts, areas, lengths, ratings, loads, what a breaker feeds, which room/circuit is largest)
spec       - asks what the specification document says, independent of this drawing
visual     - asks about layout, position or appearance (where is X, what is next to Y)
compliance - asks whether something in the drawing meets a requirement in the specification"""


def llm_route(q: str, llm: LLMClient, has_drawing: bool = True, has_spec: bool = True) -> str:
    try:
        out = llm.complete(ROUTER_SYSTEM, q).strip().lower()
        word = re.findall(r"[a-z]+", out)
        label = word[0] if word else ""
        if label in ROUTES:
            if label in ("spec", "compliance") and not has_spec:
                return "compute"
            if label in ("compute", "visual", "compliance") and not has_drawing:
                return "spec"
            return label
    except Exception:
        pass
    return heuristic_route(q, has_drawing, has_spec)


def route(q: str, llm: LLMClient | None = None, has_drawing: bool = True, has_spec: bool = True) -> str:
    return llm_route(q, llm, has_drawing, has_spec) if llm else heuristic_route(q, has_drawing, has_spec)

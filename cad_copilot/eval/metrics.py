"""Scoring functions. Each returns True/False (or None when a human must judge)."""
from __future__ import annotations

import re

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def parse_number(s: str | None) -> float | None:
    if s is None:
        return None
    m = _NUM.findall(str(s).replace(",", ""))
    return float(m[0]) if m else None


def score(q: dict, final: str | None, text: str, sources: list[dict]) -> bool | None:
    t = q["answer_type"]
    exp = q["expected"]
    if t == "number":
        v = parse_number(final)
        return v is not None and abs(v - float(exp)) <= max(0.01, 0.01 * abs(float(exp)))
    if t == "label":
        got = (final or "").upper()
        return any(opt.upper() == got or (got and opt.upper() in got) for opt in str(exp).split("|"))
    if t == "verdict":
        return (final or "").upper().startswith(str(exp))
    if t == "not_found":
        return (final or "") == "NOT_FOUND" or text.strip().startswith("NOT_FOUND")
    if t == "clause":
        # Correct if the answer (LLM) or the shown excerpts (offline) contain the right clause.
        pat = re.compile(r"(?<![\d.])" + re.escape(exp) + r"(?![\d])")
        if pat.search(text):
            return True
        return any(pat.search(s.get("text", "")) for s in sources[:2])
    return None  # manual review (visual)


def clause_in(text: str, clause: str) -> bool:
    return re.search(r"(^|\s)" + re.escape(clause) + r"\s", text) is not None

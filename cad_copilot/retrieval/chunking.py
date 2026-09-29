"""Three chunking strategies, so the eval can compare them.

fixed      - sliding character window (the common default; ignores structure)
sentence   - groups of consecutive sentences
structure  - splits at numbered headings/clauses ("3.2 ...") and prefixes each
             chunk with its section title, so the chunk is self-describing
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from cad_copilot.parsing.pdf_parser import Page

CLAUSE_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)\s+\S")   # 3.2 The clear width...
HEADING_RE = re.compile(r"^\s*(\d+)\s+[A-Z][^\n]{2,60}$")  # 3 Corridors and Circulation


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    page: int
    section: str | None = None


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def fixed_chunks(pages: list[Page], size: int = 500, overlap: int = 100) -> list[Chunk]:
    out = []
    for p in pages:
        t = _clean(p.text.replace("\n", " "))
        i = 0
        while i < len(t):
            out.append(Chunk(f"{p.source}:p{p.page}:f{len(out)}", t[i:i + size], p.source, p.page))
            i += size - overlap
    return out


def sentence_chunks(pages: list[Page], per_chunk: int = 3) -> list[Chunk]:
    out = []
    for p in pages:
        sents = re.split(r"(?<=[.!?])\s+", _clean(p.text.replace("\n", " ")))
        for i in range(0, len(sents), per_chunk):
            out.append(Chunk(f"{p.source}:p{p.page}:s{len(out)}", " ".join(sents[i:i + per_chunk]), p.source, p.page))
    return out


def structure_chunks(pages: list[Page], max_chars: int = 900) -> list[Chunk]:
    out: list[Chunk] = []
    section = None
    for p in pages:
        buf: list[str] = []

        def flush():
            if buf:
                body = _clean(" ".join(buf))
                prefix = f"[{section}] " if section else ""
                out.append(Chunk(f"{p.source}:p{p.page}:c{len(out)}", (prefix + body)[: max_chars], p.source, p.page, section))
                buf.clear()

        for line in p.text.splitlines():
            if HEADING_RE.match(line) and not CLAUSE_RE.match(line):
                flush()
                section = line.strip()
            elif CLAUSE_RE.match(line):
                flush()
                buf.append(line)
            elif line.strip():
                buf.append(line)
        flush()
    return out


STRATEGIES = {"fixed": fixed_chunks, "sentence": sentence_chunks, "structure": structure_chunks}


def chunk_pages(pages: list[Page], strategy: str = "structure") -> list[Chunk]:
    return STRATEGIES[strategy](pages)

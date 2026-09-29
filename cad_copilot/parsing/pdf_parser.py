"""Extract page-numbered text from a PDF so every answer can cite its page.

Scanned PDFs have no text layer; pass `ocr` (page PNG -> text, e.g. a vision LLM) to read them.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pymupdf

MAX_OCR_PAGES = 60


@dataclass
class Page:
    source: str
    page: int  # 1-based, as a human would cite it
    text: str


class ScannedPdfError(ValueError):
    """The PDF has no text layer and no OCR was available."""


def parse_pdf(path: str | Path, ocr: Callable[[bytes], str] | None = None, dpi: int = 150) -> list[Page]:
    name = Path(path).name
    texts: dict[int, str] = {}
    scanned: dict[int, bytes] = {}
    with pymupdf.open(str(path)) as doc:
        for i, pg in enumerate(doc):
            text = pg.get_text("text").strip()
            if text:
                texts[i + 1] = text
            elif ocr and len(scanned) < MAX_OCR_PAGES:
                scanned[i + 1] = pg.get_pixmap(dpi=dpi).tobytes("png")  # render here: pymupdf is not thread-safe
    if scanned:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for num, text in zip(scanned, pool.map(ocr, scanned.values())):
                if text and text.strip():
                    texts[num] = text.strip()
    if not texts:
        raise ScannedPdfError(f"{name} is a scanned PDF with no text layer, so it needs OCR (reading the page images) first.")
    return [Page(source=name, page=n, text=texts[n]) for n in sorted(texts)]

"""CAD Copilot web app: serves the HTML/CSS/JS frontend in app/web plus a small JSON API.

Run:  uvicorn app.server:app --port 8501        (desktop copy: python app/run_desktop.py)

APP_MODE=web (default) is always online; APP_MODE=desktop also allows the offline rule-based mode.

GET  /                         landing page            GET  /app                    workspace
GET  /api/config               mode + availability     GET  /api/samples            sample catalog
GET  /api/drawing/{id}         summary, board, spec    GET  /api/image/{id}?size=   rendered PNG
POST /api/upload   (file)      -> {"id"}               POST /api/ask                -> answer
GET  /api/download             desktop zip
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
import pymupdf  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from cad_copilot import config  # noqa: E402
from cad_copilot.agent.agent import FINAL_RULE, CadCopilot, _excerpts, extract_final  # noqa: E402
from cad_copilot.llm.client import get_client  # noqa: E402
from cad_copilot.parsing.dxf_parser import parse_dxf  # noqa: E402
from cad_copilot.parsing.pdf_parser import ScannedPdfError  # noqa: E402
from cad_copilot.parsing.render import cached_png  # noqa: E402
from cad_copilot.retrieval.hybrid import build_retriever  # noqa: E402
from cad_copilot.spec_content import SPECS  # noqa: E402
from cad_copilot.tools.geometry_tools import DrawingTools  # noqa: E402

WEB = ROOT / "app" / "web"
SAMPLES = ROOT / "data" / "samples"
PREVIEWS = ROOT / "data" / "previews"          # pre-rendered sample images (rendering takes ~2 s each)
UPLOADS = Path(tempfile.gettempdir()) / "cadcopilot_uploads"
DESKTOP = config.APP_MODE == "desktop"
MAX_UPLOAD = 50 * 1024 * 1024

CATEGORIES = [  # distribution boards are the core use; all three are showcased
    {"id": "db", "label": "Distribution boards", "icon": "⚡", "badge": "CORE"},
    {"id": "plan", "label": "Building plans", "icon": "🏠", "badge": "BUILDINGS"},
    {"id": "ckt", "label": "Circuits", "icon": "🔌", "badge": "ELECTRONICS"},
]
KIND = {"db": "Distribution board", "plan": "Floor plan", "ckt": "Circuit"}
EXAMPLES = {
    "db": ["How many circuits are in this distribution board?",
           "What is the total connected load of circuit C1 in watts?",
           "Which circuit has the highest connected load?",
           "Are all socket circuits protected by an RCD as the spec requires?",
           "Do all lighting circuits meet the breaker rating limit in the spec?"],
    "plan": ["How many rooms are in this plan?",
             "What is the area of the KITCHEN in square metres?",
             "Does the corridor meet the minimum width required by the spec?",
             "Does every habitable room have a window as the spec requires?",
             "What is the minimum bedroom size in the spec?"],
    "ckt": ["How many components are on the schematic?",
            "How many resistors are in the circuit?",
            "What is the value of R3 in ohms?",
            "How many components are directly connected to C1?"],
}
PDF_EXAMPLES = ["Summarise what this drawing shows.",
                "List every instrument or equipment tag on the drawing.",
                "What line sizes and line numbers are shown?",
                "Which items are connected to the motor-operated valve?"]
PDF_SYSTEM = """You are CAD Copilot, reading a PDF the user uploaded: usually an engineering drawing (a P&ID,
a single-line diagram, a schematic or a floor plan), sometimes a text document. You get the image of the page on
screen plus passages found anywhere in the document. Answer only from this uploaded document, never from other
drawings; cite the page, like (p.3).
- Quote tags, labels, line numbers and values exactly as written. If something is unreadable, say so rather than guess.
- Values come from labels printed on the drawing, not from measured geometry; say so when you give dimensions.
- If specification excerpts are given, check against them and cite clause and page, like (clause 3.2, p.2).
- Be concise; use a short list when listing items. {final}"""
MAX_PAGE_PX = 2000
_FILE_ID = re.compile(r"^[\w.-]+$")


# ------------------------------------------------------------------ files and caches
def _path(file_id: str, suffix: str) -> Path:
    """Resolve a sample name or upload id to a file; anything else is a 404 (no path traversal)."""
    if _FILE_ID.match(file_id or "") and file_id.lower().endswith(suffix):
        for folder in (SAMPLES, UPLOADS):
            if (folder / file_id).is_file():
                return folder / file_id
    raise HTTPException(404, "Unknown file")


def _drawing_path(file_id: str) -> Path:
    """A drawing is a DXF (measured with code) or a PDF (read from the page image)."""
    return _path(file_id, ".pdf" if (file_id or "").lower().endswith(".pdf") else ".dxf")


@lru_cache(maxsize=32)
def _pdf_meta(path: str) -> dict:
    with pymupdf.open(path) as doc:
        texts = [pg.get_text("text").strip() for pg in doc]
        return {"pages": len(doc), "texts": texts, "scanned": not any(texts)}


@lru_cache(maxsize=64)
def _pdf_png(path: str, page: int, size: str) -> bytes:
    """Render one PDF page; large sheets are scaled so the longest side is at most MAX_PAGE_PX."""
    with pymupdf.open(path) as doc:
        pg = doc[max(0, min(page, len(doc)) - 1)]
        longest = max(pg.rect.width, pg.rect.height) or 1
        target = 480 if size == "thumb" else MAX_PAGE_PX
        zoom = min(target / longest, 3.0)
        return pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")


def _doc_hits(pdf: Path, question: str, online: bool, k: int = 4) -> list:
    """Search the uploaded PDF itself, so questions about any page are answered, not only the page on screen."""
    try:
        return _retriever(str(pdf), online).search(question, k)
    except Exception:  # scanned with no OCR available, or no text at all: the page image is still read
        return []


def _ask_pdf(pdf: Path, page: int, question: str, spec: Path | None, llm, online: bool) -> dict:
    t0 = time.time()
    meta = _pdf_meta(str(pdf))
    page = max(1, min(page, meta["pages"]))
    doc_hits = _doc_hits(pdf, question, online)
    spec_hits = _retriever(str(spec), online).search(question, 4) if spec and spec != pdf else []
    sources = [{"page": h.chunk.page, "section": h.chunk.section, "text": h.chunk.text} for h in doc_hits + spec_hits]
    if llm is None:
        if not doc_hits:
            return {"question": question, "route": "error", "final": None, "trace": [], "sources": [], "latency_s": 0,
                    "text": "This PDF has no selectable text, so it can only be read by the online AI. Switch to "
                            "**Online**, or upload the DXF version of this drawing."}
        text = "Most relevant passages in **" + _title(pdf) + "**:\n\n" + "\n".join(
            f"- (p.{h.chunk.page}) {h.chunk.text[:400]}" for h in doc_hits[:3])
        return {"question": question, "route": "spec", "text": text, "final": None, "sources": sources,
                "trace": [{"tool": "search_document", "args": {"query": question}, "result": f"{len(doc_hits)} passages"}],
                "latency_s": round(time.time() - t0, 2)}
    parts = [f"Document: {_title(pdf)}, {meta['pages']} page(s). The image shows page {page}."]
    if meta["texts"][page - 1]:
        parts.append(f"Text on page {page}:\n" + meta["texts"][page - 1][:6000])
    if doc_hits:
        parts.append("Relevant passages from the whole document:\n" + _excerpts(doc_hits))
    if spec_hits:
        parts.append("Specification excerpts:\n" + _excerpts(spec_hits))
    parts.append(f"Question: {question}")
    text = llm.complete(PDF_SYSTEM.format(final=FINAL_RULE), "\n\n".join(parts), _pdf_png(str(pdf), page, "full"))
    trace = [{"tool": "read_drawing_image", "args": {"page": page}, "result": "page image sent to the model"}]
    if doc_hits:
        trace.append({"tool": "search_document", "args": {"query": question}, "result": f"{len(doc_hits)} passages"})
    return {"question": question, "route": "visual", "text": text, "final": extract_final(text),
            "trace": trace, "sources": sources, "latency_s": round(time.time() - t0, 2)}


def _is_sample(p: Path) -> bool:
    return p.parent == SAMPLES


def _manifest_spec(dxf: Path) -> str | None:
    manifest = dxf.with_suffix(".json")
    return json.loads(manifest.read_text()).get("spec") if _is_sample(dxf) and manifest.exists() else None


def _sample_spec(dxf: Path) -> Path | None:
    name = _manifest_spec(dxf)
    return SAMPLES / SPECS[name]["file"] if name else None


def _title(p: Path) -> str:
    if _is_sample(p):
        prefix, _, num = p.stem.partition("-")
        return f"{KIND.get(prefix, prefix)} {num}"
    return p.name.split("-", 2)[-1]  # uploads are stored as up-<hash>-<original name>


def _prefix(p: Path, domain: str) -> str:
    if _is_sample(p):
        return p.stem.split("-")[0]
    return "plan" if "floor plan" in domain else "db"


@lru_cache(maxsize=64)
def _drawing(path: str):
    return parse_dxf(path)


OCR_PROMPT = ("You transcribe scanned pages of engineering design specifications. Copy all text on the page exactly, "
              "keeping clause numbers, headings and values. Write table rows one per line with cells separated by ' | '. "
              "Output only the page text, no commentary.")
_RETRIEVERS: dict[str, object] = {}


def _retriever(path: str, allow_ocr: bool = False):
    """Index a spec once. Scanned pages are read by the online vision model, but only when online is allowed,
    so an offline desktop session never sends a document out."""
    if path not in _RETRIEVERS:
        llm = _llm()[0] if allow_ocr else None
        ocr = (lambda png: llm.complete(OCR_PROMPT, "Transcribe this page.", png)) if llm else None
        _RETRIEVERS[path] = build_retriever(path, config.CHUNK_STRATEGY, ocr=ocr)
    return _RETRIEVERS[path]


@lru_cache(maxsize=1)
def _llm():
    try:
        return get_client("openai"), None
    except Exception as exc:
        return None, str(exc)


@lru_cache(maxsize=64)
def _board(path: str) -> list[dict]:
    """One row per final circuit - empty for drawings that are not distribution boards."""
    try:
        r = DrawingTools(_drawing(path)).call("downstream_summary", {})
    except Exception:
        return []
    return r.get("rows", []) if isinstance(r, dict) else []


def _png(p: Path, size: str) -> bytes:
    folder = PREVIEWS if _is_sample(p) else UPLOADS / "png"
    return cached_png(p, folder, dpi=80, size_in=8) if size == "thumb" else cached_png(p, folder)


def _warm():
    """Load the showcase drawings, specs and model client in the background so the first click is instant."""
    for name in ("db-001.dxf", "plan-001.dxf", "ckt-001.dxf"):
        p = SAMPLES / name
        if p.exists():
            _drawing(str(p))
            _board(str(p))
            if (spec := _sample_spec(p)):
                _retriever(str(spec))
    if not DESKTOP or config.OPENAI_API_KEY:
        _llm()


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_warm, daemon=True).start()
    yield


app = FastAPI(title="CAD Copilot", version="2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.middleware("http")
async def revalidate_pages(request, call_next):
    """Pages, scripts and styles are re-checked on every load (cheap 304s), so an update is never hidden by a stale cache."""
    response = await call_next(request)
    if request.url.path in ("/", "/app") or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ------------------------------------------------------------------ pages
@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(WEB / "index.html")


@app.get("/app", include_in_schema=False)
def workspace():
    return FileResponse(WEB / "app.html")


# ------------------------------------------------------------------ API
@app.get("/api/config")
def get_config():
    return {"desktop": DESKTOP,
            "default_mode": "online" if (not DESKTOP or config.OPENAI_API_KEY) else "offline"}


@app.get("/api/samples")
def samples():
    cats = []
    for c in CATEGORIES:
        items = []
        for p in sorted(SAMPLES.glob(f"{c['id']}-*.dxf")):
            spec = _manifest_spec(p)
            items.append({"id": p.name, "title": _title(p), "short": p.stem.split("-")[-1],
                          "spec": SPECS[spec]["title"] if spec else None})
        cats.append({**c, "samples": items})
    return {"categories": cats}


@app.get("/api/drawing/{file_id}")
def drawing_info(file_id: str):
    p = _drawing_path(file_id)
    if p.suffix.lower() == ".pdf":
        meta = _pdf_meta(str(p))
        return {"id": file_id, "kind": "pdf", "title": _title(p), "pages": meta["pages"], "scanned": meta["scanned"],
                "domain": "PDF drawing · read by the online AI", "spec": None, "board": [], "warnings": [],
                "examples": PDF_EXAMPLES, "image": f"/api/image/{file_id}"}
    d = _drawing(str(p))
    s = d.summary()
    spec_name = _manifest_spec(p)
    return {"id": file_id, "kind": "dxf", "title": _title(p), "domain": s.get("domain", ""), "entities": s["entity_count"],
            "layers": s["layers"], "units": s["units"], "text": s["text_annotations"], "warnings": d.warnings,
            "spec": {"id": SPECS[spec_name]["file"], "title": SPECS[spec_name]["title"]} if spec_name else None,
            "board": _board(str(p)), "examples": EXAMPLES[_prefix(p, s.get("domain", ""))],
            "image": f"/api/image/{file_id}"}


@app.get("/api/image/{file_id}")
def image(file_id: str, size: str = "full", page: int = 1):
    p = _drawing_path(file_id)
    data = _pdf_png(str(p), page, size) if p.suffix.lower() == ".pdf" else _png(p, size)
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), mode: str = Form("online"), role: str = Form("spec")):
    name = file.filename or ""
    suffix = Path(name).suffix.lower()
    if suffix not in (".dxf", ".pdf"):
        raise HTTPException(400, "Upload a .dxf or .pdf drawing, or a .pdf specification")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 50 MB")
    safe = re.sub(r"[^\w.-]+", "_", Path(name).stem)[:40] or "file"
    file_id = f"up-{hashlib.md5(data).hexdigest()[:12]}-{safe}{suffix}"
    UPLOADS.mkdir(parents=True, exist_ok=True)
    path = UPLOADS / file_id
    path.write_bytes(data)
    online = mode != "offline" or not DESKTOP
    try:
        if suffix == ".dxf":
            _drawing(str(path))
        elif role == "drawing":
            _pdf_meta(str(path))  # just check it opens; the page image is read when a question is asked
        else:
            _retriever(str(path), allow_ocr=online)
    except ScannedPdfError:
        path.unlink(missing_ok=True)
        hint = ("Switch to Online so the AI can read the page images, or upload a PDF with selectable text."
                if not online else "The online AI is not available to read it right now; upload a PDF with selectable text.")
        raise HTTPException(422, f"{name} is a scanned PDF (pages are images, no text). {hint}")
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, f"Could not read {name}: {exc}")
    return {"id": file_id, "name": name}


class Ask(BaseModel):
    question: str
    drawing: str | None = None
    spec: str | None = None
    mode: str = "online"
    page: int = 1  # for PDF drawings


@app.post("/api/ask")
def ask(body: Ask):
    drawing = _drawing_path(body.drawing) if body.drawing else None
    spec = _path(body.spec, ".pdf") if body.spec else (_sample_spec(drawing) if drawing else None)
    online = body.mode != "offline" or not DESKTOP  # the hosted web app is always online
    llm, err = _llm() if online else (None, None)
    if drawing is not None and drawing.suffix.lower() == ".pdf":
        try:
            ans = _ask_pdf(drawing, body.page, body.question, spec, llm, online)
        except Exception as exc:
            ans = {"question": body.question, "route": "error", "text": f"Something failed: {exc}",
                   "final": None, "trace": [], "sources": [], "latency_s": 0}
        ans["fallback"] = bool(online and err)
        return json.loads(json.dumps(ans, default=str))
    dxf = drawing
    copilot = CadCopilot(_drawing(str(dxf)) if dxf else None, _retriever(str(spec), online) if spec else None, llm,
                         _png(dxf, "full") if (dxf and llm) else None)
    try:
        ans = copilot.answer(body.question).to_dict()
    except Exception as exc:
        ans = {"question": body.question, "route": "error", "text": f"Something failed: {exc}",
               "final": None, "trace": [], "sources": [], "latency_s": 0}
    ans["fallback"] = bool(online and err)  # online was wanted but the model could not start
    return json.loads(json.dumps(ans, default=str))


# ------------------------------------------------------------------ desktop download
RUN_BAT = r"""@echo off
title CAD Copilot
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ and tick "Add to PATH".
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo First run: installing CAD Copilot. This takes a few minutes...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
set APP_MODE=desktop
".venv\Scripts\python.exe" app\run_desktop.py
pause
"""

RUN_SH = """#!/usr/bin/env sh
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }
if [ ! -x .venv/bin/python ]; then
  echo "First run: installing CAD Copilot. This takes a few minutes..."
  python3 -m venv .venv && .venv/bin/python -m pip install -q -r requirements.txt || exit 1
fi
APP_MODE=desktop exec .venv/bin/python app/run_desktop.py
"""

DESKTOP_README = """CAD Copilot - desktop app
=========================

Start it
  Windows      double-click run.bat
  Mac / Linux  open a terminal here and run:  sh run.sh

The first start installs everything (needs Python 3.10+ and internet, a few minutes).
After that it opens in your browser (usually http://127.0.0.1:8501, or the next free port).
The top bar of the workspace has an Online / Offline switch.

Modes
  Offline  works with no internet and no API key (fixed question patterns).
  Online   free-form questions and vision. Copy .env.example to .env and fill in
           OPENAI_API_KEY, OPENAI_BASE_URL and LLM_MODEL, then restart.
"""


@lru_cache(maxsize=1)
def _desktop_zip() -> bytes:
    """The app for offline use. Never includes .env files, virtualenvs or caches."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        files = [ROOT / "app" / "server.py", ROOT / "app" / "run_desktop.py", *WEB.rglob("*"),
                 *ROOT.glob("cad_copilot/**/*.py"), *SAMPLES.glob("*"), *PREVIEWS.glob("*.png"),
                 ROOT / "requirements.txt", ROOT / ".env.example", ROOT / "LICENSE"]
        for f in files:
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f"cad-copilot/{f.relative_to(ROOT).as_posix()}")
        z.writestr("cad-copilot/run.bat", RUN_BAT.replace("\n", "\r\n"))
        z.writestr("cad-copilot/run.sh", RUN_SH)
        z.writestr("cad-copilot/README.txt", DESKTOP_README)
    return buf.getvalue()


@app.get("/api/download")
def download():
    return Response(_desktop_zip(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="cad-copilot-desktop.zip"'})


@app.get("/health")
def health():
    return {"status": "ok", "desktop": DESKTOP}

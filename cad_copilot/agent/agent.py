"""CadCopilot: routes each question to tools, RAG, vision, or tools+RAG."""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field

from cad_copilot import config
from cad_copilot.agent import heuristic
from cad_copilot.agent.router import route as route_question
from cad_copilot.llm.client import LLMClient
from cad_copilot.parsing.dxf_parser import Drawing, parse_dxf, to_compact_text
from cad_copilot.retrieval.hybrid import Embedder, HybridRetriever, build_retriever
from cad_copilot.tools.geometry_tools import TOOL_SCHEMAS, DrawingTools

FINAL_RULE = ("Finish with a final line exactly: FINAL: <answer> - a bare number (no units, no commas) for "
              "quantities, PASS or FAIL for compliance checks, or a short label such as a room name.")

DOMAIN_HINTS = """How drawings are represented:
- Building plans: rooms, corridors and part outlines are labelled closed polylines -> labeled_regions
  (area_m2; min_side = corridor width). Doors are DOOR blocks: scale = door width; block_inserts gives the room
  each door opens into. Windows per room: count_per_region(layer="WINDOWS", region_layer="ROOMS").
- Electrical / electronic schematics: devices and loads are blocks with attributes (TAG, RATING_A, LOAD_W,
  SIZE_SQMM, LENGTH_M, SENS_MA, VALUE_OHM, VALUE_UF...). Units are in the attribute name (_A amps, _W watts,
  _M metres, _SQMM square mm, _MA milliamps, _OHM ohms). Conductors join them. Use components,
  component_details, connected_to, downstream (what a breaker feeds and its total load), downstream_summary
  (one row per circuit with its breaker, RCD, cable and load), bill_of_materials and sum_attribute."""

COMPUTE_SYSTEM = """You are CAD Copilot, answering questions about one construction drawing by calling tools.
Rules:
- Every number in your answer must come from a tool result. Never estimate or do geometry in your head.
- Drawing units: {units}. Convert only when asked (1 m = 1000 mm).
""" + DOMAIN_HINTS + """
- Answer in 1-3 sentences. {final}

Drawing overview:
{summary}"""

SPEC_SYSTEM = """You answer questions about a design specification using ONLY the excerpts provided.
Cite the clause number and page for every claim, like (clause 3.2, p.2).
If the excerpts do not contain the answer, reply exactly: NOT_FOUND: The specification does not cover this.
Be concise."""

COMPLIANCE_SYSTEM = """You are CAD Copilot checking a drawing against a design specification.
- Get every drawing value from the tools (never estimate). Drawing units: {units}.
- Take requirements only from the specification excerpts below; cite clause and page.
""" + DOMAIN_HINTS + """
- Check every relevant item (every room, door or circuit) and list the ones that fail. {final}

Specification excerpts:
{excerpts}

Drawing overview:
{summary}"""

VISUAL_SYSTEM = """You are looking at a rendered construction drawing (a building plan or a schematic), with a text summary of its layers, blocks and labels.
Answer the question about layout, position or appearance. If the image does not show enough to answer, say so.
Be concise."""

RAW_SYSTEM = """You are given a CAD drawing as a list of entities (block inserts list their attributes). Answer the question from this data.
Drawing units are stated at the top. {final}"""


@dataclass
class Answer:
    question: str
    route: str
    text: str
    final: str | None = None
    trace: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    latency_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def extract_final(text: str) -> str | None:
    if text.strip().startswith("NOT_FOUND"):
        return "NOT_FOUND"
    m = re.findall(r"FINAL:\s*(.+)", text)
    return m[-1].strip().strip("*` .") if m else None


def _excerpts(hits) -> str:
    return "\n".join(f"[{i + 1}] (page {h.chunk.page}{'; ' + h.chunk.section if h.chunk.section else ''}) {h.chunk.text}"
                     for i, h in enumerate(hits))


class CadCopilot:
    def __init__(self, drawing: Drawing | None = None, retriever: HybridRetriever | None = None,
                 llm: LLMClient | None = None, image_png: bytes | None = None):
        self.drawing = drawing
        self.tools = DrawingTools(drawing) if drawing else None
        self.retriever = retriever
        self.llm = llm
        self._image = image_png

    @classmethod
    def from_files(cls, dxf_path: str | None = None, pdf_path: str | None = None, llm: LLMClient | None = None,
                   strategy: str | None = None, embedder: Embedder | None = None) -> "CadCopilot":
        drawing = parse_dxf(dxf_path) if dxf_path else None
        retriever = build_retriever(pdf_path, strategy or config.CHUNK_STRATEGY, embedder) if pdf_path else None
        return cls(drawing, retriever, llm)

    @property
    def image(self) -> bytes | None:
        if self._image is None and self.drawing is not None:
            from cad_copilot.parsing.render import render_png
            self._image = render_png(self.drawing.path)
        return self._image

    # ------------------------------------------------------------------ public
    def answer(self, question: str, route: str | None = None) -> Answer:
        t0 = time.time()
        r = route or route_question(question, self.llm, self.drawing is not None, self.retriever is not None)
        handler = {"compute": self._compute, "spec": self._spec, "visual": self._visual,
                   "compliance": self._compliance}[r]
        text, final, trace, sources = handler(question)
        return Answer(question, r, text, final if final is not None else extract_final(text),
                      trace, sources, round(time.time() - t0, 2))

    def raw_baseline(self, question: str) -> Answer:
        """Baseline for the eval: the LLM reads the entity dump directly, no tools."""
        if not self.llm:
            raise RuntimeError("The raw baseline needs an LLM provider.")
        t0 = time.time()
        text = self.llm.complete(RAW_SYSTEM.format(final=FINAL_RULE),
                                 f"{to_compact_text(self.drawing)}\n\nQuestion: {question}")
        return Answer(question, "raw", text, extract_final(text), [], [], round(time.time() - t0, 2))

    # ------------------------------------------------------------------ routes
    def _need_drawing(self):
        if not self.tools:
            return "Please upload a DXF drawing first.", None, [], []

    def _compute(self, q: str):
        if (miss := self._need_drawing()):
            return miss
        if not self.llm:
            return heuristic.HeuristicPlanner(self.tools).compute(q)
        system = COMPUTE_SYSTEM.format(units=self.drawing.units, final=FINAL_RULE, summary=self.drawing.summary_text())
        text, trace = self.llm.run_tool_loop(system, q, TOOL_SCHEMAS, self.tools.call)
        return text, None, trace, []

    def _spec(self, q: str):
        if not self.retriever:
            return "Please upload a specification PDF first.", None, [], []
        if not self.llm:
            return heuristic.spec_answer(q, self.retriever)
        if not self.retriever.is_answerable(q):  # only rejects clearly off-topic questions
            return "NOT_FOUND: The specification does not cover this.", "NOT_FOUND", [], []
        hits = self.retriever.search(q, 4)
        sources = [{"page": h.chunk.page, "section": h.chunk.section, "text": h.chunk.text} for h in hits]
        text = self.llm.complete(SPEC_SYSTEM, f"Excerpts:\n{_excerpts(hits)}\n\nQuestion: {q}")
        return text, None, [], sources

    def _visual(self, q: str):
        if (miss := self._need_drawing()):
            return miss
        if not self.llm:
            return ("Layout questions need a vision-capable LLM (set LLM_PROVIDER). Meanwhile, here is the "
                    "drawing overview:\n" + self.drawing.summary_text()), None, [], []
        text = self.llm.complete(VISUAL_SYSTEM, f"Summary:\n{self.drawing.summary_text()}\n\nQuestion: {q}", self.image)
        return text, None, [{"tool": "vision", "args": {"image": "rendered drawing"}, "result": "image sent"}], []

    def _compliance(self, q: str):
        if (miss := self._need_drawing()):
            return miss
        if not self.retriever:
            return "Compliance checks need a specification PDF.", None, [], []
        if not self.llm:
            return heuristic.compliance_answer(q, heuristic.HeuristicPlanner(self.tools), self.retriever)
        hits = self.retriever.search(q, 5)
        sources = [{"page": h.chunk.page, "section": h.chunk.section, "text": h.chunk.text} for h in hits]
        system = COMPLIANCE_SYSTEM.format(units=self.drawing.units, final=FINAL_RULE, excerpts=_excerpts(hits),
                                          summary=self.drawing.summary_text())
        text, trace = self.llm.run_tool_loop(system, q, TOOL_SCHEMAS, self.tools.call)
        return text, None, trace, sources

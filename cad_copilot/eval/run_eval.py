"""Run the benchmark and write results tables.

    # offline (no API key): rule-based planner + retrieval + router benchmarks
    python -m cad_copilot.eval.run_eval --provider heuristic

    # with an LLM, plus the "LLM reads raw DXF" baseline for the headline comparison
    python -m cad_copilot.eval.run_eval --provider openai --raw-baseline
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from cad_copilot.agent.agent import CadCopilot
from cad_copilot.agent.router import heuristic_route, llm_route
from cad_copilot.eval.metrics import clause_in, score
from cad_copilot.llm.client import get_client
from cad_copilot.parsing.dxf_parser import parse_dxf
from cad_copilot.parsing.pdf_parser import parse_pdf
from cad_copilot.retrieval.chunking import STRATEGIES, chunk_pages
from cad_copilot.retrieval.hybrid import Embedder, HybridRetriever
from cad_copilot.spec_content import SPECS


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}% ({a}/{b})" if b else "n/a"


def retrieval_benchmark(pdf: str, embedder: Embedder, qa: list[tuple[str, str]], spec: str) -> list[dict]:
    pages = parse_pdf(pdf)
    rows = []
    for strat in STRATEGIES:
        r = HybridRetriever(chunk_pages(pages, strat), embedder)
        avg_len = sum(len(c.text) for c in r.chunks) / len(r.chunks)
        for mode in ("bm25", "dense", "hybrid"):
            h1 = h3 = 0
            chars3 = 0
            for q, clause in qa:
                hits = r.search(q, 3, mode)
                h1 += clause_in(hits[0].chunk.text, clause)
                h3 += any(clause_in(h.chunk.text, clause) for h in hits)
                chars3 += sum(len(h.chunk.text) for h in hits)
            rows.append({"spec": spec, "strategy": strat, "mode": mode, "chunks": len(r.chunks), "avg_chunk_chars": round(avg_len),
                         "recall@1": h1 / len(qa), "recall@3": h3 / len(qa),
                         "context_chars@3": round(chars3 / len(qa))})
    return rows


def run(questions: list[dict], samples: str, provider: str, raw_baseline: bool, limit: int | None,
        strategy: str) -> dict:
    llm = get_client(provider)
    embedder = Embedder()
    retrievers = {name: HybridRetriever(chunk_pages(parse_pdf(f"{samples}/{cfg['file']}"), strategy), embedder)
                  for name, cfg in SPECS.items()}
    agents: dict[tuple, CadCopilot] = {}
    if limit:
        questions = questions[:limit]

    rows = []
    for i, q in enumerate(questions):
        dxf, spec = q["drawing"], q.get("spec")
        if (dxf, spec) not in agents:
            agents[(dxf, spec)] = CadCopilot(parse_dxf(f"{samples}/{dxf}"), retrievers.get(spec), llm)
        agent = agents[(dxf, spec)]
        has_spec = spec is not None
        route_h = heuristic_route(q["question"], True, has_spec)
        route_l = llm_route(q["question"], llm, True, has_spec) if llm else None
        try:
            a = agent.answer(q["question"])
            ok = score(q, a.final, a.text, a.sources)
            row = {**q, "route": a.route, "final": a.final, "correct": ok, "latency_s": a.latency_s,
                   "tool_calls": len(a.trace), "answer": a.text[:600]}
        except Exception as exc:
            row = {**q, "route": None, "final": None, "correct": False, "error": str(exc)}
        row["route_heuristic_ok"] = route_h == q["expected_route"]
        row["route_llm_ok"] = (route_l == q["expected_route"]) if route_l else None
        if raw_baseline and llm and q["kind"] == "compute":
            try:
                b = agent.raw_baseline(q["question"])
                row["raw_final"], row["raw_correct"] = b.final, score(q, b.final, b.text, [])
            except Exception as exc:
                row["raw_final"], row["raw_correct"] = None, False
                row["raw_error"] = str(exc)
        rows.append(row)
        print(f"[{i + 1}/{len(questions)}] {q['kind']:<12} {'OK ' if row['correct'] else ('-- ' if row['correct'] is None else 'XX ')} {q['question'][:70]}")
    retrieval = []
    for name, cfg in SPECS.items():
        retrieval += retrieval_benchmark(f"{samples}/{cfg['file']}", embedder, cfg["qa"], name)
    return {"provider": provider, "embedder": embedder.kind, "strategy": strategy, "rows": rows,
            "retrieval": retrieval}


def summarize(res: dict) -> str:
    rows = res["rows"]
    by = defaultdict(list)
    for r in rows:
        by[r["kind"]].append(r)
    L = [f"# CAD Copilot eval results", "",
         f"- Provider: `{res['provider']}`  |  embeddings: `{res['embedder']}`  |  chunking: `{res['strategy']}`",
         f"- Questions: {len(rows)}  |  generated {time.strftime('%Y-%m-%d %H:%M')}", "",
         "## Accuracy by question type", "", "| Type | Accuracy |", "|---|---|"]
    for kind in ("compute", "compliance", "spec", "unanswerable"):
        rs = by.get(kind, [])
        if rs:
            L.append(f"| {kind} | {pct(sum(bool(r['correct']) for r in rs), len(rs))} |")
    L.append(f"| visual | {len(by.get('visual', []))} answers saved for manual review |")

    L += ["", "## Accuracy by domain", "", "| Domain | Compute | Compliance | Spec |", "|---|---|---|---|"]
    for dom in ("building", "electrical", "electronic", "mechanical"):
        cells = []
        for kind in ("compute", "compliance", "spec"):
            rs = [r for r in rows if r.get("domain") == dom and r["kind"] == kind]
            cells.append(pct(sum(bool(r["correct"]) for r in rs), len(rs)) if rs else "-")
        L.append(f"| {dom} | " + " | ".join(cells) + " |")

    comp = by.get("compute", [])
    if comp:
        L += ["", "## Compute: canonical vs paraphrased wording", "", "| Wording | Accuracy |", "|---|---|"]
        for v in ("canonical", "paraphrase"):
            rs = [r for r in comp if r.get("variant") == v]
            L.append(f"| {v} | {pct(sum(bool(r['correct']) for r in rs), len(rs))} |")
        if any("raw_correct" in r for r in comp):
            rs = [r for r in comp if "raw_correct" in r]
            L += ["", "## Headline: tools vs LLM reading raw DXF", "", "| Method | Numeric accuracy |", "|---|---|",
                  f"| LLM + geometry tools | {pct(sum(bool(r['correct']) for r in rs), len(rs))} |",
                  f"| LLM reading raw entity dump | {pct(sum(bool(r['raw_correct']) for r in rs), len(rs))} |"]
        L += ["", "### Per template", "", "| Domain | Template | Accuracy |", "|---|---|---|"]
        tb = defaultdict(list)
        for r in comp:
            tb[(r.get("domain"), r["template"])].append(r)
        for (d, k), rs in tb.items():
            L.append(f"| {d} | {k} | {pct(sum(bool(r['correct']) for r in rs), len(rs))} |")

    L += ["", "## Routing accuracy", "", "| Router | Accuracy |", "|---|---|",
          f"| keyword rules | {pct(sum(r['route_heuristic_ok'] for r in rows), len(rows))} |"]
    if any(r["route_llm_ok"] is not None for r in rows):
        L.append(f"| LLM | {pct(sum(bool(r['route_llm_ok']) for r in rows), len(rows))} |")

    L += ["", "## Retrieval", "",
          "| Spec | Chunking | Mode | Chunks | recall@1 | recall@3 | context chars@3 |", "|---|---|---|---|---|---|---|"]
    for r in res["retrieval"]:
        L.append(f"| {r['spec']} | {r['strategy']} | {r['mode']} | {r['chunks']} | {r['recall@1']:.0%} | {r['recall@3']:.0%} | {r['context_chars@3']} |")
    L += ["", "recall@3 is inflated for strategies with few, large chunks (top-3 covers much of the document); "
          "compare recall@1 and context size too."]

    lat = [r["latency_s"] for r in rows if r.get("latency_s") is not None]
    if lat:
        L += ["", f"Median latency: {sorted(lat)[len(lat) // 2]:.2f}s per question."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", default="data/eval/questions.jsonl")
    ap.add_argument("--samples", default="data/samples")
    ap.add_argument("--provider", default=None, help="heuristic | openai (default: LLM_PROVIDER)")
    ap.add_argument("--raw-baseline", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--strategy", default="structure")
    ap.add_argument("--out", default="eval_results")
    a = ap.parse_args()
    from cad_copilot import config
    provider = a.provider or config.LLM_PROVIDER
    qs = [json.loads(l) for l in Path(a.questions).read_text().splitlines() if l.strip()]
    res = run(qs, a.samples, provider, a.raw_baseline, a.limit, a.strategy)
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    (out / f"results_{provider}.json").write_text(json.dumps(res, indent=2, default=str))
    md = summarize(res)
    (out / f"results_{provider}.md").write_text(md)
    fails = [r for r in res["rows"] if r["correct"] is False]
    (out / f"failures_{provider}.jsonl").write_text("\n".join(json.dumps(r, default=str) for r in fails) + "\n")
    print("\n" + md)

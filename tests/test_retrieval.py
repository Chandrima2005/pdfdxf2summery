from cad_copilot.eval.metrics import clause_in
from cad_copilot.parsing.pdf_parser import parse_pdf
from cad_copilot.retrieval.chunking import STRATEGIES, chunk_pages
from cad_copilot.retrieval.hybrid import Embedder, HybridRetriever
from cad_copilot.spec_content import SPEC_QA


def test_all_strategies_produce_chunks_with_pages(samples):
    pages = parse_pdf(samples / "building_spec.pdf")
    for s in STRATEGIES:
        chunks = chunk_pages(pages, s)
        assert chunks and all(c.page >= 1 and c.text for c in chunks)


def test_structure_chunks_carry_section(samples):
    chunks = chunk_pages(parse_pdf(samples / "building_spec.pdf"), "structure")
    corridor = [c for c in chunks if "1100 mm" in c.text][0]
    assert corridor.section and "Corridor" in corridor.section


def test_hybrid_recall_at_3(samples):
    r = HybridRetriever(chunk_pages(parse_pdf(samples / "building_spec.pdf"), "structure"), Embedder(force_tfidf=True))
    hits = sum(any(clause_in(h.chunk.text, c) for h in r.search(q, 3)) for q, c in SPEC_QA)
    assert hits / len(SPEC_QA) >= 0.8


def test_off_topic_rejected(samples):
    r = HybridRetriever(chunk_pages(parse_pdf(samples / "building_spec.pdf"), "structure"), Embedder(force_tfidf=True))
    assert not r.is_answerable("What is the required roof pitch?")
    assert r.is_answerable("What is the minimum corridor width?")


def test_retrievers_do_not_share_tfidf_state(samples):
    """Regression: one Embedder passed to two retrievers used to overwrite the first one's vocabulary."""
    shared = Embedder(force_tfidf=True)
    a = HybridRetriever(chunk_pages(parse_pdf(samples / "building_spec.pdf"), "structure"), shared)
    b = HybridRetriever(chunk_pages(parse_pdf(samples / "electrical_spec.pdf"), "structure"), shared)
    assert "1100 mm" in a.search("minimum corridor width", 1)[0].chunk.text
    assert any("30 mA" in h.chunk.text for h in b.search("residual current device socket outlets", 3))
    assert all(h.chunk.source == "electrical_spec.pdf" for h in b.search("corridor width", 3))


def test_electrical_spec_recall(samples):
    from cad_copilot.spec_content import ELECTRICAL_QA
    r = HybridRetriever(chunk_pages(parse_pdf(samples / "electrical_spec.pdf"), "structure"), Embedder(force_tfidf=True))
    hits = sum(any(clause_in(h.chunk.text, c) for h in r.search(q, 3)) for q, c in ELECTRICAL_QA)
    assert hits / len(ELECTRICAL_QA) >= 0.8

"""Hybrid retrieval: BM25 (keywords) + dense embeddings (meaning), fused with RRF.

BM25 is good at exact terms ("1100 mm", "WALLS"); embeddings are good at
paraphrase ("hallway" ~ "corridor"). Reciprocal Rank Fusion combines the two
rankings without needing their scores to be on the same scale.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

from cad_copilot.retrieval.chunking import Chunk

STOP = set("a an the of to in on for and or is are be shall must what which how does do any "
           "with by at from this that it as can should will".split())


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()) if t not in STOP]


class Embedder:
    """sentence-transformers if installed, otherwise a TF-IDF fallback (no GPU/torch needed)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", force_tfidf: bool = False):
        self.kind = "tfidf"
        self.model_name = model_name
        if not force_tfidf:
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(model_name)
                self.kind = "st"
            except Exception:
                pass
        # Similarity below which we treat the query as "not covered by the document".
        self.no_answer_threshold = 0.55 if self.kind == "st" else 0.05

    def fit(self, texts: list[str]) -> np.ndarray:
        if self.kind == "st":
            return self.model.encode(texts, normalize_embeddings=True)
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        m = self.vec.fit_transform(texts)
        return self._norm(m.toarray())

    def query(self, q: str) -> np.ndarray:
        if self.kind == "st":
            prefix = "Represent this sentence for searching relevant passages: " if "bge" in self.model_name else ""
            return self.model.encode([prefix + q], normalize_embeddings=True)[0]
        return self._norm(self.vec.transform([q]).toarray())[0]

    @staticmethod
    def _norm(m: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(m, axis=-1, keepdims=True)
        return m / np.where(n == 0, 1, n)


@dataclass
class Hit:
    chunk: Chunk
    score: float
    bm25_rank: int | None = None
    dense_rank: int | None = None


class HybridRetriever:
    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None, rrf_k: int = 60):
        if not chunks:
            raise ValueError("No chunks to index")
        self.chunks = chunks
        self.rrf_k = rrf_k
        self.bm25 = BM25Okapi([tokenize(c.text) for c in chunks])
        embedder = embedder or Embedder()
        # TF-IDF keeps a per-corpus vocabulary, so each retriever needs its own copy.
        # (A sentence-transformers model has no per-corpus state and is safely shared.)
        self.embedder = copy.copy(embedder) if embedder.kind == "tfidf" else embedder
        self.emb = self.embedder.fit([c.text for c in chunks])

    def _bm25_scores(self, q: str) -> np.ndarray:
        return np.asarray(self.bm25.get_scores(tokenize(q)))

    def _dense_scores(self, q: str) -> np.ndarray:
        return self.emb @ self.embedder.query(q)

    def search(self, query: str, k: int = 5, mode: str = "hybrid") -> list[Hit]:
        b, d = self._bm25_scores(query), self._dense_scores(query)
        b_rank = {int(i): r for r, i in enumerate(np.argsort(-b))}
        d_rank = {int(i): r for r, i in enumerate(np.argsort(-d))}
        if mode == "bm25":
            order = np.argsort(-b)
            scores = b
        elif mode == "dense":
            order = np.argsort(-d)
            scores = d
        else:
            fused = np.array([1 / (self.rrf_k + b_rank[i]) + 1 / (self.rrf_k + d_rank[i]) for i in range(len(self.chunks))])
            order = np.argsort(-fused)
            scores = fused
        return [Hit(self.chunks[i], float(scores[i]), b_rank[int(i)], d_rank[int(i)]) for i in order[:k]]

    def is_answerable(self, query: str) -> bool:
        """Cheap out-of-scope detector: refuse rather than hallucinate."""
        return bool(self._bm25_scores(query).max() > 0 and self._dense_scores(query).max() >= self.embedder.no_answer_threshold)


def build_retriever(pdf_path: str, strategy: str = "structure", embedder: Embedder | None = None,
                    ocr=None) -> HybridRetriever:
    """`ocr` (page PNG -> text) is only used for scanned pages that have no text layer."""
    from cad_copilot.parsing.pdf_parser import parse_pdf
    from cad_copilot.retrieval.chunking import chunk_pages
    return HybridRetriever(chunk_pages(parse_pdf(pdf_path, ocr=ocr), strategy), embedder)

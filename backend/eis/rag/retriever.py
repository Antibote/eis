"""Гибридный поиск по фрагментам документов: BM25 (леммы) + векторный поиск, слияние RRF.

Эмбеддинги — за интерфейсом Embedder: локальная модель sentence-transformers
(multilingual-e5-small) или, если она недоступна, TF-IDF по символьным n-граммам.
Векторный индекс — точный косинусный поиск в NumPy (для 10³–10⁴ фрагментов этого достаточно;
замена на pgvector/Qdrant — через тот же интерфейс).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from rank_bm25 import BM25Okapi

from eis.domain.models import Fragment, KnowledgeBase
from eis.extraction.lexicon import find_params
from eis.extraction.mentions import lemma, tokens

log = logging.getLogger(__name__)
STOP = set("и в во на с со по для из от до не к ко о об а но или что как при же ли бы то это его её их".split())


def lemmatize(text: str) -> list[str]:
    return [lm for t, _, _ in tokens(text) if (lm := lemma(t)) not in STOP]


class Embedder(Protocol):
    name: str
    def encode_passages(self, texts: list[str]) -> np.ndarray: ...
    def encode_query(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "intfloat/multilingual-e5-small"):
        from sentence_transformers import SentenceTransformer
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        self.model = SentenceTransformer(model_name, device="cpu")
        self.name = model_name
        self.e5 = "e5" in model_name

    def encode_passages(self, texts):
        pref = "passage: " if self.e5 else ""
        return self.model.encode([pref + t for t in texts], normalize_embeddings=True, batch_size=32)

    def encode_query(self, text):
        pref = "query: " if self.e5 else ""
        return self.model.encode([pref + text], normalize_embeddings=True)[0]


class TfidfEmbedder:
    name = "tfidf-char-3-5"

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self.fitted = False

    def encode_passages(self, texts):
        m = self.vec.fit_transform(texts)
        self.fitted = True
        return _l2(m.toarray())

    def encode_query(self, text):
        return _l2(self.vec.transform([text]).toarray())[0]


def _l2(m):
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(n == 0, 1, n)


_EMBEDDER_CACHE: dict[str, Embedder] = {}


def default_embedder(prefer: str | None = None) -> Embedder:
    """Локальная модель, если доступна офлайн/онлайн; иначе — TF-IDF (без сети)."""
    name = prefer or os.environ.get("EIS_EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    if name == "tfidf":
        return TfidfEmbedder()
    if name not in _EMBEDDER_CACHE:
        try:
            _EMBEDDER_CACHE[name] = SentenceTransformerEmbedder(name)
        except Exception as e:  # noqa: BLE001
            log.warning("Модель эмбеддингов %s недоступна (%s) — используется TF-IDF", name, e)
            return TfidfEmbedder()
    return _EMBEDDER_CACHE[name]


@dataclass
class Hit:
    fragment: Fragment
    score: float
    bm25_rank: int | None = None
    vector_rank: int | None = None
    flags: list[str] = field(default_factory=list)


class HybridRetriever:
    def __init__(self, kb: KnowledgeBase, embedder: Embedder | None = None):
        self.kb = kb
        self.frags = [f for f in kb.fragments.values() if len(f.text) > 3]
        self.bm25 = BM25Okapi([lemmatize(f.text) or ["∅"] for f in self.frags])
        self.embedder = embedder or default_embedder()
        self.mat = np.asarray(self.embedder.encode_passages([self._passage(f) for f in self.frags]), dtype=np.float32)
        # индексы для фильтров
        self.frag_entities: dict[str, set[str]] = {}
        for r in kb.relations.values():
            for e in r.evidence:
                if e.fragment_id:
                    self.frag_entities.setdefault(e.fragment_id, set()).add(r.source)
        self.frag_params: dict[str, set[str]] = {}
        for req in kb.requirements.values():
            for e in req.evidence:
                self.frag_params.setdefault(e.fragment_id, set()).add(req.parameter)

    @staticmethod
    def _passage(f: Fragment) -> str:
        ctx = (f.heading_path[-1] + ". ") if f.heading_path else ""
        return ctx + f.text

    def _allowed(self, f: Fragment, doc_types, entity_id, parameter) -> bool:
        if doc_types and self.kb.documents[f.document_id].doc_type not in doc_types:
            return False
        if entity_id and entity_id not in self.frag_entities.get(f.id, set()):
            return False
        if parameter and parameter not in self.frag_params.get(f.id, set()):
            text_params = {h.key for h in find_params(f.text.lower())}
            if parameter not in text_params:
                return False
        return True

    def search(self, query: str, k: int = 8, mode: str = "hybrid", doc_types: set[str] | None = None,
               entity_id: str | None = None, parameter: str | None = None, rrf_k: int = 60) -> list[Hit]:
        mask = np.array([self._allowed(f, doc_types, entity_id, parameter) for f in self.frags])
        ranks: dict[int, dict[str, int]] = {}
        if mode in ("bm25", "hybrid"):
            s = np.asarray(self.bm25.get_scores(lemmatize(query) or ["∅"]))
            s[~mask] = -np.inf
            for rank, i in enumerate(np.argsort(-s)[: max(k * 4, 20)]):
                if np.isfinite(s[i]) and s[i] > 0:
                    ranks.setdefault(int(i), {})["bm25"] = rank
        if mode in ("vector", "hybrid"):
            q = np.asarray(self.embedder.encode_query(query), dtype=np.float32)
            s = self.mat @ q
            s[~mask] = -np.inf
            for rank, i in enumerate(np.argsort(-s)[: max(k * 4, 20)]):
                if np.isfinite(s[i]):
                    ranks.setdefault(int(i), {})["vec"] = rank
        scored = []
        for i, r in ranks.items():
            sc = sum(1.0 / (rrf_k + v + 1) for v in r.values())
            scored.append(Hit(self.frags[i], round(sc, 6), r.get("bm25"), r.get("vec"), list(self.frags[i].flags)))
        scored.sort(key=lambda h: -h.score)
        return scored[:k]

"""Рабочее пространство проекта: KnowledgeBase + граф + поиск + результаты анализа (в памяти, с ленивой сборкой)."""
from __future__ import annotations

import threading
from functools import cached_property

from eis.domain.models import KnowledgeBase
from eis.graph.store import NetworkXStore, build_graph
from eis.rag.retriever import HybridRetriever, default_embedder
from eis.services.change_request import build_mention_index
from eis.services.contradictions import detect_contradictions


class Workspace:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb
        self.lock = threading.RLock()

    @cached_property
    def graph(self) -> NetworkXStore:
        return build_graph(self.kb)

    @cached_property
    def retriever(self) -> HybridRetriever:
        return HybridRetriever(self.kb, default_embedder())

    @cached_property
    def contradictions(self):
        return detect_contradictions(self.kb, self.graph)

    @cached_property
    def mentions(self):
        return build_mention_index(self.kb)

    def evidence_context(self, ev) -> dict:
        d = self.kb.documents.get(ev.document_id)
        return {"document_id": ev.document_id, "filename": d.filename if d else None, "code": d.code if d else None,
                "page": ev.page, "locator": ev.locator, "quote": ev.quote, "fragment_id": ev.fragment_id,
                "method": ev.method, "rule": ev.rule, "confidence": ev.confidence}

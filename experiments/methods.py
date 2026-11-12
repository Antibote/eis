"""Сравниваемые методы определения последствий изменения.

Все методы получают одинаковый вход: текст запроса на изменение и один и тот же корпус
(KnowledgeBase, построенная из документов). Выход: множества затронутых компонентов,
документов, испытаний и «достигнутых» узлов (для оценки цепочек), а также нарушения (если метод их выявляет).

M1 keyword  — BM25 по тексту изменения, top-k фрагментов → упомянутые в них сущности.
M2 rag      — гибридный поиск (BM25 + эмбеддинги, RRF), top-k → упомянутые сущности.
M3 graph    — неориентированный обход извлечённого графа на глубину d без весов, правил и классов.
M4 hybrid   — предлагаемый метод (services/impact.py): типизированный обход с учётом физики параметра,
              формальная перепроверка ограничений, отбор документов по содержанию утверждений.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from eis.domain.models import KnowledgeBase, RelationType
from eis.graph.store import NetworkXStore
from eis.rag.retriever import HybridRetriever
from eis.services.change_request import parse_change
from eis.services.impact import ImpactAnalyzer, ImpactSettings

COMP = {"Assembly", "Component"}


@dataclass
class MethodOutput:
    components: set[str] = field(default_factory=set)
    documents: set[str] = field(default_factory=set)
    tests: set[str] = field(default_factory=set)
    reached: set[str] = field(default_factory=set)
    violations: set[str] | None = None
    claims: int = 0                 # число утверждений «X затронут»
    supported_claims: int = 0       # из них — с указанием источника (фрагмент/путь)


def _from_fragments(kb: KnowledgeBase, frag_ids: list[str]) -> MethodOutput:
    out = MethodOutput()
    fset = set(frag_ids)
    for r in kb.relations.values():
        if r.type != RelationType.DOCUMENTED_IN:
            continue
        if any(e.fragment_id in fset for e in r.evidence):
            e = kb.entities.get(r.source)
            if e is None:
                continue
            out.reached.add(r.source)
            if e.type.value in COMP:
                out.components.add(r.source)
            if e.type.value == "Test":
                out.tests.add(r.source)
    out.documents = {kb.fragments[f].document_id for f in frag_ids}
    out.claims = out.supported_claims = len(out.components)   # каждый вывод привязан к найденному фрагменту
    return out


class KeywordMethod:
    name = "M1_keyword"

    def __init__(self, kb, graph, retriever: HybridRetriever, k: int = 10):
        self.kb, self.r, self.k = kb, retriever, k

    def run(self, change_text: str) -> MethodOutput:
        hits = self.r.search(change_text, k=self.k, mode="bm25")
        return _from_fragments(self.kb, [h.fragment.id for h in hits])


class RagMethod(KeywordMethod):
    name = "M2_rag"

    def run(self, change_text: str) -> MethodOutput:
        hits = self.r.search(change_text, k=self.k, mode="hybrid")
        return _from_fragments(self.kb, [h.fragment.id for h in hits])


class GraphMethod:
    name = "M3_graph"

    def __init__(self, kb: KnowledgeBase, graph: NetworkXStore, depth: int = 3):
        self.kb, self.g, self.depth = kb, graph, depth

    def run(self, change_text: str) -> MethodOutput:
        pc = parse_change(change_text, self.kb, self.g)
        start = pc.requirement.id
        seen, frontier = {start}, [start]
        skip = {RelationType.DOCUMENTED_IN}
        for _ in range(self.depth):
            nxt = []
            for n in frontier:
                for e in self.g.out_edges(n) + self.g.in_edges(n):
                    if e.type in skip:
                        continue
                    m = e.target if e.source == n else e.source
                    if m not in seen:
                        seen.add(m)
                        nxt.append(m)
            frontier = nxt
        out = MethodOutput(reached=seen)
        for n in seen:
            e = self.kb.entities.get(n)
            if e is None:
                continue
            if e.type.value in COMP:
                out.components.add(n)
            if e.type.value == "Test":
                out.tests.add(n)
            for d in self.g.documents_of(n):
                out.documents.add(d.target)
        out.claims = out.supported_claims = len(out.components)
        return out


class HybridMethod:
    name = "M4_hybrid"

    def __init__(self, kb, graph, settings: ImpactSettings | None = None, include_classes=None, name=None):
        self.kb, self.g = kb, graph
        self.a = ImpactAnalyzer(kb, graph, settings)
        self.include = include_classes or {"confirmed", "direct", "potential"}
        if name:
            self.name = name

    def run(self, change_text: str) -> MethodOutput:
        pc = parse_change(change_text, self.kb, self.g)
        rep = self.a.analyze(pc.requirement.id, new_value=pc.new_value, new_low=pc.new_low, new_high=pc.new_high)
        out = MethodOutput(violations=set())
        for it in rep.items:
            if it.impact_class not in self.include:
                continue
            out.reached.add(it.entity_id)
            out.reached |= {s.node for s in it.path}
            if it.entity_type in COMP:
                out.components.add(it.entity_id)
                out.claims += 1
                out.supported_claims += bool(it.evidence or it.path)
                if it.impact_class == "confirmed":
                    out.violations.add(it.entity_id)
        out.reached.add(pc.requirement.id)
        out.documents = {d.document_id for d in rep.documents}
        out.tests = {t.test_id for t in rep.tests if t.repeat_required}
        out.report = rep  # type: ignore[attr-defined]
        return out

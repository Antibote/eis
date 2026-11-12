"""Хранилище графа знаний.

`GraphStore` — протокол, от которого зависят сервисы анализа. MVP-реализация — NetworkX
(MultiDiGraph в памяти, строится из KnowledgeBase). Адаптер Neo4j реализует тот же протокол.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

import networkx as nx

from eis.domain.models import KnowledgeBase, Relation, RelationType


class GraphStore(Protocol):
    def node(self, node_id: str) -> dict | None: ...
    def out_edges(self, node_id: str, types: Iterable[RelationType] | None = None) -> list[Relation]: ...
    def in_edges(self, node_id: str, types: Iterable[RelationType] | None = None) -> list[Relation]: ...
    def nodes(self, node_type: str | None = None) -> list[dict]: ...
    def stats(self) -> dict: ...


class NetworkXStore:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb
        self.g = nx.MultiDiGraph()
        for e in kb.entities.values():
            self.g.add_node(e.id, id=e.id, type=e.type.value, name=e.name, designation=e.designation)
        for r in kb.relations.values():
            for end in (r.source, r.target):
                if end not in self.g:
                    self.g.add_node(end, id=end, type="Unknown", name=end, designation=None)
            self.g.add_edge(r.source, r.target, key=r.id, rel=r)

    def node(self, node_id: str) -> dict | None:
        return self.g.nodes[node_id] if node_id in self.g else None

    def _filter(self, edges, types):
        ts = set(types) if types is not None else None
        return [d["rel"] for *_, d in edges if ts is None or d["rel"].type in ts]

    def out_edges(self, node_id, types=None):
        return self._filter(self.g.out_edges(node_id, data=True), types) if node_id in self.g else []

    def in_edges(self, node_id, types=None):
        return self._filter(self.g.in_edges(node_id, data=True), types) if node_id in self.g else []

    def nodes(self, node_type=None):
        return [d for _, d in self.g.nodes(data=True) if node_type is None or d["type"] == node_type]

    def children(self, node_id: str) -> list[str]:
        return [r.target for r in self.out_edges(node_id, [RelationType.CONTAINS])]

    def descendants(self, node_id: str) -> set[str]:
        out, stack = set(), [node_id]
        while stack:
            for c in self.children(stack.pop()):
                if c not in out:
                    out.add(c)
                    stack.append(c)
        return out

    def ancestors(self, node_id: str) -> list[str]:
        out, cur = [], node_id
        while True:
            parents = [r.source for r in self.in_edges(cur, [RelationType.CONTAINS])]
            if not parents or parents[0] in out:
                return out
            cur = parents[0]
            out.append(cur)

    def materials(self, node_id: str) -> list[Relation]:
        return self.out_edges(node_id, [RelationType.USES_MATERIAL])

    def documents_of(self, node_id: str) -> list[Relation]:
        return self.out_edges(node_id, [RelationType.DOCUMENTED_IN])

    def stats(self) -> dict:
        from collections import Counter
        return {"nodes": self.g.number_of_nodes(), "edges": self.g.number_of_edges(),
                "nodes_by_type": dict(Counter(d["type"] for _, d in self.g.nodes(data=True))),
                "edges_by_type": dict(Counter(d["rel"].type.value for *_, d in self.g.edges(data=True)))}

    def subgraph_json(self, node_ids: Iterable[str] | None = None) -> dict:
        """Для визуализации: узлы и рёбра (без evidence — его отдают по запросу)."""
        ids = set(node_ids) if node_ids is not None else set(self.g.nodes)
        return {
            "nodes": [dict(self.g.nodes[n]) for n in ids if n in self.g],
            "edges": [{"id": d["rel"].id, "source": u, "target": v, "type": d["rel"].type.value, "weight": d["rel"].weight}
                      for u, v, d in self.g.edges(data=True) if u in ids and v in ids],
        }


def build_graph(kb: KnowledgeBase) -> NetworkXStore:
    return NetworkXStore(kb)

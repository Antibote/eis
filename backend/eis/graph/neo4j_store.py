"""Адаптер графа знаний для Neo4j (тот же протокол GraphStore, что у NetworkXStore).

Узлы — метка :Entity {id, type, name, designation}; связи — типизированные отношения Neo4j
(:DEPENDS_ON, :CONTAINS, …) со свойствами {id, weight}. Доказательства связей (цитаты, страницы) остаются
в базе знаний: Neo4j выполняет обход, а объекты Relation с основаниями возвращаются из KnowledgeBase по id.
Включение: EIS_GRAPH_BACKEND=neo4j, EIS_NEO4J_URL, EIS_NEO4J_USER, EIS_NEO4J_PASSWORD.
"""
from __future__ import annotations

from collections.abc import Iterable

from eis.domain.models import KnowledgeBase, Relation, RelationType

REL_TYPES = {t.value for t in RelationType}


def _rel_type(t: str) -> str:
    """Тип отношения подставляется в текст Cypher — только из фиксированного перечня (защита от инъекций)."""
    if t not in REL_TYPES:
        raise ValueError(f"Неизвестный тип связи: {t}")
    return t


class Neo4jStore:
    def __init__(self, kb: KnowledgeBase, driver, database: str | None = None, sync: bool = True):
        self.kb, self.driver, self.database = kb, driver, database
        if sync:
            self.sync()

    # ------------------------------------------------------------ загрузка
    def _run(self, query: str, **params):
        with self.driver.session(database=self.database) as s:
            return list(s.run(query, **params))

    def sync(self, batch: int = 1000):
        """Полная загрузка базы знаний проекта в Neo4j (идемпотентно: MERGE по id)."""
        pid = self.kb.project_id
        self._run("CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE (n.project, n.id) IS UNIQUE")
        self._run("MATCH (n:Entity {project: $p}) DETACH DELETE n", p=pid)
        nodes = [{"id": e.id, "type": e.type.value, "name": e.name, "designation": e.designation}
                 for e in self.kb.entities.values()]
        ends = {x for r in self.kb.relations.values() for x in (r.source, r.target)} - {n["id"] for n in nodes}
        nodes += [{"id": x, "type": "Unknown", "name": x, "designation": None} for x in sorted(ends)]
        for i in range(0, len(nodes), batch):
            self._run("UNWIND $rows AS r MERGE (n:Entity {project: $p, id: r.id}) "
                      "SET n.type = r.type, n.name = r.name, n.designation = r.designation", rows=nodes[i:i + batch], p=pid)
        by_type: dict[str, list[dict]] = {}
        for r in self.kb.relations.values():
            by_type.setdefault(r.type.value, []).append({"id": r.id, "s": r.source, "t": r.target, "w": r.weight})
        for t, rows in by_type.items():
            for i in range(0, len(rows), batch):
                self._run(f"UNWIND $rows AS r MATCH (a:Entity {{project: $p, id: r.s}}), (b:Entity {{project: $p, id: r.t}}) "
                          f"CREATE (a)-[:{_rel_type(t)} {{id: r.id, weight: r.w}}]->(b)", rows=rows[i:i + batch], p=pid)

    # ------------------------------------------------------------ протокол GraphStore
    def _rels(self, ids) -> list[Relation]:
        return [self.kb.relations[i] for i in ids if i in self.kb.relations]

    def node(self, node_id: str) -> dict | None:
        rec = self._run("MATCH (n:Entity {project: $p, id: $id}) RETURN n", p=self.kb.project_id, id=node_id)
        return dict(rec[0]["n"]) if rec else None

    def _edges(self, node_id, types, outgoing: bool) -> list[Relation]:
        ts = [_rel_type(t.value if isinstance(t, RelationType) else t) for t in types] if types is not None else None
        pattern = "(a:Entity {project: $p, id: $id})-[r]->()" if outgoing else "()-[r]->(a:Entity {project: $p, id: $id})"
        where = " WHERE type(r) IN $ts" if ts is not None else ""
        recs = self._run(f"MATCH {pattern}{where} RETURN r.id AS id", p=self.kb.project_id, id=node_id, ts=ts)
        return self._rels(r["id"] for r in recs)

    def out_edges(self, node_id: str, types: Iterable[RelationType] | None = None) -> list[Relation]:
        return self._edges(node_id, types, True)

    def in_edges(self, node_id: str, types: Iterable[RelationType] | None = None) -> list[Relation]:
        return self._edges(node_id, types, False)

    def nodes(self, node_type: str | None = None) -> list[dict]:
        recs = self._run("MATCH (n:Entity {project: $p}) WHERE $t IS NULL OR n.type = $t RETURN n",
                         p=self.kb.project_id, t=node_type)
        return [dict(r["n"]) for r in recs]

    def children(self, node_id: str) -> list[str]:
        return [r.target for r in self.out_edges(node_id, [RelationType.CONTAINS])]

    def descendants(self, node_id: str) -> set[str]:
        recs = self._run("MATCH (:Entity {project: $p, id: $id})-[:CONTAINS*1..]->(d:Entity) RETURN DISTINCT d.id AS id",
                         p=self.kb.project_id, id=node_id)
        return {r["id"] for r in recs}

    def ancestors(self, node_id: str) -> list[str]:
        recs = self._run("MATCH path = (a:Entity)-[:CONTAINS*1..]->(:Entity {project: $p, id: $id}) "
                         "WHERE a.project = $p RETURN a.id AS id, length(path) AS d ORDER BY d",
                         p=self.kb.project_id, id=node_id)
        out = []
        for r in recs:
            if r["id"] not in out:
                out.append(r["id"])
        return out

    def materials(self, node_id: str) -> list[Relation]:
        return self.out_edges(node_id, [RelationType.USES_MATERIAL])

    def documents_of(self, node_id: str) -> list[Relation]:
        return self.out_edges(node_id, [RelationType.DOCUMENTED_IN])

    def stats(self) -> dict:
        p = self.kb.project_id
        n = self._run("MATCH (n:Entity {project: $p}) RETURN n.type AS t, count(*) AS c", p=p)
        e = self._run("MATCH (:Entity {project: $p})-[r]->() RETURN type(r) AS t, count(*) AS c", p=p)
        return {"nodes": sum(r["c"] for r in n), "edges": sum(r["c"] for r in e),
                "nodes_by_type": {r["t"]: r["c"] for r in n}, "edges_by_type": {r["t"]: r["c"] for r in e}}

    def subgraph_json(self, node_ids: Iterable[str] | None = None) -> dict:
        ids = list(node_ids) if node_ids is not None else None
        nodes = self._run("MATCH (n:Entity {project: $p}) WHERE $ids IS NULL OR n.id IN $ids RETURN n",
                          p=self.kb.project_id, ids=ids)
        edges = self._run("MATCH (a:Entity {project: $p})-[r]->(b:Entity) WHERE $ids IS NULL OR (a.id IN $ids AND b.id IN $ids) "
                          "RETURN r.id AS id, a.id AS s, b.id AS t, type(r) AS type, r.weight AS w",
                          p=self.kb.project_id, ids=ids)
        return {"nodes": [dict(r["n"]) for r in nodes],
                "edges": [{"id": r["id"], "source": r["s"], "target": r["t"], "type": r["type"], "weight": r["w"]} for r in edges]}


def neo4j_store_from_env(kb: KnowledgeBase):
    import os

    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(os.environ.get("EIS_NEO4J_URL", "bolt://localhost:7687"),
                                  auth=(os.environ.get("EIS_NEO4J_USER", "neo4j"), os.environ.get("EIS_NEO4J_PASSWORD", "")))
    return Neo4jStore(kb, driver)

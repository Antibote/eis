"""Адаптер Neo4j: генерация запросов и разбор ответов (без сервера) и сверка с NetworkX (при EIS_NEO4J_URL)."""
import os

import pytest

from eis.domain.models import RelationType
from eis.graph.neo4j_store import Neo4jStore, _rel_type


class FakeSession:
    def __init__(self, log, answers):
        self.log, self.answers = log, answers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, q, **p):
        self.log.append((q, p))
        for key, recs in self.answers.items():
            if key in q:
                return recs
        return []


class FakeDriver:
    def __init__(self, answers=None):
        self.log, self.answers = [], answers or {}

    def session(self, database=None):
        return FakeSession(self.log, self.answers)


def test_sync_creates_typed_relations_in_batches(dev_kb):
    d = FakeDriver()
    Neo4jStore(dev_kb, d)
    creates = [(q, p) for q, p in d.log if "CREATE (a)-[:" in q]
    types = {q.split("[:")[1].split(" ")[0] for q, _ in creates}
    assert types == {r.type.value for r in dev_kb.relations.values()}
    assert sum(len(p["rows"]) for _, p in creates) == len(dev_kb.relations)


def test_edges_are_mapped_back_to_relations_with_evidence(dev_kb):
    rel = next(r for r in dev_kb.relations.values() if r.type == RelationType.DEPENDS_ON)
    d = FakeDriver({"RETURN r.id AS id": [{"id": rel.id}]})
    st = Neo4jStore(dev_kb, d, sync=False)
    got = st.in_edges(rel.target, [RelationType.DEPENDS_ON])
    assert got == [rel] and got[0].evidence
    q, p = d.log[-1]
    assert "type(r) IN $ts" in q and p["ts"] == ["DEPENDS_ON"]


def test_relation_type_whitelist():
    with pytest.raises(ValueError):
        _rel_type("X]->() DETACH DELETE n //")


@pytest.mark.skipif(not os.environ.get("EIS_NEO4J_URL"), reason="нужен сервер Neo4j (EIS_NEO4J_URL)")
def test_same_answers_as_networkx(dev_kb, dev_graph):
    from eis.graph.neo4j_store import neo4j_store_from_env
    from eis.services.impact import ImpactAnalyzer
    neo = neo4j_store_from_env(dev_kb)
    for n in list(dev_kb.entities)[:60]:
        assert {r.id for r in neo.out_edges(n)} == {r.id for r in dev_graph.out_edges(n)}
        assert neo.descendants(n) == dev_graph.descendants(n)
    r = next(x for x in dev_kb.requirements.values() if x.parameter == "power")
    a, b = ImpactAnalyzer(dev_kb, dev_graph).analyze(r.id, new_value=75), ImpactAnalyzer(dev_kb, neo).analyze(r.id, new_value=75)
    assert {i.entity_id for i in a.items} == {i.entity_id for i in b.items}

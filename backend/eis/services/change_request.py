"""Разбор запроса на изменение, сформулированного на естественном языке.

«Номинальная мощность электродвигателя увеличивается с 55 кВт до 75 кВт» →
(требование ТЗ «мощность / электродвигатель», новое значение 75 кВт).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from eis.domain.models import KnowledgeBase, Requirement
from eis.extraction.lexicon import find_params
from eis.extraction.mentions import MentionIndex
from eis.extraction.units import NUM, match_unit, parse_number, to_canonical
from eis.graph.store import NetworkXStore

CHANGE_RE = re.compile(r"(?:с|от)\s+(?P<old>" + NUM + r")\s*(?P<ou>[^\d\s]{0,8})?\s+(?:до|на)\s+(?P<new>" + NUM + r")")


@dataclass
class ParsedChange:
    requirement: Requirement
    new_value: float | None
    new_low: float | None
    new_high: float | None
    unit: str
    old_stated: float | None
    explanation: str


def build_mention_index(kb: KnowledgeBase) -> MentionIndex:
    idx = MentionIndex()
    for e in kb.entities.values():
        if e.type.value in ("Product", "Assembly", "Component"):
            idx.add_with_head_alias(e.id, e.name)
    for e in kb.entities.values():
        if e.type.value == "Product":
            idx.add(e.id, "агрегат", alias=True)
    return idx


def parse_change(text: str, kb: KnowledgeBase, graph: NetworkXStore, index: MentionIndex | None = None) -> ParsedChange:
    lc = text.lower().replace("ё", "е")
    params = find_params(lc)
    if not params:
        raise ValueError("Не распознан изменяемый параметр")
    p = params[0]
    m = CHANGE_RE.search(text[p.end:]) or CHANGE_RE.search(text)
    if not m:
        raise ValueError("Не распознаны старое и новое значения («с … до …»)")
    u = match_unit(text, (p.end if CHANGE_RE.search(text[p.end:]) else 0) + m.end("new"))
    if u is None:
        raise ValueError("Не распознана единица измерения нового значения")
    new = to_canonical(parse_number(m.group("new")), u)
    old = to_canonical(parse_number(m.group("old")), u)
    index = index or build_mention_index(kb)
    comps = [x.entity_id for x in index.find(text)]
    product = next((e.id for e in kb.entities.values() if e.type.value == "Product"), None)
    candidates = []
    for c in comps + [product]:
        if c is None:
            continue
        for s in [c] + graph.ancestors(c):
            reqs = [r for r in kb.requirements.values() if r.subject_id == s and r.parameter == p.key
                    and r.kind in ("demand", "nominal")]
            if reqs:
                candidates = reqs
                break
        if candidates:
            break
    if not candidates:
        raise ValueError(f"Не найдено требование к параметру {p.key}")
    # приоритет: техническое задание, затем требование со значением, совпадающим со «старым»
    def score(r):
        dt = kb.documents[r.document_id].doc_type
        matches_old = any(v is not None and abs(v - old) < 1e-6 for v in (
            r.value if not isinstance(r.value, str) else None, r.low, r.high))
        return (dt != "TechnicalSpecification", not matches_old)
    r = sorted(candidates, key=score)[0]
    lo = hi = val = None
    if r.operator == "range":
        if "нижн" in lc or (r.low is not None and abs(r.low - old) < 1e-6):
            lo = new
        else:
            hi = new
    else:
        val = new
    return ParsedChange(r, val, lo, hi, r.unit, old,
                        f"параметр «{p.key}», требование {kb.documents[r.document_id].code} п. {r.section or '—'}")

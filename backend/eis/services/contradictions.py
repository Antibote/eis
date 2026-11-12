"""Гибридный детектор противоречий.

Уровень 1 (formal): сравнение требований к одной характеристике (субъект, параметр) после
приведения единиц; проверка «режим ⊆ возможность»; уставки внутри допустимых границ.
Уровень 3 (graph): проверка через связи графа — зависимые компоненты, их материалы, состав.
Уровень 2 (llm): семантические противоречия — services/semantic.py, статус не выше «potential».

Статусы: confirmed — формальное нарушение, обе стороны извлечены с уверенностью ≥ порога;
potential — нарушение при недостаточной уверенности извлечения;
insufficient_data — сравнение невозможно (несопоставимые единицы/форматы).
"""
from __future__ import annotations

import math
from itertools import combinations

from eis.domain.engineering import MATERIAL_LIMITED, PARAM_RU, TEMPERATURE_PARAMS  # noqa: F401 (PARAM_RU реэкспорт)
from eis.domain.models import EntityType, KnowledgeBase, RelationType, Requirement, stable_id
from eis.domain.results import Contradiction
from eis.extraction.units import match_unit
from eis.graph.store import NetworkXStore

CONFIRM_THRESHOLD = 0.75
REL_TOL = 1e-3
INF = math.inf



def fmt_req(r: Requirement) -> str:
    u = f" {r.unit}" if r.unit else ""
    if r.operator == "range":
        return f"{r.low:g}…{r.high:g}{u}"
    v = r.value if isinstance(r.value, str) else f"{r.value:g}"
    return f"{'' if r.operator == '=' else r.operator + ' '}{v}{u}"


def ip_rank(code: str) -> tuple[int, int]:
    d = code.upper().replace("IP", "")
    return (int(d[0]) if d[0].isdigit() else 0, int(d[1]) if d[1].isdigit() else 0)


def same_bounds(a: Requirement, b: Requirement) -> bool:
    if isinstance(a.value, str) or isinstance(b.value, str):
        return a.value == b.value and a.operator == b.operator
    ia, ib = a.interval(), b.interval()
    return all(math.isclose(x, y, rel_tol=REL_TOL, abs_tol=1e-9) or (math.isinf(x) and math.isinf(y))
               for x, y in zip(ia, ib))


def covers(demand: tuple[float, float], cap: tuple[float, float], ops: str) -> tuple[bool, float | None]:
    """Проверка «режим ⊆ возможность» по тем границам, которые задаёт требование-режим.
    → (выполнено, относительный запас по наихудшей границе)."""
    lo_d, hi_d = demand
    lo_c, hi_c = cap
    margins = []
    ok = True
    if ops in ("<=", "=", "range") and not math.isinf(hi_d) and not math.isinf(hi_c):
        ok &= hi_d <= hi_c + 1e-9
        margins.append((hi_c - hi_d) / max(abs(hi_c), 1e-9))
    if ops in (">=", "=", "range") and not math.isinf(lo_d) and not math.isinf(lo_c):
        ok &= lo_d >= lo_c - 1e-9
        margins.append((lo_d - lo_c) / max(abs(lo_c), 1e-9))
    return ok, (min(margins) if margins else None)


class ContradictionDetector:
    def __init__(self, kb: KnowledgeBase, graph: NetworkXStore, confirm_threshold: float = CONFIRM_THRESHOLD):
        self.kb, self.g, self.thr = kb, graph, confirm_threshold
        self.by_con: dict[tuple[str, str], list[Requirement]] = {}
        for r in kb.requirements.values():
            if r.status == "active":
                self.by_con.setdefault((r.subject_id, r.parameter), []).append(r)
        self.out: dict[str, Contradiction] = {}

    # ------------------------------------------------------------ helpers
    def _name(self, eid):
        e = self.kb.entities.get(eid)
        return e.name if e else eid

    def _doc(self, r: Requirement) -> str:
        d = self.kb.documents.get(r.document_id)
        return (d.code or d.filename) if d else r.document_id

    def _status(self, *reqs: Requirement) -> str:
        return "confirmed" if min(r.confidence for r in reqs) >= self.thr else "potential"

    def _add(self, c: Contradiction):
        key = stable_id(c.type, *sorted(c.items))
        c.id = "ctr:" + key
        if key not in self.out:
            self.out[key] = c

    @staticmethod
    def _severity(rel_diff: float, critical_param: bool) -> str:
        if critical_param and rel_diff > 0.2:
            return "critical"
        return "high" if rel_diff > 0.1 else "medium" if rel_diff > 0.02 else "low"

    # ------------------------------------------------------------ L1: одинаковая характеристика
    def value_mismatches(self):
        for (subj, param), reqs in self.by_con.items():
            stated = [r for r in reqs if r.kind in ("demand", "nominal")]
            for a, b in combinations(stated, 2):
                if same_bounds(a, b):
                    continue
                if isinstance(a.value, str) != isinstance(b.value, str):
                    self._add(Contradiction(id="", type="value_mismatch", status="insufficient_data", severity="low",
                                            title=f"Несопоставимые значения: {PARAM_RU.get(param, param)}",
                                            description=f"{fmt_req(a)} и {fmt_req(b)}", explanation="Разные формы записи значения.",
                                            recommendation="Уточнить требование вручную.", entities=[subj], items=[a.id, b.id],
                                            evidence=a.evidence[:1] + b.evidence[:1], confidence=0.3))
                    continue
                if isinstance(a.value, str):    # IP-коды
                    diff, critical = 0.15, False
                else:
                    ia, ib = a.interval(), b.interval()
                    fin = [(x, y) for x, y in zip(ia, ib) if not (math.isinf(x) or math.isinf(y))]
                    diff = max((abs(x - y) / max(abs(x), abs(y), 1e-9) for x, y in fin), default=1.0)
                    critical = param in ("power", "working_pressure", "test_pressure")
                ua, ub = match_unit(a.unit_original or ""), match_unit(b.unit_original or "")
                hidden = bool(ua and ub and (ua.factor, ua.offset) != (ub.factor, ub.offset))
                ctype = "unit_hidden_mismatch" if hidden else "value_mismatch"
                expl = (f"Для характеристики «{PARAM_RU.get(param, param)}» объекта «{self._name(subj)}» документы задают "
                        f"разные значения: {self._doc(a)} — {fmt_req(a)} ({a.value_original}), "
                        f"{self._doc(b)} — {fmt_req(b)} ({b.value_original}).")
                if hidden:
                    expl += " Расхождение скрыто различием единиц измерения и выявлено после их приведения."
                self._add(Contradiction(
                    id="", type=ctype, status=self._status(a, b), severity=self._severity(diff, critical),
                    title=f"Расхождение: {PARAM_RU.get(param, param)} ({self._name(subj)})",
                    description=f"{self._doc(a)}: {fmt_req(a)} ≠ {self._doc(b)}: {fmt_req(b)}",
                    explanation=expl,
                    recommendation="Определить действующее значение (как правило — по ТЗ) и выпустить извещение об "
                                   "изменении для документа с отличающимся значением.",
                    entities=[subj], items=[a.id, b.id], evidence=a.evidence[:1] + b.evidence[:1],
                    confidence=round(min(a.confidence, b.confidence) * 0.95, 3)))

    # ------------------------------------------------------------ L1/L3: режим vs возможность
    def _dependents(self, subj: str, param: str) -> set[str]:
        """Компоненты, работа которых зависит от характеристики (subj, param), + сам субъект."""
        con = f"con:{subj}:{param}"
        deps = {r.source for r in self.g.in_edges(con, [RelationType.DEPENDS_ON])}
        return deps | {subj}

    def capability_violations(self):
        for (subj, param), reqs in self.by_con.items():
            demands = [r for r in reqs if r.kind in ("demand", "nominal") and not isinstance(r.value, str)]
            if not demands:
                continue
            for comp in self._dependents(subj, param):
                caps = [c for c in self.by_con.get((comp, param), []) if c.kind == "capability"]
                for d in demands:
                    for c in caps:
                        ok, margin = covers(d.interval(), c.interval(), d.operator)
                        if ok:
                            continue
                        via_graph = comp != subj
                        self._add(Contradiction(
                            id="", type="demand_exceeds_capability", status=self._status(d, c),
                            severity="critical" if param in ("working_pressure", "power") else "high",
                            title=f"{PARAM_RU.get(param, param).capitalize()}: требование выходит за возможности "
                                  f"«{self._name(comp)}»",
                            description=f"{self._doc(d)}: {fmt_req(d)}; {self._doc(c)}: {self._name(comp)} — {fmt_req(c)}",
                            explanation=(f"Требование {self._doc(d)} к «{self._name(subj)}» ({fmt_req(d)}) не обеспечивается "
                                         f"ограничением компонента «{self._name(comp)}» ({fmt_req(c)}, {self._doc(c)})."
                                         + (" Связь установлена по графу: компонент зависит от этой характеристики "
                                            "(DEPENDS_ON)." if via_graph else "")),
                            recommendation=f"Проверить применимость «{self._name(comp)}»: заменить компонент или "
                                           f"скорректировать требование; согласовать с держателем {self._doc(d)}.",
                            entities=[comp], items=[d.id, c.id], evidence=d.evidence[:1] + c.evidence[:1],
                            confidence=round(min(d.confidence, c.confidence) * (0.9 if via_graph else 0.95), 3),
                            detected_by="graph" if via_graph else "formal"))

    def material_limits(self):
        """L3: зависимый компонент → его материалы (и материалы вложенных деталей) → температура применения."""
        for (subj, param), reqs in self.by_con.items():
            if param not in MATERIAL_LIMITED:
                continue
            demands = [r for r in reqs if r.kind in ("demand", "nominal")]
            for comp in self._dependents(subj, param) - {subj}:
                for part in {comp} | self.g.descendants(comp):
                    for mrel in self.g.materials(part):
                        for c in self.by_con.get((mrel.target, "material_temperature"), []):
                            for d in demands:
                                ok, _ = covers(d.interval(), c.interval(), d.operator)
                                if ok:
                                    continue
                                self._add(Contradiction(
                                    id="", type="material_limit", status=self._status(d, c), severity="high",
                                    title=f"Материал «{self._name(mrel.target)}» не обеспечивает режим "
                                          f"«{PARAM_RU.get(param, param)}»",
                                    description=f"{self._doc(d)}: {fmt_req(d)}; {self._name(mrel.target)}: "
                                                f"{fmt_req(c)} ({self._doc(c)})",
                                    explanation=(f"«{self._name(comp)}» зависит от характеристики «{PARAM_RU.get(param)}», "
                                                 f"деталь «{self._name(part)}» изготовлена из «{self._name(mrel.target)}» "
                                                 f"с температурой применения {fmt_req(c)}, что не покрывает {fmt_req(d)}."),
                                    recommendation=f"Подобрать материал для «{self._name(part)}» с подходящим диапазоном "
                                                   f"температур или ограничить режим эксплуатации.",
                                    entities=[part, mrel.target], items=[d.id, c.id, mrel.id],
                                    evidence=d.evidence[:1] + c.evidence[:1] + mrel.evidence[:1],
                                    confidence=round(min(d.confidence, c.confidence) * 0.85, 3), detected_by="graph"))

    def setpoints(self):
        for (subj, param), reqs in self.by_con.items():
            for sp in (r for r in reqs if r.kind == "setpoint" and not isinstance(r.value, str)):
                for lim in (r for r in reqs if r.kind in ("demand", "capability") and r.operator in ("<=", "range")):
                    hi = lim.interval()[1]
                    if sp.value > hi + 1e-9:
                        self._add(Contradiction(
                            id="", type="setpoint_exceeds_limit", status=self._status(sp, lim), severity="high",
                            title=f"Уставка выше допустимого значения: {PARAM_RU.get(param, param)}",
                            description=f"{self._doc(sp)}: уставка {fmt_req(sp)}; {self._doc(lim)}: {fmt_req(lim)}",
                            explanation=f"Уставка {sp.value:g} {sp.unit} для «{self._name(subj)}» превышает предельное "
                                        f"значение {hi:g} {lim.unit} — защита сработает после выхода за допустимый режим.",
                            recommendation="Снизить уставку до значения не выше предельного или обосновать предел.",
                            entities=[subj], items=[sp.id, lim.id], evidence=sp.evidence[:1] + lim.evidence[:1],
                            confidence=round(min(sp.confidence, lim.confidence) * 0.95, 3)))

    def material_mismatches(self):
        """L3: компонент связан с несколькими материалами одного класса из разных документов."""
        for e in self.kb.entities.values():
            if e.type not in (EntityType.COMPONENT, EntityType.ASSEMBLY):
                continue
            rels = self.g.materials(e.id)
            by_class: dict[str, list] = {}
            for r in rels:
                cls = self._name(r.target).split()[0].lower()
                by_class.setdefault(cls, []).append(r)
            for cls, rs in by_class.items():
                for a, b in combinations(rs, 2):
                    da = {x.document_id for x in a.evidence}
                    db = {x.document_id for x in b.evidence}
                    if da == db:
                        continue
                    self._add(Contradiction(
                        id="", type="material_mismatch", status="confirmed", severity="medium",
                        title=f"Разные материалы для «{e.name}»",
                        description=f"{self._name(a.target)} vs {self._name(b.target)}",
                        explanation=(f"Для «{e.name}» документы указывают разные материалы одного класса: "
                                     f"«{self._name(a.target)}» ({', '.join(self._docname(x) for x in sorted(da))}) и "
                                     f"«{self._name(b.target)}» ({', '.join(self._docname(x) for x in sorted(db))})."),
                        recommendation="Установить действующий материал и привести спецификацию, ведомость материалов "
                                       "и ТУ в соответствие.",
                        entities=[e.id, a.target, b.target], items=[a.id, b.id], evidence=a.evidence[:1] + b.evidence[:1],
                        confidence=0.85, detected_by="graph"))

    def _docname(self, doc_id):
        d = self.kb.documents.get(doc_id)
        return (d.code or d.filename) if d else doc_id

    def run(self) -> list[Contradiction]:
        self.value_mismatches()
        self.capability_violations()
        self.material_limits()
        self.setpoints()
        self.material_mismatches()
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(self.out.values(), key=lambda c: (order[c.severity], -c.confidence))


def detect_contradictions(kb: KnowledgeBase, graph: NetworkXStore, **kw) -> list[Contradiction]:
    return ContradictionDetector(kb, graph, **kw).run()


_ = TEMPERATURE_PARAMS, INF

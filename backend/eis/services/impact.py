"""Анализ последствий изменения технического требования (метод M4 «гибрид»).

Классы влияния:
  confirmed   — подтверждённое техническое влияние: формальная проверка показала нарушение
                ограничения компонента/материала новым значением (с цитатами обеих сторон);
  direct      — прямая зависимость: компонент явно зависит от изменяемой характеристики
                (DEPENDS_ON / субъект требования / производная величина);
  potential   — потенциальное влияние: достигнут транзитивно (состав, путь нагрузки) либо
                проверка невозможна/на пределе;
  documentary — документальная связь: только упоминание в документах.
Транзитивная связь сама по себе не считается доказательством физического влияния.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass

from eis.domain.engineering import (AFFINITY, DEFAULT_PROPAGATION, DERIVED_RULES, MARGIN_WARN, MATERIAL_LIMITED, PARAM_CLASS,
                                    PROPAGATION, change_is_harsher, related)
from eis.domain.models import EntityType, KnowledgeBase, RelationType, Requirement
from eis.domain.results import (CheckResult, Contradiction, DerivedImpact, DocumentImpact, ImpactItem, ImpactReport,
                                PathStep, TestImpact)
from eis.extraction.lexicon import find_params
from eis.extraction.units import NUM_RE, match_unit, parse_number, to_canonical
from eis.graph.store import NetworkXStore
from eis.services.contradictions import PARAM_RU, covers, fmt_req, same_bounds

COMPONENT_TYPES = {EntityType.PRODUCT.value, EntityType.ASSEMBLY.value, EntityType.COMPONENT.value}


@dataclass
class ImpactSettings:
    max_depth: int = 3
    decay: float = 0.85
    use_physics: bool = True        # учитывать физическую природу параметра при распространении
    use_checks: bool = True         # формальная перепроверка ограничений новым значением
    use_doc_filter: bool = True     # документы — только с утверждениями о релевантных параметрах
    use_load_path: bool = True      # путь нагрузки (DEPENDS_ON между компонентами)
    use_direction: bool = True      # учитывать направление изменения (смягчение не требует перепроверки)
    use_composition_filter: bool = False  # по составу — только к деталям с данными (проверено: не улучшает F1, см. журнал)
    min_confidence: float = 0.0


class ImpactAnalyzer:
    def __init__(self, kb: KnowledgeBase, graph: NetworkXStore, settings: ImpactSettings | None = None):
        self.kb, self.g = kb, graph
        self.s = settings or ImpactSettings()
        self.by_con: dict[tuple[str, str], list[Requirement]] = {}
        self.by_param: dict[str, dict[str, list[Requirement]]] = {}     # параметр → объект → требования
        for r in kb.requirements.values():
            if r.status == "active":
                self.by_con.setdefault((r.subject_id, r.parameter), []).append(r)
                self.by_param.setdefault(r.parameter, {}).setdefault(r.subject_id, []).append(r)

    def _name(self, eid):
        e = self.kb.entities.get(eid)
        return e.name if e else eid

    def _type(self, eid):
        e = self.kb.entities.get(eid)
        return e.type.value if e else "Unknown"

    # ------------------------------------------------------------------ основной метод
    def analyze(self, requirement_id: str, new_value: float | None = None, new_low: float | None = None,
                new_high: float | None = None, unit: str | None = None, _rot: float | None = None,
                _nested: bool = False) -> ImpactReport:
        t0 = time.perf_counter()
        r = self.kb.requirements[requirement_id]
        conv = (lambda x: x)
        if unit:
            u = match_unit(unit)
            if u is None or u.dimension != r.dimension:
                raise ValueError(f"Единица «{unit}» несовместима с параметром {r.parameter} ({r.unit})")
            conv = (lambda x: None if x is None else to_canonical(x, u))
        new = r.model_copy(update={"value": conv(new_value) if new_value is not None else r.value,
                                   "low": conv(new_low) if new_low is not None else r.low,
                                   "high": conv(new_high) if new_high is not None else r.high})
        subj, param = r.subject_id, r.parameter
        con = f"con:{subj}:{param}"
        prop = PROPAGATION.get(param, DEFAULT_PROPAGATION) if self.s.use_physics else \
            {"contains_down": True, "materials": True}
        items: dict[str, ImpactItem] = {}
        derived: list[DerivedImpact] = []
        used_edges = []
        old_i, new_i = r.interval(), new.interval()
        harsher = (change_is_harsher(param, old_i, new_i, r.operator)
                   if self.s.use_direction and old_i and new_i else True)
        rot = _rot or self._nominal_value(subj, "rotation_speed")
        not_rechecked: list[str] = []

        def put(eid, relation, conf, path, evidence, cls):
            if self._type(eid) not in COMPONENT_TYPES and self._type(eid) != EntityType.MATERIAL.value:
                return
            if self._type(eid) == EntityType.PRODUCT.value:
                return       # изделие в целом не считается «затронутым компонентом»
            cur = items.get(eid)
            if cur is None or conf > cur.confidence:
                items[eid] = ImpactItem(entity_id=eid, name=self._name(eid), entity_type=self._type(eid), impact_class=cls,
                                        relation=relation, confidence=round(conf, 3), path=path, evidence=evidence[:2])

        def put_dep(eid, relation, conf, path, evidence, edge=None):
            """Зависимый узел. При смягчении — только если формальная проверка показывает нарушение."""
            if harsher:
                if edge is not None:
                    used_edges.append(edge)
                put(eid, relation, conf, path, evidence, "direct")
                return
            if self._type(eid) not in COMPONENT_TYPES or self._type(eid) == EntityType.PRODUCT.value:
                return
            chk = self._check(eid, param, new, prop, rot) if self.s.use_checks else None
            if chk and chk.verdict == "violation":
                if edge is not None:
                    used_edges.append(edge)
                put(eid, relation, conf, path, evidence, "confirmed")
                items[eid].check = chk
            elif eid not in not_rechecked:
                not_rechecked.append(eid)

        base_path = [PathStep(node=r.id), PathStep(node=con, via="CONSTRAINS")]
        # 1) субъект требования
        put(subj, "subject", 1.0, [PathStep(node=r.id), PathStep(node=subj, via="CONSTRAINS")], r.evidence, "direct")
        # 1б) компоненты, номинал которых задаёт ту же величину (частота вращения изделия = двигателя)
        for s_, reqs in self.by_param.get(param, {}).items():
            if s_ != subj and any(x.kind == "nominal" for x in reqs):
                x = next(x for x in reqs if x.kind == "nominal")
                put(s_, "realizes", 0.9, base_path + [PathStep(node=x.id), PathStep(node=s_, via="CONSTRAINS")],
                    x.evidence, "direct")
        # 2) компоненты, явно зависящие от изменяемой характеристики
        for e in self.g.in_edges(con, [RelationType.DEPENDS_ON]):
            put_dep(e.source, "dependent", e.weight * _econf(e), base_path + [
                PathStep(node=e.source, via="DEPENDS_ON", reverse=True)], e.evidence, e)
        # 2б) вкладчики: характеристика изделия зависит от компонентов (масса агрегата — от двигателя и рамы)
        for e in self.g.out_edges(con, [RelationType.DEPENDS_ON]):
            if self._type(e.target) in COMPONENT_TYPES:
                put_dep(e.target, "contributor", e.weight * _econf(e), base_path + [
                    PathStep(node=e.target, via="DEPENDS_ON")], e.evidence, e)
        # 2в) компоненты с собственным ограничением по тому же параметру (ТУ уплотнения: до 3600 об/мин)
        for s_, reqs in self.by_param.get(param, {}).items():
            if s_ != subj and self._type(s_) in COMPONENT_TYPES:
                cap = next((x for x in reqs if x.kind == "capability"), None)
                if cap is not None:
                    put_dep(s_, "own_limit", 0.9 * cap.confidence, base_path + [PathStep(node=cap.id),
                            PathStep(node=s_, via="CONSTRAINS")], cap.evidence)
        # 3) производные характеристики (испытательное давление, давление настройки клапана)
        for e in self.g.in_edges(con, [RelationType.DERIVED_FROM]):
            used_edges.append(e)
            dcon = e.source
            dsubj = self.kb.entities[dcon].attrs.get("subject_id") if dcon in self.kb.entities else None
            dparam = self.kb.entities[dcon].attrs.get("parameter") if dcon in self.kb.entities else None
            factor = e.attrs.get("factor")
            base = new.value if not isinstance(new.value, str) else None
            exp = round(base * factor, 4) if factor and base is not None else None
            stated = self.by_con.get((dsubj, dparam), [])
            derived.append(DerivedImpact(constraint_id=dcon, factor=factor, new_expected=exp,
                                         description=f"{PARAM_RU.get(dparam, dparam)} «{self._name(dsubj)}» = "
                                                     f"{factor:g} × {PARAM_RU.get(param, param)}",
                                         stated=[f"{fmt_req(x)} ({self._docname(x.document_id)})" for x in stated],
                                         evidence=e.evidence[:1]))
            if dsubj:
                put(dsubj, "derived", e.weight * _econf(e), [PathStep(node=r.id), PathStep(node=con, via="CONSTRAINS"),
                    PathStep(node=dcon, via="DERIVED_FROM", reverse=True), PathStep(node=dsubj, via="CHARACTERIZES")],
                    e.evidence, "direct")
        # 3б) законы подобия: частота вращения → подача, напор, мощность (вложенный анализ производных изменений)
        nested: list[ImpactReport] = []
        if (not _nested and param in AFFINITY and r.operator == "=" and not isinstance(r.value, str)
                and not isinstance(new.value, str) and r.value):
            ratio = new.value / r.value
            scope = [subj] + sorted(self.g.descendants(subj))
            for tparam, k in AFFINITY[param].items():
                for s_ in scope:
                    x = next((y for y in self.by_con.get((s_, tparam), []) if y.kind == "nominal"
                              and not isinstance(y.value, str)), None)
                    if x is None:
                        continue
                    nv = x.value * ratio ** k
                    derived.append(DerivedImpact(constraint_id=f"con:{s_}:{tparam}", factor=round(ratio ** k, 4),
                                                 new_expected=round(nv, 3),
                                                 description=f"{PARAM_RU.get(tparam, tparam)} «{self._name(s_)}» ∝ "
                                                             f"n{'' if k == 1 else '²' if k == 2 else '³'} (законы подобия)",
                                                 stated=[f"{fmt_req(x)} ({self._docname(x.document_id)})"],
                                                 evidence=x.evidence[:1]))
                    sub = self.analyze(x.id, new_value=nv, _rot=new.value, _nested=True)
                    nested.append(sub)
                    for it in sub.items:
                        it = it.model_copy(update={"relation": "derived", "path": base_path + it.path,
                                                   "confidence": round(it.confidence * 0.9, 3)})
                        cur = items.get(it.entity_id)
                        if cur is None or (it.impact_class == "confirmed" and cur.impact_class != "confirmed"):
                            items[it.entity_id] = it
                    break
        # 4) транзитивное распространение
        frontier = [(i.entity_id, i.confidence, i.path) for i in items.values()]
        for depth in range(1, self.s.max_depth + 1):
            nxt = []
            for eid, conf, path in frontier:
                if prop["contains_down"]:
                    for e in self.g.out_edges(eid, [RelationType.CONTAINS]):
                        c = conf * e.weight * self.s.decay
                        if e.target not in items and (not self.s.use_composition_filter
                                                      or self._has_check_data(e.target, param)):
                            put(e.target, "contained", c, path + [PathStep(node=e.target, via="CONTAINS")], e.evidence, "potential")
                            nxt.append((e.target, c, items[e.target].path if e.target in items else path))
                if self.s.use_load_path and depth == 1 and eid == subj:
                    for e in self.g.in_edges(eid, [RelationType.DEPENDS_ON]):
                        if self._type(e.source) in COMPONENT_TYPES and e.source not in items:
                            used_edges.append(e)
                            c = conf * e.weight * self.s.decay
                            put(e.source, "load_path", c, path + [PathStep(node=e.source, via="DEPENDS_ON", reverse=True)],
                                e.evidence, "potential")
            frontier = nxt
            if not frontier:
                break
        # 4б) материалы затронутых деталей (для тепловых параметров)
        if prop["materials"]:
            for it in list(items.values()):
                for m in self.g.materials(it.entity_id):
                    put(m.target, "material", it.confidence * m.weight, it.path + [PathStep(node=m.target, via="USES_MATERIAL")],
                        m.evidence, "potential")
        # 5) формальная проверка новым значением
        for it in list(items.values()):
            if it.check is not None:
                continue
            if it.entity_type == EntityType.MATERIAL.value:
                it.check = self._check_material(it.entity_id, new) if self.s.use_checks else None
            else:
                it.check = self._check(it.entity_id, param, new, prop, rot) if self.s.use_checks else None
            if it.check and it.check.verdict == "violation":
                it.impact_class = "confirmed"
            elif it.check and it.check.verdict in ("at_limit", "no_data") and it.impact_class == "direct":
                it.impact_class = "direct"
        items = {k: v for k, v in items.items() if v.confidence >= self.s.min_confidence}
        # 6) испытания, документы, конфликты
        same = [x for x in self.by_con.get((subj, param), []) if x.id != r.id]
        tests = self._tests([r] + same, new, harsher, derived)
        docs = self._documents(r, same, items, derived, used_edges, tests, param)
        if not harsher and not _nested:
            # смягчение: компоненты не перепроверяются, но документы, утверждающие изменяемую величину и
            # ограничения зависимых узлов, приводятся в соответствие — перечень как при ужесточении
            full = ImpactAnalyzer(self.kb, self.g, ImpactSettings(**{**asdict(self.s), "use_direction": False}))
            full.by_con, full.by_param = self.by_con, self.by_param
            fr = full.analyze(requirement_id, new_value=new_value, new_low=new_low, new_high=new_high, unit=unit,
                              _rot=_rot, _nested=True)
            have = {d.document_id for d in docs}
            docs = sorted(docs + [d for d in fr.documents if d.document_id not in have], key=lambda d: d.filename)
        for sub in nested:
            have_t = {t.test_id for t in tests}
            tests += [t for t in sub.tests if t.test_id not in have_t]
            have_d = {d.document_id for d in docs}
            docs += [d for d in sub.documents if d.document_id not in have_d]
            docs.sort(key=lambda d: d.filename)
        conflicts = self._conflicts(new, same)
        rec = self._recommendations(items, docs, tests, derived, conflicts)
        return ImpactReport(
            requirement_id=r.id, requirement_text=r.text, parameter=param, subject_id=subj, old=fmt_req(r), new=fmt_req(new),
            items=sorted(items.values(), key=lambda i: ({"confirmed": 0, "direct": 1, "potential": 2, "documentary": 3}
                                                       [i.impact_class], -i.confidence)),
            documents=docs, tests=tests, derived=derived, conflicts_after_change=conflicts, recommendations=rec,
            settings=asdict(self.s), elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            change_direction="harsher" if harsher else "milder", not_rechecked=[self._name(x) for x in not_rechecked])

    # ------------------------------------------------------------------ проверки
    def _has_check_data(self, comp: str, param: str) -> bool:
        """Есть ли у детали данные для проверки: материал или ограничение по связанному параметру.
        Деталь без таких данных не включается в затронутые по составу — проверить её нечем."""
        if self.g.materials(comp) or self.g.out_edges(comp, [RelationType.CONTAINS]):
            return True
        return any(self.by_con.get((comp, p)) for p in related(param))

    def _nominal_value(self, subj, param):
        for s in [subj] + self.g.ancestors(subj):
            for x in self.by_con.get((s, param), []):
                if x.kind in ("nominal", "demand") and x.operator == "=" and not isinstance(x.value, str):
                    return x.value
        return None

    def _check(self, comp, param, new: Requirement, prop, rot) -> CheckResult:
        checks: list[CheckResult] = []
        interval = new.interval()
        for cap in (c for c in self.by_con.get((comp, param), []) if c.kind == "capability"):
            ok, margin = covers(interval, cap.interval(), new.operator)
            checks.append(self._verdict(ok, margin, f"{self._name(comp)}: {fmt_req(cap)} ({self._docname(cap.document_id)})"
                                                    f" при новом значении {fmt_req(new)}", [cap.id]))
        if prop["materials"] and param in MATERIAL_LIMITED:
            for m in self.g.materials(comp):
                for cap in self.by_con.get((m.target, "material_temperature"), []):
                    ok, margin = covers(interval, cap.interval(), new.operator)
                    checks.append(self._verdict(ok, margin, f"материал «{self._name(m.target)}»: {fmt_req(cap)} "
                                                            f"при {fmt_req(new)}", [cap.id, m.id]))
        if new.kind == "demand" and interval:
            for sp in (c for c in self.by_con.get((comp, param), []) if c.kind == "setpoint" and not isinstance(c.value, str)):
                ok, margin = covers((sp.value, sp.value), interval, "=")
                checks.append(self._verdict(ok, margin, f"уставка {fmt_req(sp)} ({self._docname(sp.document_id)}) "
                                                        f"при новом пределе {fmt_req(new)}", [sp.id]))
        for rule in DERIVED_RULES.get(param, []):
            if rot and not isinstance(new.value, str) and new.value is not None:
                val = rule["fn"](new.value, rot)
                for cap in (c for c in self.by_con.get((comp, rule["target"]), []) if c.kind == "capability"):
                    ok, margin = covers((val, val), cap.interval(), "=")
                    checks.append(self._verdict(ok, margin, f"{rule['formula']}: {val:.0f} {cap.unit} при n = {rot:g} об/мин; "
                                                            f"допустимо {fmt_req(cap)} ({self._docname(cap.document_id)})",
                                                [cap.id]))
        if not checks:
            return CheckResult(verdict="no_data", detail="Нет извлечённых ограничений компонента для проверки")
        order = {"violation": 0, "at_limit": 1, "ok": 2}
        worst = min(checks, key=lambda c: order[c.verdict])
        return CheckResult(verdict=worst.verdict, detail="; ".join(c.detail for c in sorted(checks, key=lambda c: order[c.verdict])),
                           against=[a for c in checks for a in c.against], margin=worst.margin)

    def _check_material(self, mat, new: Requirement) -> CheckResult:
        caps = self.by_con.get((mat, "material_temperature"), [])
        if not caps:
            return CheckResult(verdict="no_data", detail="Нет данных о температуре применения материала")
        c = caps[0]
        ok, margin = covers(new.interval(), c.interval(), new.operator)
        return self._verdict(ok, margin, f"материал «{self._name(mat)}»: {fmt_req(c)} при {fmt_req(new)}", [c.id])

    @staticmethod
    def _verdict(ok, margin, detail, against) -> CheckResult:
        if not ok:
            return CheckResult(verdict="violation", detail="НАРУШЕНИЕ — " + detail, against=against, margin=margin)
        if margin is not None and margin < MARGIN_WARN:
            return CheckResult(verdict="at_limit", detail=f"на пределе (запас {margin:.0%}) — " + detail, against=against,
                               margin=margin)
        return CheckResult(verdict="ok", detail="соответствует — " + detail, against=against, margin=margin)

    # ------------------------------------------------------------------ испытания
    def _tests(self, reqs: list[Requirement], new: Requirement, harsher: bool = True,
               derived: list[DerivedImpact] | None = None) -> list[TestImpact]:
        """Испытания, проверяющие изменяемое требование; повторение — если прежний результат не подтверждает новое."""
        targets = [(new.parameter, new.interval(), new.operator, new.dimension)]
        for dv in derived or []:
            ent = self.kb.entities.get(dv.constraint_id)
            if ent and dv.new_expected is not None and dv.factor is not None:
                dparam = ent.attrs.get("parameter")
                dreq = next(iter(self.by_con.get((ent.attrs.get("subject_id"), dparam), [])), None)
                if dreq is not None:
                    targets.append((dparam, (dv.new_expected, dv.new_expected), "=", dreq.dimension))
        out: dict[str, TestImpact] = {}
        for x in reqs:
            for e in self.g.out_edges(x.id, [RelationType.VERIFIED_BY]):
                t = self.kb.entities.get(e.target)
                if not t or e.target in out:
                    continue
                res = t.attrs.get("result")
                valid = self._result_valid(res or "", new, targets, harsher)
                if valid:
                    reason = f"зафиксированный результат «{res}» подтверждает новое значение — повторение не требуется"
                elif res and valid is False and new.kind != "nominal":
                    reason = f"зафиксированный результат «{res}» не подтверждает новое значение {fmt_req(new)} — повторить"
                else:
                    reason = "проверяет изменяемое требование — требуется повторение по новому значению"
                out[e.target] = TestImpact(test_id=e.target, name=t.name, reason=reason, result=res,
                                           result_still_valid=valid, repeat_required=not valid, evidence=e.evidence[:1])
        return list(out.values())

    @staticmethod
    def _result_valid(text: str, new: Requirement, targets, harsher: bool) -> bool:
        """Подтверждает ли прежний результат испытания новое требование.
        Номинал изменился → режим испытания другой → повторить. Для нагрузки (класс load) число в результате —
        условие испытания: годно, если оно не мягче новой границы. Для состояния/бюджета — измеренный отклик:
        годен, если укладывается в новый предел с запасом не менее MARGIN_WARN. Если результат не относится к
        изменяемой величине — испытание проведено при прежнем значении: годно только при смягчении."""
        if new.kind == "nominal":
            return False
        low = text.lower()
        hits = find_params(low)
        dims = {d for *_, d in targets}
        if hits and not any(h.key == tp for h in hits for tp, *_ in targets):
            return not harsher
        start = hits[0].end if hits else 0
        value = None
        for m in NUM_RE.finditer(text, start):        # единицы — по исходному регистру («°C»)
            u = match_unit(text, m.end())
            if u and u.dimension in dims:
                value, vdim = to_canonical(parse_number(m.group(0)), u), u.dimension
                break
        if value is None:
            return not harsher
        hit_keys = {h.key for h in hits}
        ok_all = True
        for tp, (lo, hi), op, dim in targets:
            if dim != vdim or (hit_keys and tp not in hit_keys and len(targets) == 1):
                continue
            if PARAM_CLASS.get(tp, "load") == "load":
                if op == "<=":
                    ok = value >= hi - 1e-9
                elif op == ">=":
                    ok = value <= lo + 1e-9
                elif op == "=":
                    ok = value >= hi - 1e-9
                else:
                    ok = value <= lo + 1e-9 if abs(value - lo) <= abs(value - hi) else value >= hi - 1e-9
            else:
                ok, margin = covers((value, value), (lo, hi), "=")
                ok = ok and (margin is None or margin >= MARGIN_WARN)
            ok_all &= ok
        return ok_all

    # ------------------------------------------------------------------ документы
    def _docname(self, doc_id):
        d = self.kb.documents.get(doc_id)
        return (d.code or d.filename) if d else doc_id

    def _documents(self, r, same, items, derived, used_edges, tests, param) -> list[DocumentImpact]:
        acc: dict[str, DocumentImpact] = {}

        def add(doc_id, reason, item_id, evidence):
            d = self.kb.documents.get(doc_id)
            if d is None:
                return
            x = acc.setdefault(doc_id, DocumentImpact(document_id=doc_id, filename=d.filename, code=d.code, reasons=[],
                                                      items=[]))
            if reason not in x.reasons:
                x.reasons.append(reason)
            if item_id not in x.items:
                x.items.append(item_id)
            if evidence and len(x.evidence) < 4:
                x.evidence.append(evidence)

        for x in [r] + same:
            add(x.document_id, f"содержит требование «{PARAM_RU.get(param, param)}» ({fmt_req(x)})", x.id, x.evidence[0])
        for dv in derived:
            a = self.kb.entities.get(dv.constraint_id)
            if a:
                for x in self.by_con.get((a.attrs["subject_id"], a.attrs["parameter"]), []):
                    add(x.document_id, f"содержит производную величину ({dv.description})", x.id, x.evidence[0])
        for e in used_edges:
            for evd in e.evidence:
                add(evd.document_id, "описывает зависимость от изменяемой характеристики", e.id, evd)
        for t in tests:
            for e in self.g.documents_of(t.test_id):
                add(e.target, f"испытание «{t.name}»", t.test_id, e.evidence[0])
        rel = related(param)
        for it in items.values():
            if self.s.use_doc_filter:
                subjects = [it.entity_id] + ([m.target for m in self.g.materials(it.entity_id)]
                                             if param in MATERIAL_LIMITED else [])
                for s in subjects:
                    for cp in sorted(rel):
                        for x in self.by_con.get((s, cp), []):
                            add(x.document_id, f"ограничение «{self._name(s)}»: {PARAM_RU.get(cp, cp)} {fmt_req(x)}",
                                x.id, x.evidence[0])
            else:
                for e in self.g.documents_of(it.entity_id):
                    add(e.target, f"упоминает «{it.name}»", it.entity_id, e.evidence[0])
        return sorted(acc.values(), key=lambda d: d.filename)

    # ------------------------------------------------------------------ конфликты после изменения
    def _conflicts(self, new: Requirement, same: list[Requirement]) -> list[Contradiction]:
        out = []
        for x in same:
            if x.kind in ("demand", "nominal") and not same_bounds(new, x):
                out.append(Contradiction(
                    id=f"ctr:after:{x.id}", type="value_mismatch", status="confirmed", severity="medium",
                    title=f"После изменения расходится: {self._docname(x.document_id)}",
                    description=f"новое {fmt_req(new)} ≠ {fmt_req(x)} ({self._docname(x.document_id)})",
                    explanation="Документ содержит прежнее или иное значение той же характеристики.",
                    recommendation=f"Внести изменение в {self._docname(x.document_id)}.", entities=[new.subject_id],
                    items=[new.id, x.id], evidence=x.evidence[:1], confidence=x.confidence))
        return out

    def _recommendations(self, items, docs, tests, derived, conflicts) -> list[str]:
        rec = []
        viol = [i for i in items.values() if i.impact_class == "confirmed"]
        for i in viol:
            rec.append(f"«{i.name}»: {i.check.detail.split(';')[0]}. Требуется замена/доработка или пересмотр изменения.")
        lim = [i for i in items.values() if i.check and i.check.verdict == "at_limit"]
        for i in lim:
            rec.append(f"«{i.name}»: значение на пределе допустимого — оценить запас и условия эксплуатации.")
        nod = [i.name for i in items.values() if i.check and i.check.verdict == "no_data" and i.impact_class != "confirmed"]
        if nod:
            rec.append("Нет данных для формальной проверки: " + ", ".join(nod) + " — запросить характеристики у держателей документации.")
        for dv in derived:
            if dv.new_expected is not None:
                rec.append(f"Пересчитать: {dv.description} → {dv.new_expected:g}; в документах: {', '.join(dv.stated) or 'нет значения'}.")
        for t in tests:
            rec.append(f"Испытание «{t.name}»: {t.reason}.")
        if docs:
            rec.append("Выпустить извещения об изменении для документов: " + ", ".join(d.code or d.filename for d in docs) + ".")
        return rec


def _econf(rel) -> float:
    return max((e.confidence for e in rel.evidence), default=0.5)


def find_requirement(kb: KnowledgeBase, subject_id: str, parameter: str, doc_type: str = "TechnicalSpecification"):
    cands = [r for r in kb.requirements.values() if r.subject_id == subject_id and r.parameter == parameter]
    cands.sort(key=lambda r: (kb.documents[r.document_id].doc_type != doc_type, r.document_id))
    return cands[0] if cands else None


_ = re

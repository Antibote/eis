"""Инженерный помощник: вопрос на естественном языке → ответ из графа знаний и поиска со ссылками на источники.

1. Определяется намерение (правила) и упомянутые сущности.
2. Соответствующий сервис возвращает структурированные факты, у каждого — evidence.
3. Формируется детерминированный ответ (работает без LLM); каждое утверждение — со ссылкой [n].
4. Если LLM доступна — она переформулирует ответ по тем же фрагментам; citation guard удаляет
   утверждения без опоры на источники. Факты, отсутствующие в контексте, в ответ не попадают.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from eis.domain.models import Evidence, RelationType
from eis.llm.guard import guard
from eis.llm.providers import SYSTEM_GUARD, LLMProvider, NullProvider
from eis.services.change_request import parse_change
from eis.services.contradictions import PARAM_RU, fmt_req
from eis.services.impact import ImpactAnalyzer
from eis.services.workspace import Workspace

INTENTS = [
    ("impact", re.compile(r"что\s+(?:будет|произойд\w+|изменится)|если\s+(?:измен|увелич|уменьш|сниз|повыс|ужесточ)|последстви")),
    ("why", re.compile(r"почему|на\s+каком\s+основании|обоснуй")),
    ("contradictions", re.compile(r"противореч|расхожден|несоответстви|конфликт")),
    ("tests", re.compile(r"испытани|проверк\w+\s+требовани")),
    ("revise", re.compile(r"пересмотр|пересмотрет|переработ|актуализ")),
    ("value", re.compile(r"как\w*\s+значени|чему\s+равн|каков\w*\s+(?:значени|величин|предел)|сколько\s+составля|"
                         r"како\w*\s+(?:предел|допуст|номинал|рабоч|максимальн|минимальн)")),
    ("documents", re.compile(r"документ")),
    ("requirements", re.compile(r"требовани|ограничени|характеристик")),
]
DOC_TYPE_WORDS = {"спецификац": "Specification", "техническ\\w* задани|тз\\b": "TechnicalSpecification",
                  "руководств": "OperationManual", "программ\\w* и методик|пми": "TestProgram",
                  "техническ\\w* услови": "ComponentSpecification", "паспорт": "Passport", "расч[её]т": "Calculation"}


@dataclass
class Answer:
    question: str
    intent: str
    text: str
    citations: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    llm_used: bool = False
    llm_text: str | None = None
    llm_raw: str | None = None          # ответ LLM до фильтра цитирования (для аудита и экспериментов)
    guard: dict | None = None
    warnings: list[str] = field(default_factory=list)


class Citations:
    def __init__(self, ws: Workspace):
        self.ws, self.items, self.by_key = ws, [], {}

    def ref(self, ev: Evidence | None) -> str:
        if ev is None:
            return ""
        key = (ev.fragment_id, ev.char_start, ev.char_end)
        if key not in self.by_key:
            self.items.append(self.ws.evidence_context(ev) | {"n": len(self.items) + 1})
            self.by_key[key] = len(self.items)
        return f"[{self.by_key[key]}]"


class Assistant:
    def __init__(self, ws: Workspace, llm: LLMProvider | None = None):
        self.ws, self.llm = ws, llm or NullProvider()

    def intent(self, q: str) -> str:
        lc = q.lower()
        for name, rx in INTENTS:
            if rx.search(lc):
                return name
        return "search"

    def ask(self, question: str, context_entity: str | None = None) -> Answer:
        q = question.strip()
        intent = self.intent(q)
        mentions = [m.entity_id for m in self.ws.mentions.find(q)]
        product = next((e.id for e in self.ws.kb.entities.values() if e.type.value == "Product"), None)
        ents = [m for m in mentions if m != product] or ([context_entity] if context_entity else []) or mentions
        cites = Citations(self.ws)
        handler = getattr(self, f"_{intent}")
        lines, facts, warnings = handler(q, ents, cites)
        if not lines:
            intent_used = intent
            lines, facts, warnings2 = self._search(q, ents, cites)
            warnings += warnings2 + [f"Для намерения «{intent_used}» не найдено структурированных данных — показаны результаты поиска."]
        ans = Answer(question=q, intent=intent, text="\n".join(lines), citations=cites.items, facts=facts, entities=ents,
                     warnings=warnings)
        if self.llm.available and cites.items:
            self._llm_rewrite(ans)
        return ans

    # ------------------------------------------------------------ обработчики намерений
    def _name(self, eid):
        e = self.ws.kb.entities.get(eid)
        return e.name if e else eid

    def _docname(self, did):
        d = self.ws.kb.documents.get(did)
        return (d.code or d.filename) if d else did

    def _documents(self, q, ents, c):
        lines, facts = [], []
        for eid in ents[:3]:
            rels = self.ws.graph.documents_of(eid)
            if not rels:
                continue
            lines.append(f"С «{self._name(eid)}» связаны документы:")
            for r in sorted(rels, key=lambda r: self._docname(r.target)):
                ev = r.evidence[0]
                lines.append(f"• {self._docname(r.target)} — {self.ws.kb.documents[r.target].title} {c.ref(ev)}")
                facts.append({"entity": eid, "document": r.target})
        return lines, facts, [] if ents else ["Не распознан компонент в вопросе."]

    def _subject_requirements(self, eid):
        subj = {eid} | self.ws.graph.descendants(eid)
        return [r for r in self.ws.kb.requirements.values() if r.subject_id in subj]

    def _requirements(self, q, ents, c):
        lines, facts = [], []
        for eid in ents[:2]:
            reqs = self._subject_requirements(eid)
            if not reqs:
                continue
            lines.append(f"Требования и ограничения, относящиеся к «{self._name(eid)}»:")
            for r in sorted(reqs, key=lambda r: (r.parameter, r.document_id)):
                who = "" if r.subject_id == eid else f" ({self._name(r.subject_id)})"
                lines.append(f"• {PARAM_RU.get(r.parameter, r.parameter)}{who}: {fmt_req(r)} — {self._docname(r.document_id)}"
                             f"{' п. ' + r.section if r.section else ''} {c.ref(r.evidence[0])}")
                facts.append({"requirement": r.id})
        return lines, facts, []

    def _value(self, q, ents, c):
        """Значение параметра объекта: «какое значение … для … указано в документе …»."""
        from eis.extraction.lexicon import find_params
        params = [h.key for h in find_params(q.lower())]
        if not params:
            return [], [], []
        codes = {d.id for d in self.ws.kb.documents.values() if d.code and d.code.lower() in q.lower()}
        types = {t for rx, t in DOC_TYPE_WORDS.items() if re.search(rx, q.lower())}
        cands = [r for e in ents for r in self._subject_requirements(e) if r.parameter in params] if ents else []
        if not cands:          # объект не назван или требований к нему нет — по всем объектам
            cands = [r for r in self.ws.kb.requirements.values() if r.parameter in params]
        if codes:
            cands = [r for r in cands if r.document_id in codes] or cands
        elif types:
            cands = [r for r in cands if self.ws.kb.documents[r.document_id].doc_type in types] or cands
        lines, facts = [], []
        for r in sorted(cands, key=lambda r: (r.document_id, r.section or ""))[:8]:
            lines.append(f"• {PARAM_RU.get(r.parameter, r.parameter)} «{self._name(r.subject_id)}»: {fmt_req(r)} — "
                         f"{self._docname(r.document_id)}{' п. ' + r.section if r.section else ''} {c.ref(r.evidence[0])}")
            facts.append({"requirement": r.id})
        return lines, facts, []

    def _tests(self, q, ents, c):
        lines, facts = [], []
        reqs = [r for e in ents for r in self._subject_requirements(e)] if ents else list(self.ws.kb.requirements.values())
        params = {h.key for h in __import__("eis.extraction.lexicon", fromlist=["find_params"]).find_params(q.lower())}
        if params:
            reqs = [r for r in reqs if r.parameter in params] or reqs
        seen = set()
        for r in reqs:
            for e in self.ws.graph.out_edges(r.id, [RelationType.VERIFIED_BY]):
                if (e.target, r.id) in seen:
                    continue
                seen.add((e.target, r.id))
                t = self.ws.kb.entities[e.target]
                res = f"; результат: {t.attrs['result']}" if t.attrs.get("result") else ""
                lines.append(f"• {t.designation} «{t.name}» проверяет требование {self._docname(r.document_id)} п. {r.section} "
                             f"({PARAM_RU.get(r.parameter)}: {fmt_req(r)}){res} {c.ref(e.evidence[0])}{c.ref(r.evidence[0])}")
                facts.append({"test": e.target, "requirement": r.id})
        if lines:
            lines.insert(0, "Связанные испытания:")
        return lines, facts, []

    def _contradictions(self, q, ents, c):
        lc = q.lower()
        types = {t for rx, t in DOC_TYPE_WORDS.items() if re.search(rx, lc)}
        lines, facts = [], []
        for x in self.ws.contradictions:
            docs = {e.document_id for e in x.evidence}
            dtypes = {self.ws.kb.documents[d].doc_type for d in docs if d in self.ws.kb.documents}
            if types and not types <= dtypes and not (len(types) == 1 and types & dtypes):
                continue
            if ents and not (set(ents) & set(x.entities)):
                involved = set(x.entities)
                if not any(e in involved or e in {a for i in involved for a in self.ws.graph.ancestors(i)} for e in ents):
                    continue
            refs = "".join(c.ref(e) for e in x.evidence[:2])
            status = {"confirmed": "подтверждено", "potential": "потенциальное", "insufficient_data": "недостаточно данных"}[x.status]
            lines.append(f"• [{status}, {x.severity}] {x.title}: {x.description} {refs}")
            facts.append({"contradiction": x.id})
        if lines:
            lines.insert(0, f"Найдено противоречий: {len(facts)}.")
        elif types or ents:
            lines = ["Противоречий по заданному фильтру не обнаружено формальными и графовыми проверками."]
        return lines, facts, []

    def _impact(self, q, ents, c, revise_only=False):
        try:
            pc = parse_change(q, self.ws.kb, self.ws.graph, self.ws.mentions)
        except ValueError as e:
            return self._dependents_only(q, ents, c, str(e))
        rep = ImpactAnalyzer(self.ws.kb, self.ws.graph).analyze(pc.requirement.id, new_value=pc.new_value,
                                                                new_low=pc.new_low, new_high=pc.new_high)
        r = pc.requirement
        lines = [f"Изменение: {PARAM_RU.get(r.parameter)} «{self._name(r.subject_id)}» {rep.old} → {rep.new} "
                 f"({self._docname(r.document_id)} п. {r.section}) {c.ref(r.evidence[0])}"]
        facts = [{"impact_requirement": r.id, "new": rep.new}]
        if not revise_only:
            cls_ru = {"confirmed": "подтверждённое влияние", "direct": "прямая зависимость", "potential": "потенциальное влияние"}
            for it in rep.items:
                if it.entity_type == "Material":
                    continue
                chk = f" — {it.check.detail.split(';')[0]}" if it.check and it.check.verdict != "no_data" else ""
                refs = "".join(c.ref(e) for e in it.evidence[:1])
                if it.check and it.check.against:
                    for a in it.check.against[:1]:
                        if a in self.ws.kb.requirements:
                            refs += c.ref(self.ws.kb.requirements[a].evidence[0])
                lines.append(f"• {it.name}: {cls_ru[it.impact_class]}{chk} {refs}")
        lines.append("Документы на пересмотр: " + ", ".join(
            f"{d.code or d.filename} {c.ref(d.evidence[0]) if d.evidence else ''}" for d in rep.documents))
        if rep.tests:
            lines.append("Испытания: " + "; ".join(f"{t.name} — {t.reason} {c.ref(t.evidence[0]) if t.evidence else ''}"
                                                   for t in rep.tests))
        facts.append({"report": rep.model_dump(mode="json")})
        return lines, facts, []

    def _revise(self, q, ents, c):
        return self._impact(q, ents, c, revise_only=True)

    def _dependents_only(self, q, ents, c, why):
        from eis.extraction.lexicon import find_params
        params = [h.key for h in find_params(q.lower())]
        if not params:
            return [], [], [why]
        lines, facts = [f"Значение изменения не указано ({why}). От характеристики «{PARAM_RU.get(params[0])}» зависят:"], []
        for e in self.ws.kb.relations.values():
            if e.type == RelationType.DEPENDS_ON and e.target.endswith(":" + params[0]):
                lines.append(f"• {self._name(e.source)} {c.ref(e.evidence[0])}")
                facts.append({"dependent": e.source})
        lines.append("Укажите новое значение («с … до …»), чтобы выполнить проверку ограничений.")
        return (lines, facts, []) if facts else ([], [], [why])

    def _why(self, q, ents, c):
        lines, facts = [], []
        for eid in ents[:2]:
            deps = self.ws.graph.out_edges(eid, [RelationType.DEPENDS_ON])
            parents = self.ws.graph.ancestors(eid)
            if not deps and not parents:
                continue
            lines.append(f"Связи «{self._name(eid)}» с характеристиками изделия:")
            for d in deps:
                tgt = self.ws.kb.entities.get(d.target)
                what = (f"{PARAM_RU.get(tgt.attrs.get('parameter'), '')} «{self._name(tgt.attrs.get('subject_id'))}»"
                        if tgt and tgt.type.value == "Constraint" else self._name(d.target))
                lines.append(f"• зависит от: {what} {c.ref(d.evidence[0])}")
                facts.append({"depends_on": d.target})
            if parents:
                pe = self.ws.graph.in_edges(eid, [RelationType.CONTAINS])
                lines.append(f"• входит в состав: {' → '.join(self._name(p) for p in parents)} {c.ref(pe[0].evidence[0]) if pe else ''}")
            caps = [r for r in self.ws.kb.requirements.values() if r.subject_id == eid and r.kind == "capability"]
            for r in caps:
                lines.append(f"• собственное ограничение: {PARAM_RU.get(r.parameter)} {fmt_req(r)} {c.ref(r.evidence[0])}")
            lines.append("Компонент считается затронутым, если изменяется характеристика, от которой он зависит; "
                         "подтверждённым — если новое значение нарушает его собственное ограничение.")
        return lines, facts, []

    def _search(self, q, ents, c):
        hits = self.ws.retriever.search(q, k=5)
        lines, facts, warnings = [], [], []
        for h in hits:
            if "suspected_injection" in h.flags:
                warnings.append("Фрагмент с признаками инструкции для ИИ исключён из ответа.")
                continue
            f = h.fragment
            ev = Evidence(document_id=f.document_id, fragment_id=f.id, page=f.page, locator=f.locator, quote=f.text,
                          char_start=0, char_end=len(f.text))
            lines.append(f"• {self._docname(f.document_id)}: «{f.text}» {c.ref(ev)}")
            facts.append({"fragment": f.id, "score": h.score})
        if lines:
            lines.insert(0, "Наиболее релевантные фрагменты документации:")
        return lines, facts, warnings

    # ------------------------------------------------------------ LLM
    def _llm_rewrite(self, ans: Answer):
        ctx = {c["n"]: c["quote"] for c in ans.citations}
        context = "\n".join(f"[{n}] ({c['code'] or c['filename']}, {c['locator']}) {c['quote']}" for n, c in
                            ((c["n"], c) for c in ans.citations))
        user = (f"<context>\n{context}\n</context>\n\nСтруктурированный результат анализа системы:\n{ans.text}\n\n"
                f"Вопрос инженера: {ans.question}\nСформулируй краткий ответ со ссылками [n].")
        try:
            raw = self.llm.chat(SYSTEM_GUARD, user)
        except Exception as e:  # noqa: BLE001
            ans.warnings.append(f"LLM недоступна: {e}")
            return
        ans.llm_raw = raw
        g = guard(raw, ctx)
        ans.guard = {"accepted": len(g.accepted), "rejected": [{"sentence": s, "reason": r} for s, r in g.rejected],
                     "unsupported_share": round(g.unsupported_share, 3)}
        if g.accepted:
            ans.llm_text, ans.llm_used = g.text, True

"""Конвейер извлечения: разобранные документы → KnowledgeBase (сущности, требования, связи, evidence).

Порядок:
  1. классификация документов (тип, обозначение, субъект);
  2. реестр компонентов и материалов из спецификаций и ведомостей материалов;
  3. построчное извлечение: упоминания, требования, связи (правила);
  4. межДокументное связывание: ссылки «ТЗ п. 3.2.1» → VERIFIED_BY, журнал изменений → SUPERSEDES.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from eis.domain.engineering import PARAM_RU
from eis.domain.models import (Document, Entity, EntityType, Evidence, EvidenceMethod, Fragment, KnowledgeBase,
                               Relation, RelationType, Requirement, now, stable_id)
from eis.extraction.classify import classify
from eis.extraction.lexicon import INJECTION_RE, find_params
from eis.extraction.mentions import MentionIndex, lemma, lemmas_of, tokens
from eis.extraction.requirements import extract_from_table_cell, extract_requirements, sentences
from eis.extraction.units import CANONICAL

DESIG_RE = re.compile(r"^[А-ЯA-Z]{1,6}-?\d+(?:\.\d{2,3}){2,}$")
STANDARD_RE = re.compile(r"ГОСТ(?:\s+(?:Р|ИСО|ISO|IEC|EN))*\s+\d+(?:\.\d+)*(?:-\d{2,4})?")
TEST_CODE_RE = re.compile(r"^\s*([TТ]\d{2})\s+(.+)$")
TZ_REF_RE = re.compile(r"ТЗ\s+пп?\.\s*(\d+(?:\.\d+)*(?:\s*,\s*\d+(?:\.\d+)*)*)")
MATERIAL_HEAD = r"(?:резин\w*|стал\w*|сплав\w*|чугун\w*|бронз\w*|латун\w*|паронит\w*|графит\w*|фторопласт\w*|смазк\w*|карбид\w*)"
MADE_OF_RE = re.compile(r"(?:изготавлива\w+|изготовлен\w*|выполн\w+)\s+из\s+(" + MATERIAL_HEAD + r"(?:\s+[A-Za-zА-ЯЁ0-9][\w\-]*)?)",
                        re.IGNORECASE)
MATERIAL_OF_RE = re.compile(r"материал\w*\s+(.+?)\s+[—–-]\s+(" + MATERIAL_HEAD + r"(?:\s+[A-Za-zА-ЯЁ0-9][\w\-]*)?)",
                            re.IGNORECASE)
CONTAINS_RES = [
    re.compile(r"в\s+состав\s+(?P<whole>.+?)\s+вход(?:ят|ит)\s*:?\s*(?P<list>.+)"),
    re.compile(r"(?P<whole>.+?)\s+состо(?:ит|ят)\s+из\s*:?\s*(?P<list>.+)"),
    re.compile(r"(?P<whole>.+?)\s+включа(?:ет|ют)(?:\s+в\s+себя)?\s*:?\s*(?P<list>.+)"),
]
# триггер перечня зависимостей → (параметр, субъект характеристики: "product" | id-подсказка из текста)
DEP_LIST_TRIGGERS = [
    (re.compile(r"контактиру\w+\s+с\s+перекачиваем|с\s+перекачиваем\w+\s+\w+\s+контактиру|в\s+контакте\s+с\s+перекачиваем"),
     "medium_temperature"),
    (re.compile(r"границ\w+\s+(?:рабочего\s+)?давлени|под\s+рабочим\s+давлени"), "working_pressure"),
    (re.compile(r"воздействи\w+\s+температур\w+\s+окружающ|температур\w+\s+окружающ\w+\s+\w+\s+воздейству"), "ambient_temperature"),
    (re.compile(r"(?:мощност\w+|крутящ\w+\s+момент\w*)\s+(?:от\s+)?электродвигател\w+\s+переда"), "power"),
    (re.compile(r"источник\w+\s+вибраци|влия\w+\s+на\s+(?:виброскорост|вибраци)|на\s+(?:виброскорост|вибраци)\w*\s+(?:\w+\s+)?влия"),
     "vibration_velocity"),
    (re.compile(r"вклад\w*\s+в\s+масс|масс\w+\s+агрегат\w*\s+(?:в\s+основном\s+)?определя"), "mass"),
]
CONTRIBUTION_PARAMS = {"mass"}   # «вклад в массу»: характеристика зависит от компонента, а не наоборот
LOAD_RE = re.compile(r"(?P<who>.+?)\s+воспринима\w+\s+нагрузк\w*\s+от\s+(?P<src>.+)")
LOAD_REV_RE = re.compile(r"нагрузк\w*\s+от\s+(?P<src>.+?)\s+воспринима\w+\s+(?P<who>.+)")
DEP_SINGLE_RE = re.compile(r"(?P<who>.+?)\s+(?:завис\w+\s+от|определя\w+)\s+(?P<what>.+)")
MONITOR_RE = re.compile(r"(?P<who>.+?)\s+(?:контролиру\w+|измеря\w+|отслежива\w+)\s+(?P<what>.+)")
DERIVED_RE = re.compile(r"(?P<k>\d+(?:,\d+)?)\s+(?:от\s+)?(?:величины\s+)?$")

# Веса связей по умолчанию (используются анализом изменений; калибруются в экспериментах)
DEFAULT_WEIGHTS = {
    RelationType.CONTAINS: 0.9, RelationType.DEPENDS_ON: 0.9, RelationType.USES_MATERIAL: 0.8,
    RelationType.DERIVED_FROM: 1.0, RelationType.VERIFIED_BY: 1.0, RelationType.DOCUMENTED_IN: 1.0,
    RelationType.CONSTRAINS: 1.0, RelationType.CHARACTERIZES: 1.0, RelationType.SUPERSEDES: 1.0,
    RelationType.AFFECTS: 1.0,
}


@dataclass
class ParsedInput:
    document: Document
    fragments: list[Fragment]
    header_lines: list[str] = field(default_factory=list)


def ev(frag: Fragment, start: int = 0, end: int | None = None, method=EvidenceMethod.RULE, rule: str = "",
       conf: float = 0.9) -> Evidence:
    end = len(frag.text) if end is None else end
    c = conf * (frag.ocr_confidence if frag.ocr and frag.ocr_confidence else 1.0)
    return Evidence(document_id=frag.document_id, fragment_id=frag.id, page=frag.page, locator=frag.locator,
                    bbox=frag.bbox, char_start=start, char_end=end, quote=frag.text[start:end], method=method,
                    rule=rule, confidence=round(c, 3))


def comp_kind(designation: str) -> EntityType:
    parts = designation.split(".")
    if parts[-2:] == ["00", "000"]:
        return EntityType.PRODUCT
    if parts[-1] == "000":
        return EntityType.ASSEMBLY
    return EntityType.COMPONENT


def mat_key(name: str) -> str:
    return "mat:" + "_".join(lemmas_of(name))


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


class Extractor:
    def __init__(self, project_id: str = "default"):
        self.kb = KnowledgeBase(project_id=project_id)
        self.index = MentionIndex()
        self.kinds: dict[str, str] = {}
        self.by_designation: dict[str, str] = {}
        self.explicit_parent: set[str] = set()
        self.pending_refs: list[tuple[str, list[str], Evidence]] = []
        self.product_id: str | None = None

    # ------------------------------------------------------------ сущности
    def _entity(self, eid, etype, name, evidence: Evidence | None, designation=None, attrs=None, conf=0.9) -> Entity:
        e = self.kb.add_entity(Entity(id=eid, type=etype, name=name, designation=designation, attrs=attrs or {},
                                      evidence=[evidence] if evidence else [], confidence=conf))
        self.kinds[eid] = e.type.value
        return e

    def _material(self, name: str, evidence: Evidence) -> str:
        name = cap(name.strip())
        mid = mat_key(name)
        if mid not in self.kb.entities:
            self.index.add(mid, name)
        self._entity(mid, EntityType.MATERIAL, name, evidence)
        return mid

    def _rel(self, rtype: RelationType, s: str, t: str, evidence: Evidence, **attrs):
        if s == t:
            return
        self.kb.add_relation(Relation(id="", type=rtype, source=s, target=t, weight=DEFAULT_WEIGHTS.get(rtype, 1.0),
                                      attrs=attrs, evidence=[evidence]))

    def _constraint(self, subject: str, param: str, evidence: Evidence) -> str:
        cid = f"con:{subject}:{param}"
        subj = self.kb.entities.get(subject)
        self._entity(cid, EntityType.CONSTRAINT, f"{PARAM_RU.get(param, param)} — {subj.name if subj else subject}", None,
                     attrs={"subject_id": subject, "parameter": param})
        self._rel(RelationType.CHARACTERIZES, cid, subject, evidence)
        return cid

    # ------------------------------------------------------------ этап 1–2
    def register(self, inputs: list[ParsedInput]):
        for pi in inputs:
            d = pi.document
            des, code, dtype, conf, title = classify(pi.header_lines, d.filename)
            d.code, d.doc_type, d.doc_type_confidence = code, dtype, conf
            d.title = d.title or title
            d.metadata["subject_designation"] = des
            self.kb.documents[d.id] = d
            for f in pi.fragments:
                if INJECTION_RE.search(f.text):
                    f.flags.append("suspected_injection")
                self.kb.fragments[f.id] = f
            self._entity(d.id, EntityType.DOCUMENT, d.title or d.filename, None, designation=code,
                         attrs={"doc_type": dtype, "filename": d.filename})
        # реестр компонентов из спецификаций
        for pi in inputs:
            if pi.document.doc_type != "Specification":
                continue
            for f in pi.fragments:
                if f.kind != "table_row" or not f.header:
                    continue
                row = dict(zip([h.lower() for h in f.header], f.cells or []))
                des, name = row.get("обозначение", "").strip(), row.get("наименование", "").strip()
                if not DESIG_RE.match(des) or not name:
                    continue
                cid = f"cmp:{des}"
                kind = comp_kind(des)
                self._entity(cid, kind, name, ev(f, rule="spec_row", method=EvidenceMethod.TABLE), designation=des)
                self.by_designation[des] = cid
                self.index.add_with_head_alias(cid, name)
                if kind == EntityType.PRODUCT:
                    self.product_id = self.product_id or cid
                    self.index.add(cid, "агрегат", alias=True)
                for mname in filter(None, (x.strip() for x in row.get("материал", "").split(";"))):
                    mid = self._material(mname, ev(f, rule="spec_material", method=EvidenceMethod.TABLE))
                    self._rel(RelationType.USES_MATERIAL, cid, mid, ev(f, rule="spec_material", method=EvidenceMethod.TABLE))
        # материалы из ведомостей материалов (до основного прохода — чтобы находить их упоминания)
        for pi in inputs:
            for f in pi.fragments:
                if f.kind == "table_row" and f.header and any("материал" == h.lower().strip() for h in f.header):
                    row = dict(zip([h.lower().strip() for h in f.header], f.cells or []))
                    for mname in filter(None, (x.strip() for x in row.get("материал", "").split(";"))):
                        self._material(mname, ev(f, rule="material_table", method=EvidenceMethod.TABLE))
        # субъект документа по обозначению
        for d in self.kb.documents.values():
            des = d.metadata.get("subject_designation")
            d.subject_id = self.by_designation.get(des) or self.product_id

    # ------------------------------------------------------------ этап 3
    def extract(self, inputs: list[ParsedInput]):
        for pi in inputs:
            d = self.kb.documents[pi.document.id]
            current_test = None
            for f in pi.fragments:
                if "suspected_injection" in f.flags:
                    continue            # текст-инструкция не используется как источник фактов
                mentions = self.index.find(f.text)
                for m in mentions:
                    self._rel(RelationType.DOCUMENTED_IN, m.entity_id, d.id, ev(f, m.start, m.end, rule="mention",
                                                                                conf=0.75 if m.alias else 0.9))
                for sm in STANDARD_RE.finditer(f.text):
                    sid = "std:" + re.sub(r"\s+", " ", sm.group(0))
                    self._entity(sid, EntityType.STANDARD, re.sub(r"\s+", " ", sm.group(0)), ev(f, *sm.span(), rule="standard"))
                    self._rel(RelationType.DOCUMENTED_IN, sid, d.id, ev(f, *sm.span(), rule="standard"))
                if d.doc_type in ("TestProgram", "TestReport"):
                    current_test = self._tests(f, d, current_test)
                if d.doc_type == "ChangeLog":
                    self._change_row(f, d)
                    continue
                if d.doc_type == "TestReport":
                    continue            # измеренные значения — результаты, а не требования
                if f.kind == "table_row" and f.header:
                    self._table_row(f, d, mentions)
                    continue
                self._relations(f, d, mentions)
                for c in extract_requirements(f.text, mentions, self.kinds, d.subject_id):
                    self._add_req(f, d, c)
            d.status = "extracted"
            d.processed_at = now()

    def _add_req(self, f: Fragment, d: Document, c, method=EvidenceMethod.RULE, rule="requirement_rule"):
        if c.subject_id is None:
            return
        if c.kind == "capability" and c.operator == "=":
            c.operator = "<="          # предельная возможность, записанная одним числом, — верхняя граница
        rid = "req:" + stable_id(d.id, c.subject_id, c.parameter, c.kind, c.operator, c.value, c.low, c.high)
        s, e = sentences_span(f.text, c.start, c.end)
        evd = ev(f, s, e, method=method, rule=rule, conf=c.confidence)
        if rid in self.kb.requirements:      # то же требование повторно в том же документе — объединяем основания
            self.kb.requirements[rid].evidence.append(evd)
            return
        section = f.section
        if section is None and f.heading_path:
            m = re.match(r"\s*((?:\d+\.)*\d+|[TТ]\d{2})\s", f.heading_path[-1])
            section = m.group(1).replace("Т", "T") if m else None
        r = Requirement(id=rid, subject_id=c.subject_id, parameter=c.parameter, dimension=c.dimension, kind=c.kind,
                        operator=c.operator, value=c.value, low=c.low, high=c.high, unit=c.unit,
                        unit_original=c.unit_original, value_original=c.value_original, section=section,
                        text=f.text[s:e], document_id=d.id, evidence=[evd], confidence=evd.confidence)
        self.kb.requirements[rid] = r
        self._entity(rid, EntityType.REQUIREMENT, f.text[s:e][:120], evd,
                     attrs={"parameter": c.parameter, "kind": c.kind, "section": f.section})
        self._rel(RelationType.DOCUMENTED_IN, rid, d.id, evd)
        cid = self._constraint(c.subject_id, c.parameter, evd)
        self._rel(RelationType.CONSTRAINS, rid, cid, evd)

    # ------------------------------------------------------------ таблицы
    def _table_row(self, f: Fragment, d: Document, mentions):
        hdr = [h.strip() for h in f.header]
        row = dict(zip([h.lower() for h in hdr], f.cells or []))
        mids = [mat_key(x.strip()) for x in row.get("материал", "").split(";") if x.strip()]
        mid = mids[0] if len(mids) == 1 else None
        comp = next((m.entity_id for m in mentions if self.kinds.get(m.entity_id) in ("Product", "Assembly", "Component")), None)
        for m_ in mids if comp else []:
            self._rel(RelationType.USES_MATERIAL, comp, m_, ev(f, rule="material_table", method=EvidenceMethod.TABLE))
        subject = mid or comp or d.subject_id
        for h, cell in zip(hdr, f.cells or []):
            got = extract_from_table_cell(h, cell)
            if not got:
                continue
            key, dim, v, lo, hi, op = got
            from eis.extraction.requirements import ReqCandidate
            pos = f.text.find(cell)
            c = ReqCandidate(key, dim, "capability" if key == "material_temperature" else "demand", op, v, lo, hi,
                             CANONICAL[dim], h, cell, max(pos, 0), max(pos, 0) + len(cell), subject, True, 0.9)
            self._add_req(f, d, c, method=EvidenceMethod.TABLE, rule="table_cell")

    # ------------------------------------------------------------ испытания
    def _tests(self, f: Fragment, d: Document, current):
        cells = dict(zip([h.lower() for h in (f.header or [])], f.cells or []))
        m = TEST_CODE_RE.match(f.text) if f.kind in ("heading", "paragraph", "line") else None
        code, name = (m.group(1).replace("Т", "T"), m.group(2)) if m else (None, None)
        if f.kind == "table_row" and TEST_CODE_RE.match((cells.get("испытание", "") + " x")):
            code, name = cells["испытание"].strip().replace("Т", "T"), cells.get("наименование", "")
        if code:
            tid = f"test:{code}"
            attrs = {"code": code}
            if cells.get("результат"):
                attrs |= {"result": cells["результат"], "conclusion": cells.get("заключение", "")}
            self._entity(tid, EntityType.TEST, name or code, ev(f, rule="test"), designation=code, attrs=attrs)
            if attrs.get("result"):
                self.kb.entities[tid].attrs.update(attrs)
            self._rel(RelationType.DOCUMENTED_IN, tid, d.id, ev(f, rule="test"))
            current = tid
        for rm in TZ_REF_RE.finditer(f.text):
            if current:
                secs = [s.strip() for s in rm.group(1).split(",")]
                self.pending_refs.append((current, secs, ev(f, *rm.span(), rule="tz_reference")))
        return current

    # ------------------------------------------------------------ журнал изменений
    def _change_row(self, f: Fragment, d: Document):
        if f.kind != "table_row" or not f.header:
            return
        row = dict(zip([h.lower().strip() for h in f.header], [c.strip() for c in f.cells or []]))
        cid = row.get("извещение")
        if not cid:
            return
        e = ev(f, rule="changelog_row", method=EvidenceMethod.TABLE)
        text = row.get("содержание изменения", "")
        attrs = {"date": row.get("дата"), "document": row.get("документ"), "text": text}
        m = re.search(r"\sс\s+(\S+)\s*(\S*)\s+на\s+(\S+)", text)
        if m:
            attrs |= {"old_value": m.group(1), "new_value": m.group(3)}
        self._entity(f"chg:{cid}", EntityType.CHANGE, f"{cid}: {text[:80]}", e, designation=cid, attrs=attrs)
        self._rel(RelationType.DOCUMENTED_IN, f"chg:{cid}", d.id, e)
        doc = row.get("документ")
        if doc and row.get("редакция"):
            new, old = f"docver:{doc} {row['редакция']}", f"docver:{doc} {row.get('заменяет', '')}".strip()
            self._entity(new, EntityType.DOCUMENT, f"{doc} {row['редакция']}", e, designation=doc)
            self._entity(old, EntityType.DOCUMENT, f"{doc} {row.get('заменяет', '')}", e, designation=doc)
            self._rel(RelationType.SUPERSEDES, new, old, e, change=cid)
            target = next((x.id for x in self.kb.documents.values() if x.code == doc), None)
            if target:
                self._rel(RelationType.AFFECTS, f"chg:{cid}", target, e)

    # ------------------------------------------------------------ связи из текста
    def _comp_mentions(self, mentions, lo=0, hi=10**9):
        return [m for m in mentions if lo <= m.start and m.end <= hi
                and self.kinds.get(m.entity_id) in ("Product", "Assembly", "Component")]

    def _relations(self, f: Fragment, d: Document, mentions):
        text = f.text
        lc = text.lower().replace("ё", "е")
        for s0, s1 in sentences(text):
            sl = lc[s0:s1]
            # состав
            for rx in CONTAINS_RES:
                m = rx.search(sl)
                if not m:
                    continue
                whole = self._comp_mentions(mentions, s0 + m.start("whole"), s0 + m.end("whole"))
                parts = self._comp_mentions(mentions, s0 + m.start("list"), s1)
                if whole and parts:
                    parent = whole[-1].entity_id if "в состав" in sl[:12] else whole[0].entity_id
                    for p in parts:
                        self._rel(RelationType.CONTAINS, parent, p.entity_id, ev(f, s0, s1, rule="contains_list"))
                        self.explicit_parent.add(p.entity_id)
                break
            # перечни зависимостей
            hit_list = False
            for rx, param in DEP_LIST_TRIGGERS:
                tm = rx.search(sl)
                colon = sl.find(":")
                if tm and colon > 0:
                    hit_list = True
                    subj = self.product_id
                    if param == "power":
                        subj = next((x.entity_id for x in self._comp_mentions(mentions, s0, s0 + colon)), subj)
                    cid = self._constraint(subj, param, ev(f, s0, s1, rule="dependency_list"))
                    for p in self._comp_mentions(mentions, s0 + colon, s1):
                        a, b_ = (cid, p.entity_id) if param in CONTRIBUTION_PARAMS else (p.entity_id, cid)
                        self._rel(RelationType.DEPENDS_ON, a, b_, ev(f, s0, s1, rule="dependency_list"), basis=param)
                    break
            lm = LOAD_RE.search(sl) or LOAD_REV_RE.search(sl)
            if lm and not hit_list:
                hit_list = True
                who = self._comp_mentions(mentions, s0 + lm.start("who"), s0 + lm.end("who"))
                srcs = self._comp_mentions(mentions, s0 + lm.start("src"), s0 + lm.end("src"))
                for w in who[:1]:
                    for x in srcs:
                        self._rel(RelationType.DEPENDS_ON, w.entity_id, x.entity_id, ev(f, s0, s1, rule="load_bearing"),
                                  basis="load_bearing")
            if not hit_list:
                for rx, rule in ((DEP_SINGLE_RE, "dependency_single"), (MONITOR_RE, "monitoring")):
                    m = rx.search(sl)
                    if not m:
                        continue
                    who = self._comp_mentions(mentions, s0 + m.start("who"), s0 + m.end("who"))
                    params = find_params(sl[m.start("what"):])
                    if who and params:
                        what_m = self._comp_mentions(mentions, s0 + m.start("what"), s1)
                        subj = what_m[0].entity_id if what_m else self.product_id
                        cid = self._constraint(subj, params[0].key, ev(f, s0, s1, rule=rule))
                        self._rel(RelationType.DEPENDS_ON, who[0].entity_id, cid, ev(f, s0, s1, rule=rule), basis=rule)
                        break
            # производные величины: «A принимается равным 1,5 B»
            for part in re.split(r";", sl):
                off = s0 + lc[s0:s1].find(part)
                ps = find_params(part)
                if len(ps) >= 2:
                    a, b = ps[0], ps[1]
                    mid = DERIVED_RE.search(part[a.end:b.start])
                    if mid:
                        subj_a = next((x.entity_id for x in self._comp_mentions(mentions, off + a.start, off + b.start)),
                                      self.product_id)
                        e = ev(f, off, off + len(part), rule="derived_value")
                        ca, cb = self._constraint(subj_a, a.key, e), self._constraint(self.product_id, b.key, e)
                        self._rel(RelationType.DERIVED_FROM, ca, cb, e, factor=float(mid.group("k").replace(",", ".")))
            # материалы
            for rx in (MADE_OF_RE, MATERIAL_OF_RE):
                for m in rx.finditer(text[s0:s1]):
                    mname = m.group(m.lastindex)
                    toks = [t for t, _, _ in tokens(mname)]
                    norm = " ".join([cap(lemma(toks[0]))] + toks[1:])
                    mid = mat_key(norm)
                    if mid not in self.kb.entities:
                        mid = self._material(norm, ev(f, s0 + m.start(), s0 + m.end(), rule="made_of"))
                    self._rel(RelationType.DOCUMENTED_IN, mid, d.id, ev(f, s0 + m.start(), s0 + m.end(), rule="made_of"))
                    comps = self._comp_mentions(mentions, s0, s1)
                    if comps:
                        self._rel(RelationType.USES_MATERIAL, comps[0].entity_id, mid,
                                  ev(f, s0, s1, rule="made_of"))

    # ------------------------------------------------------------ этап 4
    def link(self):
        tz = [d for d in self.kb.documents.values() if d.doc_type == "TechnicalSpecification"]
        for tid, secs, e in self.pending_refs:
            for r in self.kb.requirements.values():
                if any(r.document_id == d.id for d in tz) and r.section in secs:
                    self._rel(RelationType.VERIFIED_BY, r.id, tid, e)
        # состав по обозначениям: деталь xx.yy.zzz ∈ сборка xx.yy.000; сборка ∈ изделие, если иное не указано
        for des, cid in self.by_designation.items():
            parts = des.split(".")
            if comp_kind(des) == EntityType.COMPONENT:
                parent = self.by_designation.get(".".join(parts[:-1] + ["000"]))
            elif comp_kind(des) == EntityType.ASSEMBLY:
                parent = None if cid in self.explicit_parent else self.by_designation.get(".".join([parts[0], "00", "000"]))
            else:
                parent = None
            if parent and not any(r.type == RelationType.CONTAINS and r.target == cid and r.source != parent
                                  for r in self.kb.relations.values()):
                src = self.kb.entities[cid].evidence[0]
                self._rel(RelationType.CONTAINS, parent, cid, src.model_copy(update={"rule": "designation_hierarchy",
                                                                                      "method": EvidenceMethod.GRAPH_RULE}))
        return self.kb


def sentences_span(text: str, start: int, end: int) -> tuple[int, int]:
    for s, e in sentences(text):
        if s <= start < e:
            return s, max(e, end)
    return start, end


def run_pipeline(inputs: list[ParsedInput], project_id: str = "default") -> KnowledgeBase:
    x = Extractor(project_id)
    x.register(inputs)
    x.extract(inputs)
    return x.link()

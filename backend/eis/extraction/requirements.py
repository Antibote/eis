"""Rule-based извлечение технических требований из предложения или строки таблицы."""
from __future__ import annotations

import re
from dataclasses import dataclass

from eis.extraction.lexicon import OPERATOR_CUES, ParamHit, find_params, kind_of
from eis.extraction.mentions import Mention
from eis.extraction.units import CANONICAL, NUM, NUM_RE, match_unit, parse_number, to_canonical, unit_in

IP_RE = re.compile(r"\bIP\s?(\d)(\d|X)\b", re.IGNORECASE)
SENT_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[А-ЯЁA-Z«\"])|\n+")


@dataclass
class ReqCandidate:
    parameter: str
    dimension: str
    kind: str
    operator: str
    value: float | str | None
    low: float | None
    high: float | None
    unit: str
    unit_original: str
    value_original: str
    start: int            # смещения цитаты внутри исходного текста
    end: int
    subject_id: str | None
    subject_explicit: bool
    confidence: float


def sentences(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for m in SENT_SPLIT.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def _resolve_measurement(sent_lc: str, dim: str) -> str | None:
    """«Диапазон измерения» → контролируемый параметр по размерности единицы."""
    if dim == "pressure":
        return "working_pressure"
    if dim == "temperature":
        if "подшипник" in sent_lc:
            return "bearing_temperature"
        if "окружающ" in sent_lc:
            return "ambient_temperature"
        return "medium_temperature"
    return None


def _operator(segment_lc: str) -> str:
    for op, rx in OPERATOR_CUES:
        if op != "range" and rx.search(segment_lc):
            return op
    return "="


def _subject(mentions: list[Mention], text_lc: str, entity_kinds: dict[str, str]) -> tuple[str | None, bool]:
    comps = [m for m in mentions if entity_kinds.get(m.entity_id) in ("Product", "Assembly", "Component")]
    if not comps:
        return None, False
    for m in comps:   # приоритет: упоминание сразу после «для»
        if re.search(r"(?:^|\s)для\s+$", text_lc[max(0, m.start - 6):m.start]):
            return m.entity_id, True
    return comps[0].entity_id, True


def extract_requirements(text: str, mentions: list[Mention], entity_kinds: dict[str, str],
                         default_subject: str | None) -> list[ReqCandidate]:
    out: list[ReqCandidate] = []
    lc = text.lower().replace("ё", "е")
    for s0, s1 in sentences(text):
        sent, sent_lc = text[s0:s1], lc[s0:s1]
        smentions = [Mention(m.entity_id, m.start - s0, m.end - s0, m.text, m.alias) for m in mentions
                     if m.start >= s0 and m.end <= s1]
        hits = [h for h in find_params(sent_lc)
                if not any(m.start <= h.start and h.end <= m.end for m in smentions)]
        prev_end = 0
        for i, h in enumerate(hits):
            region_end = hits[i + 1].start if i + 1 < len(hits) else len(sent)
            cand = _value_after(sent, sent_lc, h, region_end, prev_end)
            if cand is None:
                continue
            prev_end = cand.end
            if h.key == "measurement_range":
                key = _resolve_measurement(sent_lc, cand.dimension)
                if key is None:
                    continue
                cand.parameter = key
            subj, explicit = _subject(smentions, sent_lc, entity_kinds)
            cand.subject_id, cand.subject_explicit = (subj, True) if subj else (default_subject, False)
            if not explicit:
                cand.confidence -= 0.1
            cand.start += s0
            cand.end += s0
            out.append(cand)
    return out


def _value_after(sent: str, sent_lc: str, h: ParamHit, region_end: int, seg_start: int) -> ReqCandidate | None:
    region = sent_lc[h.end:region_end]
    kind = kind_of(sent_lc, h.hint)
    # степень защиты (IP-код)
    if h.dimension == "ip":
        m = IP_RE.search(sent[h.end:region_end])
        if not m:
            return None
        op = _operator(sent_lc[seg_start:h.end + m.start()])
        return ReqCandidate(h.key, "ip", kind, op if op != "<=" else "=", m.group(0).upper().replace(" ", ""), None, None,
                            "", "", m.group(0), h.start, h.end + m.end(), None, False, 0.9)
    # диапазон
    for op, rx in OPERATOR_CUES:
        if op != "range":
            continue
        m = rx.search(region)
        if m:
            u = match_unit(sent, h.end + m.end("hi"))
            dim = u.dimension if u else None
            if u is None or (h.dimension != "*" and dim != h.dimension):
                continue
            lo, hi = to_canonical(parse_number(m.group("lo")), u), to_canonical(parse_number(m.group("hi")), u)
            return ReqCandidate(h.key, dim, kind, "range", None, min(lo, hi), max(lo, hi), CANONICAL[dim], u.text,
                                sent[h.end + m.start():u.end], h.start, u.end, None, False, 0.9)
    # одиночное значение
    for m in NUM_RE.finditer(region):
        abs_end = h.end + m.end()
        u = match_unit(sent, abs_end)
        if u is None:
            continue
        if h.dimension != "*" and u.dimension != h.dimension:
            continue
        if h.dimension == "*" and u.dimension not in ("pressure", "temperature"):
            continue
        v = to_canonical(parse_number(m.group(0)), u)
        op = _operator(sent_lc[seg_start:h.end + m.start()])
        conf = 0.9 if op != "=" or kind in ("nominal", "setpoint") or "составл" in region or "—" in region else 0.8
        return ReqCandidate(h.key, u.dimension, kind, op, v, None, None, CANONICAL[u.dimension], u.text,
                            sent[h.end + m.start():u.end], h.start, u.end, None, False, conf)
    return None


def extract_from_table_cell(header: str, cell: str) -> tuple[str, str, float | None, float | None, float | None, str] | None:
    """Ячейка таблицы, заголовок которой называет параметр и единицу («Температура применения, °C»)."""
    hl = header.lower()
    hits = find_params(hl)
    u = unit_in(header)
    if not hits or u is None or not cell.strip():
        return None
    h = hits[0]
    for op, rx in OPERATOR_CUES:
        if op == "range":
            m = rx.search(cell.lower())
            if m:
                lo, hi = to_canonical(parse_number(m.group("lo")), u), to_canonical(parse_number(m.group("hi")), u)
                return h.key, u.dimension, None, min(lo, hi), max(lo, hi), "range"
    m = re.search(NUM, cell)
    if m:
        return h.key, u.dimension, to_canonical(parse_number(m.group(0)), u), None, None, _operator(cell.lower())
    return None

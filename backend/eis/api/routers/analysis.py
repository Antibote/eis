"""Граф, требования, противоречия, анализ изменений, отчёты, поиск, ассистент."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from eis.api import state
from eis.api.deps import CurrentUser, project_access
from eis.db.models import ContradictionReview, ImpactReportRow
from eis.db.session import session
from eis.domain.models import stable_id
from eis.domain.results import ImpactReport
from eis.llm.providers import provider_from_env
from eis.services.assistant import Assistant
from eis.services.change_request import parse_change
from eis.services.contradictions import PARAM_RU
from eis.services.impact import ImpactAnalyzer, ImpactSettings
from eis.services.reporting import contradiction_sections, impact_sections, to_docx, to_pdf

router = APIRouter(prefix="/api/projects/{pid}", tags=["analysis"])


# ------------------------------------------------------------------ граф и сущности
@router.get("/graph")
def graph(pid: str, node_types: str | None = None, edge_types: str | None = None, focus: str | None = None,
          depth: int = 2, user: CurrentUser = Depends(project_access())):
    ws = state.get_ws(pid)
    g = ws.graph
    nt = set(node_types.split(",")) if node_types else None
    et = set(edge_types.split(",")) if edge_types else None
    ids = None
    if focus:
        ids, frontier = {focus}, [focus]
        for _ in range(depth):
            nxt = []
            for n in frontier:
                for e in g.out_edges(n) + g.in_edges(n):
                    m = e.target if e.source == n else e.source
                    if m not in ids:
                        ids.add(m)
                        nxt.append(m)
            frontier = nxt
    data = g.subgraph_json(ids)
    if nt:
        keep = {n["id"] for n in data["nodes"] if n["type"] in nt}
        data["nodes"] = [n for n in data["nodes"] if n["id"] in keep]
        data["edges"] = [e for e in data["edges"] if e["source"] in keep and e["target"] in keep]
    if et:
        data["edges"] = [e for e in data["edges"] if e["type"] in et]
    return data | {"stats": g.stats()}


@router.get("/entities/{eid:path}")
def entity(pid: str, eid: str, user: CurrentUser = Depends(project_access())):
    ws = state.get_ws(pid)
    e = ws.kb.entities.get(eid)
    if not e:
        raise HTTPException(404, "Сущность не найдена")

    def rel(r, other):
        o = ws.kb.entities.get(other)
        return {"id": r.id, "type": r.type.value, "other": other, "other_name": o.name if o else other,
                "other_type": o.type.value if o else None, "weight": r.weight, "attrs": r.attrs,
                "evidence": [ws.evidence_context(x) for x in r.evidence[:3]]}
    out = [rel(r, r.target) for r in ws.graph.out_edges(eid)]
    inc = [rel(r, r.source) for r in ws.graph.in_edges(eid)]
    reqs = [r.model_dump(mode="json") for r in ws.kb.requirements.values() if r.subject_id == eid]
    return {"entity": e.model_dump(mode="json"), "outgoing": out, "incoming": inc, "requirements": reqs,
            "evidence": [ws.evidence_context(x) for x in e.evidence[:5]]}


@router.get("/requirements")
def requirements(pid: str, subject: str | None = None, parameter: str | None = None, document: str | None = None,
                 user: CurrentUser = Depends(project_access())):
    ws = state.get_ws(pid)
    out = []
    for r in ws.kb.requirements.values():
        if (subject and r.subject_id != subject) or (parameter and r.parameter != parameter) or \
                (document and r.document_id != document):
            continue
        d = ws.kb.documents.get(r.document_id)
        s = ws.kb.entities.get(r.subject_id)
        out.append(r.model_dump(mode="json") | {"subject_name": s.name if s else r.subject_id,
                                                "parameter_ru": PARAM_RU.get(r.parameter, r.parameter),
                                                "document_code": d.code if d else None})
    return sorted(out, key=lambda r: (r["document_code"] or "", r["section"] or ""))


@router.get("/subjects")
def subjects(pid: str, user: CurrentUser = Depends(project_access())):
    """Изделия/сборки/компоненты, у которых есть требования, — для выбора на странице анализа изменений."""
    ws = state.get_ws(pid)
    subj = {}
    for r in ws.kb.requirements.values():
        e = ws.kb.entities.get(r.subject_id)
        if e and e.type.value in ("Product", "Assembly", "Component"):
            subj.setdefault(e.id, {"id": e.id, "name": e.name, "type": e.type.value, "designation": e.designation, "count": 0})
            subj[e.id]["count"] += 1
    return sorted(subj.values(), key=lambda x: (x["type"] != "Product", x["designation"] or ""))


# ------------------------------------------------------------------ противоречия
class ReviewIn(BaseModel):
    status: str
    comment: str = ""


def _reviews(pid):
    with session() as s:
        rows = s.scalars(select(ContradictionReview).where(ContradictionReview.project_id == pid)
                         .order_by(ContradictionReview.id)).all()
    return {r.contradiction_id: {"status": r.status, "comment": r.comment, "user": r.user,
                                 "at": r.created_at.isoformat()} for r in rows}


@router.get("/contradictions")
def contradictions(pid: str, user: CurrentUser = Depends(project_access())):
    ws = state.get_ws(pid)
    rv = _reviews(pid)
    out = []
    for c in list(ws.contradictions) + list(ws.semantic):
        d = c.model_dump(mode="json")
        d["evidence"] = [ws.evidence_context(e) for e in c.evidence]
        d["entity_names"] = [ws.kb.entities[e].name if e in ws.kb.entities else e for e in c.entities]
        d["review"] = rv.get(c.id)
        out.append(d)
    return out


@router.post("/contradictions/semantic")
def run_semantic(pid: str, user: CurrentUser = Depends(project_access("engineer"))):
    """Уровень 2: семантическое сравнение пар фрагментов локальной LLM (статус находок — «потенциально»)."""
    from eis.services.semantic import semantic_contradictions
    llm = provider_from_env()
    if not llm.available or (not llm.local and not user.allow_external_llm):
        raise HTTPException(409, "Языковая модель не подключена или передача данных внешней модели не разрешена")
    ws = state.get_ws(pid)
    found, log = semantic_contradictions(ws.kb, llm, ws.retriever.embedder)
    ws.semantic = found
    state.audit(user.username, "semantic_contradictions", pid, pairs=len(log), found=len(found), llm=llm.name)
    return {"pairs": len(log), "found": len(found)}


@router.patch("/contradictions/{cid}")
def review(pid: str, cid: str, body: ReviewIn, user: CurrentUser = Depends(project_access("engineer"))):
    if body.status not in ("confirmed_by_engineer", "rejected", "new"):
        raise HTTPException(400, "Недопустимый статус")
    with session() as s:
        s.add(ContradictionReview(project_id=pid, contradiction_id=cid, status=body.status, comment=body.comment,
                                  user=user.username))
    state.audit(user.username, "review_contradiction", pid, contradiction=cid, status=body.status)
    return {"ok": True}


@router.get("/contradictions/export")
def export_contradictions(pid: str, fmt: str = Query("docx", pattern="^(docx|pdf)$"),
                          user: CurrentUser = Depends(project_access())):
    ws = state.get_ws(pid)
    secs = contradiction_sections(ws.contradictions, ws.kb)
    title = "Реестр противоречий в конструкторской документации"
    data = to_docx(title, secs) if fmt == "docx" else to_pdf(title, secs)
    return _file(data, f"contradictions.{fmt}")


# ------------------------------------------------------------------ анализ изменений
class ImpactIn(BaseModel):
    requirement_id: str | None = None
    text: str | None = None
    new_value: float | None = None
    new_low: float | None = None
    new_high: float | None = None
    unit: str | None = None
    max_depth: int = 3
    use_physics: bool = True


@router.post("/impact")
def impact(pid: str, body: ImpactIn, user: CurrentUser = Depends(project_access("engineer"))):
    ws = state.get_ws(pid)
    rid, nv, lo, hi, unit = body.requirement_id, body.new_value, body.new_low, body.new_high, body.unit
    if body.text and not rid:
        try:
            pc = parse_change(body.text, ws.kb, ws.graph, ws.mentions)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        rid, nv, lo, hi, unit = pc.requirement.id, pc.new_value, pc.new_low, pc.new_high, None
    if not rid or rid not in ws.kb.requirements:
        raise HTTPException(404, "Требование не найдено")
    try:
        rep = ImpactAnalyzer(ws.kb, ws.graph, ImpactSettings(max_depth=body.max_depth, use_physics=body.use_physics)) \
            .analyze(rid, new_value=nv, new_low=lo, new_high=hi, unit=unit)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    rep_id = "imp:" + stable_id(pid, rid, rep.new, rep.created_at.isoformat())
    summary = f"{PARAM_RU.get(rep.parameter, rep.parameter)}: {rep.old} → {rep.new}"
    with session() as s:
        s.add(ImpactReportRow(id=rep_id, project_id=pid, requirement_id=rid, summary=summary, data=rep.model_dump_json(),
                              user=user.username))
    state.audit(user.username, "impact_analysis", pid, report=rep_id, summary=summary)
    return _impact_json(ws, rep) | {"id": rep_id}


def _impact_json(ws, rep: ImpactReport) -> dict:
    d = rep.model_dump(mode="json")
    for it, src in zip(d["items"], rep.items):
        it["evidence"] = [ws.evidence_context(e) for e in src.evidence]
        it["path_names"] = [ws.kb.entities[s.node].name if s.node in ws.kb.entities else s.node for s in src.path]
    for dd, src in zip(d["documents"], rep.documents):
        dd["evidence"] = [ws.evidence_context(e) for e in src.evidence]
    for c, src in zip(d["conflicts_after_change"], rep.conflicts_after_change):
        c["evidence"] = [ws.evidence_context(e) for e in src.evidence]
    return d


@router.get("/impact")
def impact_list(pid: str, user: CurrentUser = Depends(project_access())):
    with session() as s:
        rows = s.scalars(select(ImpactReportRow).where(ImpactReportRow.project_id == pid)
                         .order_by(ImpactReportRow.created_at.desc()).limit(100)).all()
    return [{"id": r.id, "summary": r.summary, "user": r.user, "created_at": r.created_at.isoformat(),
             "requirement_id": r.requirement_id} for r in rows]


@router.get("/impact/{rep_id}")
def impact_get(pid: str, rep_id: str, user: CurrentUser = Depends(project_access())):
    rep = _load_report(pid, rep_id)
    return _impact_json(state.get_ws(pid), rep) | {"id": rep_id}


@router.get("/impact/{rep_id}/export")
def impact_export(pid: str, rep_id: str, fmt: str = Query("docx", pattern="^(docx|pdf)$"),
                  user: CurrentUser = Depends(project_access())):
    rep = _load_report(pid, rep_id)
    ws = state.get_ws(pid)
    secs = impact_sections(rep, ws.kb)
    title = "Отчёт об оценке последствий конструкторского изменения"
    state.audit(user.username, "export_report", pid, report=rep_id, fmt=fmt)
    return _file(to_docx(title, secs) if fmt == "docx" else to_pdf(title, secs), f"impact_report.{fmt}")


def _load_report(pid, rep_id) -> ImpactReport:
    with session() as s:
        row = s.get(ImpactReportRow, rep_id)
        if not row or row.project_id != pid:
            raise HTTPException(404, "Отчёт не найден")
        return ImpactReport.model_validate_json(row.data)


def _file(data: bytes, name: str) -> Response:
    mt = "application/pdf" if name.endswith(".pdf") else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(data, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------ поиск и ассистент
@router.get("/search")
def search(pid: str, q: str, mode: str = "hybrid", k: int = 10, doc_type: str | None = None, entity: str | None = None,
           parameter: str | None = None, user: CurrentUser = Depends(project_access())):
    ws = state.get_ws(pid)
    hits = ws.retriever.search(q, k=k, mode=mode, doc_types={doc_type} if doc_type else None, entity_id=entity,
                               parameter=parameter)
    return [{"fragment": h.fragment.model_dump(mode="json"), "score": h.score, "bm25_rank": h.bm25_rank,
             "vector_rank": h.vector_rank, "document_code": ws.kb.documents[h.fragment.document_id].code,
             "filename": ws.kb.documents[h.fragment.document_id].filename} for h in hits]


class AskIn(BaseModel):
    question: str
    context_entity: str | None = None


@router.post("/assistant")
def ask(pid: str, body: AskIn, user: CurrentUser = Depends(project_access())):
    ws = state.get_ws(pid)
    llm = provider_from_env()
    if not llm.local and not user.allow_external_llm:
        llm = None      # передача данных внешней модели требует явного разрешения для пользователя
    ans = Assistant(ws, llm).ask(body.question[:2000], body.context_entity)
    state.audit(user.username, "assistant", pid, intent=ans.intent, llm=ans.llm_used)
    return ans.__dict__ | {"llm_provider": llm.name if llm else "none"}

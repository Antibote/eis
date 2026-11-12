"""Документы, дашборд, проекты."""
from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from eis.api import state
from eis.api.deps import CurrentUser, current_user, project_access
from eis.db.models import AuditLog, ImpactReportRow, Project
from eis.db.session import session
from eis.security.files import MAX_FILE_MB, FileRejected, detect_format, validate_file

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/projects")
def projects(user: CurrentUser = Depends(current_user)):
    with session() as s:
        rows = s.scalars(select(Project)).all()
        return [{"id": p.id, "name": p.name, "description": p.description} for p in rows
                if user.role == "admin" or p.id in user.projects]


@router.post("/projects/{pid}/demo")
def load_demo(pid: str, user: CurrentUser = Depends(project_access("engineer"))):
    if pid != "demo":
        raise HTTPException(400, "Демонстрационный набор загружается только в проект demo")
    ws = state.load_demo(user.username)
    state.audit(user.username, "load_demo", pid, documents=len(ws.kb.documents))
    return {"documents": len(ws.kb.documents)}


@router.get("/projects/{pid}/dashboard")
def dashboard(pid: str, user: CurrentUser = Depends(project_access())):
    ws = state.get_ws(pid)
    kb = ws.kb
    ents = Counter(e.type.value for e in kb.entities.values())
    ctrs = ws.contradictions if kb.documents else []
    with session() as s:
        reports = s.scalars(select(ImpactReportRow).where(ImpactReportRow.project_id == pid)
                            .order_by(ImpactReportRow.created_at.desc()).limit(5)).all()
        events = s.scalars(select(AuditLog).where(AuditLog.project_id == pid).order_by(AuditLog.ts.desc()).limit(8)).all()
    return {
        "documents": len(kb.documents), "documents_failed": sum(d.status == "failed" for d in kb.documents.values()),
        "requirements": len(kb.requirements), "components": ents.get("Component", 0) + ents.get("Assembly", 0),
        "materials": ents.get("Material", 0), "tests": ents.get("Test", 0),
        "relations": len(kb.relations), "relations_by_type": dict(Counter(r.type.value for r in kb.relations.values())),
        "contradictions": len(ctrs), "contradictions_by_severity": dict(Counter(c.severity for c in ctrs)),
        "contradictions_by_status": dict(Counter(c.status for c in ctrs)),
        "requirements_by_kind": dict(Counter(r.kind for r in kb.requirements.values())),
        "recent_reports": [{"id": r.id, "summary": r.summary, "created_at": r.created_at.isoformat(), "user": r.user}
                           for r in reports],
        "recent_events": [{"ts": e.ts.isoformat(), "user": e.user, "action": e.action, "detail": e.detail} for e in events],
        "synthetic": any(d.is_synthetic for d in kb.documents.values()),
    }


@router.get("/projects/{pid}/documents")
def list_documents(pid: str, user: CurrentUser = Depends(project_access())):
    kb = state.get_ws(pid).kb
    out = []
    for d in kb.documents.values():
        out.append(d.model_dump(mode="json") | {
            "fragments": sum(1 for f in kb.fragments.values() if f.document_id == d.id),
            "requirements": sum(1 for r in kb.requirements.values() if r.document_id == d.id),
            "injection_flags": sum(1 for f in kb.fragments.values() if f.document_id == d.id and "suspected_injection" in f.flags)})
    return sorted(out, key=lambda x: x["filename"])


@router.post("/projects/{pid}/documents")
async def upload(pid: str, files: list[UploadFile] = File(...), user: CurrentUser = Depends(project_access("engineer"))):
    accepted, rejected = [], []
    for uf in files:
        try:
            fmt = detect_format(uf.filename or "")
            with tempfile.NamedTemporaryFile(delete=False, suffix="." + fmt) as tmp:
                size = 0
                while chunk := await uf.read(1 << 20):
                    size += len(chunk)
                    if size > MAX_FILE_MB * 2**20:
                        raise FileRejected(f"Файл больше {MAX_FILE_MB} МБ")
                    tmp.write(chunk)
            validate_file(Path(tmp.name), fmt)
            accepted.append(state.add_file(pid, Path(tmp.name), uf.filename, user.username))
        except FileRejected as e:
            rejected.append({"filename": uf.filename, "reason": str(e)})
        finally:
            if "tmp" in locals():
                Path(tmp.name).unlink(missing_ok=True)
    ws = state.rebuild(pid) if accepted else state.get_ws(pid)
    state.audit(user.username, "upload", pid, accepted=len(accepted), rejected=rejected)
    return {"accepted": accepted, "rejected": rejected, "documents": len(ws.kb.documents)}


@router.delete("/projects/{pid}/documents/{did}")
def delete_document(pid: str, did: str, user: CurrentUser = Depends(project_access("engineer"))):
    state.remove_document(pid, did)
    state.rebuild(pid)
    state.audit(user.username, "delete_document", pid, document=did)
    return {"ok": True}


@router.get("/projects/{pid}/documents/{did}")
def document_detail(pid: str, did: str, user: CurrentUser = Depends(project_access())):
    ws = state.get_ws(pid)
    kb = ws.kb
    d = kb.documents.get(did)
    if not d:
        raise HTTPException(404, "Документ не найден")
    frags = [f.model_dump(mode="json") for f in kb.fragments.values() if f.document_id == did]
    reqs = [r.model_dump(mode="json") for r in kb.requirements.values() if r.document_id == did]
    mentioned = sorted({r.source for r in kb.relations.values() if r.target == did and r.type.value == "DOCUMENTED_IN"})
    return {"document": d.model_dump(mode="json"), "fragments": frags, "requirements": reqs,
            "entities": [{"id": e, "name": kb.entities[e].name, "type": kb.entities[e].type.value}
                         for e in mentioned if e in kb.entities and kb.entities[e].type.value != "TechnicalRequirement"]}


@router.get("/projects/{pid}/documents/{did}/file")
def document_file(pid: str, did: str, user: CurrentUser = Depends(project_access())):
    p = state.file_path(pid, did)
    if not p or not p.exists():
        raise HTTPException(404, "Файл не найден")
    state.audit(user.username, "download", pid, document=did)
    return FileResponse(p, filename=p.name.split("_", 1)[-1])

"""Реестр рабочих пространств проектов и их сохранение в БД."""
from __future__ import annotations

import hashlib
import shutil
import threading
from pathlib import Path

from sqlalchemy import select

from eis.config import settings
from eis.db.models import AuditLog, DocumentRow, KBSnapshot, Project, User
from eis.db.session import init_db, session
from eis.domain.models import KnowledgeBase, stable_id
from eis.security.auth import hash_password
from eis.services.ingest import ingest_paths
from eis.services.workspace import Workspace

_lock = threading.RLock()
_ws: dict[str, Workspace] = {}


def bootstrap():
    init_db()
    with session() as s:
        if not s.scalar(select(User).where(User.username == "admin")):
            s.add(User(username="admin", password_hash=hash_password(settings.admin_password), role="admin"))
        if not s.get(Project, "demo"):
            s.add(Project(id="demo", name="НА-200 (демонстрационный)",
                          description="Синтетический набор документации насосного агрегата НА-200"))


def audit(user: str, action: str, project_id: str | None = None, **detail):
    with session() as s:
        s.add(AuditLog(user=user, action=action, project_id=project_id, detail=detail))


def project_dir(pid: str) -> Path:
    p = settings.data_dir / "projects" / pid / "files"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_ws(pid: str) -> Workspace:
    with _lock:
        if pid not in _ws:
            with session() as s:
                snap = s.scalars(select(KBSnapshot).where(KBSnapshot.project_id == pid).order_by(KBSnapshot.id.desc())).first()
            kb = KnowledgeBase.model_validate_json(snap.data) if snap else KnowledgeBase(project_id=pid)
            _ws[pid] = Workspace(kb)
        return _ws[pid]


def rebuild(pid: str) -> Workspace:
    """Повторная обработка всех документов проекта (межДокументные связи требуют полного прохода)."""
    with session() as s:
        rows = s.scalars(select(DocumentRow).where(DocumentRow.project_id == pid)).all()
        paths = [Path(r.path) for r in rows]
    kb = ingest_paths(paths, pid)
    ws = Workspace(kb)
    stats = {"documents": len(kb.documents), "requirements": len(kb.requirements), "relations": len(kb.relations)}
    with session() as s:
        s.add(KBSnapshot(project_id=pid, data=kb.model_dump_json(), stats=stats))
    with _lock:
        _ws[pid] = ws
    return ws


def add_file(pid: str, src: Path, filename: str, user: str) -> str:
    data = src.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    safe = "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._-()") or "file"
    dest = project_dir(pid) / f"{sha[:12]}_{safe}"
    if not dest.exists():
        shutil.copyfile(src, dest)
    did = "doc:" + stable_id(pid, sha)
    with session() as s:
        if not s.get(DocumentRow, did):
            s.add(DocumentRow(id=did, project_id=pid, filename=safe, fmt=Path(safe).suffix.lstrip(".").lower(), sha256=sha,
                              path=str(dest), size=len(data), uploaded_by=user))
    return did


def remove_document(pid: str, did: str):
    with session() as s:
        row = s.get(DocumentRow, did)
        if row and row.project_id == pid:
            s.delete(row)


def file_path(pid: str, did: str) -> Path | None:
    with session() as s:
        row = s.get(DocumentRow, did)
        return Path(row.path) if row and row.project_id == pid else None


def load_demo(user: str) -> Workspace:
    for p in sorted(settings.demo_dataset.iterdir()):
        if p.is_file():
            add_file("demo", p, p.name, user)
    return rebuild("demo")

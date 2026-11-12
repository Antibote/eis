from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Path

from eis.db.models import User
from eis.db.session import session
from eis.security.auth import has_role, read_token
from sqlalchemy import select


@dataclass
class CurrentUser:
    username: str
    role: str
    projects: list[str]
    allow_external_llm: bool


def current_user(authorization: str = Header(default="")) -> CurrentUser:
    tok = authorization.removeprefix("Bearer ").strip()
    data = read_token(tok) if tok else None
    if not data:
        raise HTTPException(401, "Требуется вход в систему")
    with session() as s:
        u = s.scalar(select(User).where(User.username == data["u"]))
        if not u:
            raise HTTPException(401, "Пользователь не найден")
        return CurrentUser(u.username, u.role, list(u.projects or []), bool(u.allow_external_llm))


def project_access(need: str = "viewer"):
    def dep(pid: str = Path(...), user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role != "admin" and pid not in user.projects:
            raise HTTPException(403, "Нет доступа к проекту")
        if not has_role(user.role, need):
            raise HTTPException(403, f"Недостаточно прав: требуется роль {need}")
        return user
    return dep

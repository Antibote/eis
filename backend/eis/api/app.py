"""FastAPI-приложение EIS. Запуск: uvicorn eis.api.app:app --reload"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from eis.api import state
from eis.api.routers import analysis, documents
from eis.config import ROOT, settings
from eis.db.models import User
from eis.db.session import session
from eis.api.deps import CurrentUser, current_user
from eis.security.auth import hash_password, issue_token, verify_password

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Engineering Intelligence System", version="0.1.0",
              description="Анализ инженерной документации и оценка последствий конструкторских изменений")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["*"],
                   allow_headers=["*"], allow_credentials=True)


@app.on_event("startup")
def _startup():
    state.bootstrap()


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login", tags=["auth"])
def login(body: LoginIn):
    with session() as s:
        u = s.scalar(select(User).where(User.username == body.username))
        if not u or not verify_password(body.password, u.password_hash):
            state.audit(body.username, "login_failed")
            raise HTTPException(401, "Неверное имя пользователя или пароль")
        role = u.role
    state.audit(body.username, "login")
    return {"token": issue_token(body.username, role), "username": body.username, "role": role}


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


@app.post("/api/auth/password", tags=["auth"])
def change_password(body: PasswordIn, user: CurrentUser = Depends(current_user)):
    """Смена собственного пароля: нужен текущий пароль; новый — не короче 10 символов и не равен имени."""
    new = body.new_password
    if len(new) < 10 or new.lower() == user.username.lower() or new == body.old_password:
        raise HTTPException(400, "Новый пароль: не короче 10 символов, не совпадает с именем и с прежним паролем")
    with session() as s:
        u = s.scalar(select(User).where(User.username == user.username))
        if not u or not verify_password(body.old_password, u.password_hash):
            state.audit(user.username, "password_change_failed")
            raise HTTPException(403, "Текущий пароль указан неверно")
        u.password_hash = hash_password(new)
    state.audit(user.username, "password_changed")
    return {"ok": True}


@app.get("/api/health", tags=["auth"])
def health():
    from eis.parsing.parsers import ocr_available
    from eis.llm.providers import provider_from_env
    llm = provider_from_env()
    return {"status": "ok", "ocr": ocr_available(), "llm": llm.name, "llm_available": llm.available}


app.include_router(documents.router)
app.include_router(analysis.router)

# собранный фронтенд (Docker): отдаём статику и index.html для клиентских маршрутов
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() and Path(f).resolve().is_relative_to(DIST) else DIST / "index.html")

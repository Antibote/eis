"""Локальная аутентификация: PBKDF2-хеши паролей, подписанные HMAC токены, роли."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from eis.config import settings

ROLES = {"viewer": 0, "engineer": 1, "admin": 2}


def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return f"pbkdf2${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(pw, bytes.fromhex(salt)).split("$")[2], h)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def issue_token(username: str, role: str) -> str:
    payload = _b64(json.dumps({"u": username, "r": role, "exp": int(time.time()) + settings.token_ttl_hours * 3600}).encode())
    sig = _b64(hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str) -> dict | None:
    try:
        payload, sig = token.split(".")
    except ValueError:
        return None
    good = _b64(hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        return None
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return data if data.get("exp", 0) > time.time() else None


def has_role(role: str, need: str) -> bool:
    return ROLES.get(role, -1) >= ROLES[need]

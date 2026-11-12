"""API: вход и смена пароля на временной базе (отдельный процесс — подключение к БД создаётся при импорте)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = textwrap.dedent('''
    from fastapi.testclient import TestClient
    from eis.api.app import app
    with TestClient(app) as c:
        t = c.post("/api/auth/login", json={"username": "admin", "password": "initial-pass"}).json()["token"]
        h = {"Authorization": f"Bearer {t}"}
        assert c.post("/api/auth/password", headers=h, json={"old_password": "wrong", "new_password": "new-long-password"}).status_code == 403
        assert c.post("/api/auth/password", headers=h, json={"old_password": "initial-pass", "new_password": "short"}).status_code == 400
        assert c.post("/api/auth/password", headers=h, json={"old_password": "initial-pass", "new_password": "new-long-password"}).status_code == 200
        assert c.post("/api/auth/login", json={"username": "admin", "password": "initial-pass"}).status_code == 401
        assert c.post("/api/auth/login", json={"username": "admin", "password": "new-long-password"}).status_code == 200
        assert c.post("/api/auth/password", json={"old_password": "x", "new_password": "y" * 12}).status_code == 401
    print("OK")
''')


def test_password_change_flow(tmp_path):
    env = {**os.environ, "EIS_DATABASE_URL": f"sqlite:///{tmp_path / 'eis.db'}", "EIS_DATA_DIR": str(tmp_path),
           "EIS_ADMIN_PASSWORD": "initial-pass", "EIS_SECRET_KEY": "test-secret"}
    backend = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-c", SCRIPT], cwd=backend, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-2000:]

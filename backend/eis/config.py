"""Настройки (переменные окружения EIS_*)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EIS_", env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{ROOT / 'data' / 'eis.db'}"
    data_dir: Path = ROOT / "data"
    secret_key: str = "dev-secret-change-me"
    token_ttl_hours: int = 12
    admin_password: str = "admin"
    cors_origins: str = "http://localhost:5173"
    demo_dataset: Path = ROOT / "dataset" / "out" / "test" / "docs"
    allow_external_llm: bool = False


settings = Settings()

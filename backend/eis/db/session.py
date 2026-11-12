from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from eis.config import settings
from eis.db.models import Base  # noqa: F401 (метаданные для миграций)

if settings.database_url.startswith("sqlite"):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(settings.database_url, future=True,
                       connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db():
    """Схема БД — миграциями Alembic. База, созданная до появления миграций (create_all), помечается
    начальной ревизией, затем применяются новые."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        if "users" in tables and "alembic_version" not in tables:
            command.stamp(cfg, "0001")
        command.upgrade(cfg, "head")


@contextmanager
def session():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()

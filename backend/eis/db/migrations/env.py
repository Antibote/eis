"""Окружение Alembic: метаданные моделей EIS, адрес БД — из настроек (EIS_DATABASE_URL)."""
from alembic import context
from sqlalchemy import engine_from_config, pool

from eis.config import settings
from eis.db.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def run_offline():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=settings.database_url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    conn = config.attributes.get("connection")       # передаётся из init_db
    if conn is not None:
        _run(conn)
        return
    engine = engine_from_config({}, prefix="sqlalchemy.", poolclass=pool.NullPool, url=settings.database_url)
    with engine.connect() as c:
        _run(c)


def _run(conn):
    context.configure(connection=conn, target_metadata=target_metadata,
                      render_as_batch=conn.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()

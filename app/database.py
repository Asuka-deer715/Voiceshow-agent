from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from pgvector.psycopg import register_vector

ROOT = Path(__file__).resolve().parents[1]
_init_lock = threading.Lock()
_initialized = False


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    for env_file in (ROOT / ".env", ROOT / ".env.database"):
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


DATABASE_URL = _env("DATABASE_URL", "")
if not DATABASE_URL.startswith("postgresql+psycopg://"):
    raise RuntimeError("Set DATABASE_URL to a PostgreSQL+psycopg connection URL")
DATABASE_READ_URL = _env("DATABASE_READ_URL", DATABASE_URL)
POOL_SIZE = int(_env("DB_POOL_SIZE", "10"))
MAX_OVERFLOW = int(_env("DB_MAX_OVERFLOW", "20"))
POOL_TIMEOUT = int(_env("DB_POOL_TIMEOUT", "30"))
SLOW_QUERY_MS = float(_env("DB_SLOW_QUERY_MS", "200"))


def _engine(url: str, role: str) -> Engine:
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError(f"{role} database must use PostgreSQL with psycopg")
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT,
        connect_args={"connect_timeout": 10, "application_name": f"voiceshop-{role}"},
        future=True,
        logging_name=f"voiceshop-{role}",
    )
    @event.listens_for(engine, "connect")
    def configure(dbapi_connection, _connection_record) -> None:
        register_vector(dbapi_connection)

    return engine


write_engine = _engine(DATABASE_URL, "write")
read_engine = _engine(DATABASE_READ_URL, "read")
WriteSession = sessionmaker(bind=write_engine, expire_on_commit=False, autoflush=False, future=True)
ReadSession = sessionmaker(bind=read_engine, expire_on_commit=False, autoflush=False, future=True)


@contextmanager
def write_session() -> Iterator[Session]:
    with WriteSession.begin() as session:
        yield session


@contextmanager
def read_session() -> Iterator[Session]:
    with ReadSession() as session:
        yield session


def init_database() -> None:
    """Run versioned migrations once during process startup."""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        from alembic import command
        from alembic.config import Config

        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "alembic"))
        command.upgrade(config, "head")
        _initialized = True

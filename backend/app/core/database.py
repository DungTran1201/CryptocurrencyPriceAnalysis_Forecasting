"""Database connection, engine configuration, WAL pragmas, and session factories.

Supports SQLite WAL (Profile LITE) and PostgreSQL (Profile STANDARD/EXTENDED)
with bounded connection pools and explicit async/sync session factories.
"""

from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from backend.app.core.config import settings


def normalize_sync_database_url(url: str) -> str:
    """Normalize sync DB URL for SQLAlchemy/Alembic (PostgreSQL -> postgresql+psycopg://)."""
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + url[len("postgresql+asyncpg://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg://" + url[len("postgresql+psycopg2://"):]
    if url.startswith("sqlite+aiosqlite://"):
        return "sqlite://" + url[len("sqlite+aiosqlite://"):]
    return url


def _ensure_sqlite_parent_dir(url: str) -> None:
    """Create parent directory for file-backed SQLite DBs outside testing mode."""
    if settings.app_env == "testing" or ":memory:" in url or "mode=memory" in url:
        return
    if ":///" in url:
        raw_path = url.split(":///", 1)[1].split("?", 1)[0]
        if raw_path:
            p = Path(raw_path)
            if not p.is_absolute():
                p = Path(settings.base_dir) / p
            p.parent.mkdir(parents=True, exist_ok=True)


_is_sqlite = "sqlite" in settings.database_url
_sync_database_url = normalize_sync_database_url(settings.sync_database_url)
if _is_sqlite:
    _ensure_sqlite_parent_dir(settings.database_url)

# Async Engine (for FastAPI REST endpoints and async consumers)
if _is_sqlite:
    async_engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
    )
else:
    async_engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
        pool_size=settings.resources.db_pool_size,
        max_overflow=settings.resources.db_max_overflow,
        pool_pre_ping=True,
    )


def _configure_sqlite_pragmas(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=15000;")
        cursor.execute("PRAGMA foreign_keys=ON;")
    finally:
        cursor.close()


if _is_sqlite:
    @event.listens_for(async_engine.sync_engine, "connect")
    def _on_async_sqlite_connect(dbapi_conn, connection_record):
        _configure_sqlite_pragmas(dbapi_conn, connection_record)

# Async Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Sync Engine (for Alembic migrations and synchronous worker utilities)
if "sqlite" in _sync_database_url:
    sync_engine = create_engine(
        _sync_database_url,
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
    )

    @event.listens_for(sync_engine, "connect")
    def _on_sync_sqlite_connect(dbapi_conn, connection_record):
        _configure_sqlite_pragmas(dbapi_conn, connection_record)
else:
    sync_engine = create_engine(
        _sync_database_url,
        echo=False,
        pool_size=settings.resources.db_pool_size,
        max_overflow=settings.resources.db_max_overflow,
        pool_pre_ping=True,
    )

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for injecting request-scoped async database sessions.

    Avoids unconditional commits on read-only GET requests while committing
    pending ORM mutations for backward compatibility.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            if session.new or session.dirty or session.deleted:
                await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_sync_db():
    """Context helper for synchronous database access in migrations/scripts."""
    db = SyncSessionLocal()
    try:
        yield db
        if db.new or db.dirty or db.deleted:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def init_db():
    """Initialize all database tables defined in SQLAlchemy models."""
    from backend.app.models import (  # noqa: F401
        market,
        forecast,
        ml_model,
        pipeline,
        data_quality,
        governance,
        lake,
        workflow,
    )
    if _is_sqlite:
        _ensure_sqlite_parent_dir(settings.database_url)
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

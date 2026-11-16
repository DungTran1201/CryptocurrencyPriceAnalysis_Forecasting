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

# Ensure local data directory exists for SQLite / checkpoints
db_path = Path(settings.storage.data_dir)
if not db_path.is_absolute():
    db_path = Path(settings.base_dir) / db_path
db_path.mkdir(parents=True, exist_ok=True)

_is_sqlite = "sqlite" in settings.database_url

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
        cursor.execute("PRAGMA busy_timeout=5000;")
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
if "sqlite" in settings.sync_database_url:
    sync_engine = create_engine(
        settings.sync_database_url,
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
    )

    @event.listens_for(sync_engine, "connect")
    def _on_sync_sqlite_connect(dbapi_conn, connection_record):
        _configure_sqlite_pragmas(dbapi_conn, connection_record)
else:
    sync_engine = create_engine(
        settings.sync_database_url,
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
    """Dependency for injecting request-scoped async database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
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
    )
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

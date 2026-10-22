"""Database connection, engine configuration, and session factories.

Supports both SQLite (for zero-setup local dev & tests) and PostgreSQL
(for production), with async and sync session managers.
"""

from typing import AsyncGenerator
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker
from backend.app.core.config import settings

# Base directory setup for SQLite storage
db_path = Path(settings.base_dir) / "data"
db_path.mkdir(parents=True, exist_ok=True)

# Async Engine (for FastAPI REST endpoints)
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)

# Async Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

# Sync Engine (for background workers and migrations)
sync_engine = create_engine(
    settings.sync_database_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.sync_database_url else {}
)

# Sync Session Factory
SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for injecting async database sessions into FastAPI routes."""
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
    """Context manager or helper for synchronous database access in workers/scripts."""
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
    """Initialize all database tables defined in models."""
    # Ensure all models are imported so Base metadata is populated
    from backend.app.models import market, forecast, ml_model  # noqa: F401
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

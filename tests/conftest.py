"""Pytest fixtures, TEST-ISO data directory isolation, and test database setup."""

import os
from pathlib import Path
import sys
from typing import AsyncGenerator, Dict, Tuple
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Ensure test environment flag is set before database/settings modules initialize
os.environ.setdefault("APP_ENV", "testing")

from backend.app.core.config import settings
from backend.app.core.database import Base
from backend.app.models import (  # noqa: F401
    market,
    forecast,
    ml_model,
    pipeline,
    data_quality,
    governance,
)
from backend.app.storage.local import LocalStorageBackend

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_GUARDED_DATA_SUBDIRS = ("bronze", "silver", "gold", "checkpoints", "models", "warehouse", "dlq")
_GUARDED_DATA_FILES = ("crypto_market.db",)


def _snapshot_live_data(repo_data_dir: Path) -> Dict[str, Tuple[int, int]]:
    """Capture (size, mtime_ns) of persisted lake/SQL files under repo ./data/."""
    snap: Dict[str, Tuple[int, int]] = {}
    if not repo_data_dir.exists():
        return snap
    for sub in _GUARDED_DATA_SUBDIRS:
        sub_path = repo_data_dir / sub
        if not sub_path.exists():
            continue
        for p in sub_path.rglob("*"):
            if p.is_file():
                st = p.stat()
                snap[p.relative_to(repo_data_dir).as_posix()] = (st.st_size, st.st_mtime_ns)
    for fname in _GUARDED_DATA_FILES:
        fp = repo_data_dir / fname
        if fp.exists() and fp.is_file():
            st = fp.stat()
            snap[fname] = (st.st_size, st.st_mtime_ns)
    return snap


def _rebind_runtime_storage(data_dir: Path) -> None:
    """Redirect singleton StreamPlatformRuntime storage/checkpoints if imported."""
    rt_mod = sys.modules.get("backend.app.streaming.runtime")
    if rt_mod is None:
        return
    rt = getattr(rt_mod, "stream_runtime", None)
    if rt is None:
        return
    rt.medallion.backend = LocalStorageBackend(data_dir)
    rt.analytics_engine.checkpoint_dir = data_dir / settings.storage.checkpoint_subdir
    rt.analytics_engine.states.clear()
    rt.consumer.medallion = rt.medallion
    rt._last_triggered_inference = None


@pytest.fixture(scope="session", autouse=True)
def _session_data_isolation_guard(tmp_path_factory: pytest.TempPathFactory):
    """TEST-ISO session guard: redirect defaults before app import & assert repo ./data/ untouched."""
    repo_data_dir = (Path(settings.base_dir) / "data").resolve()
    before = _snapshot_live_data(repo_data_dir)

    session_data = tmp_path_factory.mktemp("session_data")
    session_models = session_data / "models"
    session_models.mkdir(parents=True, exist_ok=True)

    orig_env = settings.app_env
    orig_backend = settings.storage.backend
    orig_data_dir = settings.storage.data_dir
    orig_model_dir = settings.ml.model_storage_dir

    settings.app_env = "testing"
    settings.storage.backend = "local"
    settings.storage.data_dir = str(session_data)
    settings.ml.model_storage_dir = str(session_models)
    os.environ["DATA_DIR"] = str(session_data)
    _rebind_runtime_storage(session_data)

    yield

    settings.app_env = orig_env
    settings.storage.backend = orig_backend
    settings.storage.data_dir = orig_data_dir
    settings.ml.model_storage_dir = orig_model_dir

    after = _snapshot_live_data(repo_data_dir)
    assert after == before, (
        "TEST-ISO violation: repository ./data/ was modified during pytest run! "
        f"added={set(after) - set(before)}, removed={set(before) - set(after)}"
    )


@pytest.fixture(scope="function", autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """TEST-ISO per-test fixture redirecting Lake, ML models, and runtime checkpoints to tmp_path."""
    test_data = tmp_path / "data"
    test_models = test_data / "models"
    test_data.mkdir(parents=True, exist_ok=True)
    test_models.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("DATA_DIR", str(test_data))
    monkeypatch.setattr(settings, "app_env", "testing")
    monkeypatch.setattr(settings.storage, "backend", "local")
    monkeypatch.setattr(settings.storage, "data_dir", str(test_data))
    monkeypatch.setattr(settings.ml, "model_storage_dir", str(test_models))

    from types import SimpleNamespace
    monkeypatch.setattr(
        "backend.app.api.v1.system.psutil.disk_usage",
        lambda _p: SimpleNamespace(free=50 * (1024 ** 3), total=100 * (1024 ** 3), percent=50.0),
    )

    _rebind_runtime_storage(test_data)
    yield test_data
    _rebind_runtime_storage(test_data)


@pytest_asyncio.fixture(scope="function")
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a fresh in-memory SQLite database session for each test."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()

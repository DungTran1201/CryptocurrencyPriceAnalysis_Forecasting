"""FastAPI Main Application Entry Point.

Includes lifespan database initialization, symbol seeding, optional embedded
streaming runtime (Profile LITE), Prometheus /metrics, CORS, security headers,
and static frontend serving.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.core.database import init_db, AsyncSessionLocal
from backend.app.core.logging import get_logger
from backend.app.core.metrics import collect_resource_snapshot, render_prometheus_metrics
from backend.app.models.market import Symbol
from backend.app.api.v1.router import api_v1_router
from backend.app.services.governance_service import GovernanceService
from backend.app.storage import get_data_root
from backend.app.streaming.runtime import stream_runtime

logger = get_logger("Application")


async def seed_initial_symbols():
    """Ensure default trading pairs exist in database on startup."""
    default_symbols = [
        {"symbol": "BTCUSDT", "base_asset": "BTC", "quote_asset": "USDT"},
        {"symbol": "ETHUSDT", "base_asset": "ETH", "quote_asset": "USDT"},
        {"symbol": "SOLUSDT", "base_asset": "SOL", "quote_asset": "USDT"},
        {"symbol": "BNBUSDT", "base_asset": "BNB", "quote_asset": "USDT"},
    ]
    async with AsyncSessionLocal() as session:
        for sym_data in default_symbols:
            stmt = select(Symbol).where(Symbol.symbol == sym_data["symbol"])
            res = await session.execute(stmt)
            if not res.scalar_one_or_none():
                session.add(Symbol(**sym_data, is_active=True))
        await session.commit()
        await GovernanceService.sync_catalog_entries(session)
    logger.info("Default market symbols & catalog entries verified in database.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    logger.info(
        f"Starting {settings.app_name} v{settings.app_version} "
        f"[env={settings.app_env}, profile={settings.profile.value}]"
    )
    await init_db()
    await seed_initial_symbols()

    if settings.streaming.enabled and settings.app_env != "testing":
        await stream_runtime.start(
            start_ingestor=settings.streaming.embedded_in_api,
            start_consumer=settings.streaming.embedded_in_api,
        )

    yield

    await stream_runtime.stop()
    logger.info("Application shutting down cleanly.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Resource-efficient single-node real-time cryptocurrency financial intelligence & forecasting platform.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Inject security headers on all HTTP responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    """Lightweight Prometheus text exposition endpoint."""
    collect_resource_snapshot(
        data_dir=str(get_data_root()),
        memory_budget_mb=settings.resources.total_memory_mb,
    )
    payload, content_type = render_prometheus_metrics()
    return Response(content=payload, media_type=content_type)


app.include_router(api_v1_router)

frontend_dist = Path(settings.base_dir) / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
else:
    @app.get("/")
    async def root_redirect():
        return {
            "message": f"Welcome to {settings.app_name}",
            "version": settings.app_version,
            "profile": settings.profile.value,
            "docs": "/docs",
            "health": "/api/v1/health",
            "status": "/api/v1/system/status",
            "metrics": "/metrics",
        }

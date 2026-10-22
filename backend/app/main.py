"""FastAPI Main Application Entry Point.

Includes lifespan database initialization, seed data, CORS middleware,
structured logging, and API route registration.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.core.database import init_db, AsyncSessionLocal
from backend.app.core.logging import get_logger
from backend.app.models.market import Symbol
from backend.app.api.v1.router import api_v1_router

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
                sym = Symbol(**sym_data, is_active=True)
                session.add(sym)
        await session.commit()
    logger.info("Default market symbols verified in database.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version} [{settings.app_env}]")
    # Initialize SQLite/PostgreSQL tables
    await init_db()
    # Seed symbols
    await seed_initial_symbols()
    yield
    logger.info("Application shutting down cleanly.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Production-grade cryptocurrency market intelligence and forecasting API.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers_and_logging(request: Request, call_next):
    """Inject security headers and log API response time."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


# Register API v1 routes
app.include_router(api_v1_router)

# Mount static frontend build if it exists
frontend_dist = Path(settings.base_dir) / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
else:
    @app.get("/")
    async def root_redirect():
        return {
            "message": f"Welcome to {settings.app_name}",
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/api/v1/health",
            "status": "/api/v1/system/status"
        }

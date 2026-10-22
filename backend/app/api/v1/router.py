"""API v1 master router assembly."""

from fastapi import APIRouter
from backend.app.api.v1.market import router as market_router
from backend.app.api.v1.forecast import router as forecast_router
from backend.app.api.v1.models import router as models_router
from backend.app.api.v1.system import router as system_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(system_router)
api_v1_router.include_router(market_router)
api_v1_router.include_router(forecast_router)
api_v1_router.include_router(models_router)

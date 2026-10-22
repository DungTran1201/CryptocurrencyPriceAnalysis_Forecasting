"""API v1 master router assembly."""

from fastapi import APIRouter
from backend.app.api.v1.market import router as market_router
from backend.app.api.v1.forecast import router as forecast_router
from backend.app.api.v1.models import router as models_router
from backend.app.api.v1.system import router as system_router
from backend.app.api.v1.pipelines import router as pipelines_router
from backend.app.api.v1.data_quality import router as data_quality_router
from backend.app.api.v1.analytics import router as analytics_router
from backend.app.api.v1.data_explorer import router as data_explorer_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(system_router)
api_v1_router.include_router(pipelines_router)
api_v1_router.include_router(data_quality_router)
api_v1_router.include_router(analytics_router)
api_v1_router.include_router(data_explorer_router)
api_v1_router.include_router(market_router)
api_v1_router.include_router(forecast_router)
api_v1_router.include_router(models_router)

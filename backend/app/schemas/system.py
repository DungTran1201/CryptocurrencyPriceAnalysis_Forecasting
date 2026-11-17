"""Pydantic schemas for Health, System Status, and Resource Telemetry endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class CheckpointSummarySchema(BaseModel):
    """Synchronization status per symbol and timeframe."""
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    timeframe: str
    total_candles: int
    last_close_time: Optional[datetime] = None
    last_sync_status: str
    detected_gaps_count: int
    updated_at: datetime


class DependencyCheckSchema(BaseModel):
    """Individual dependency probe status."""
    status: str  # OK | DEGRADED | FAILED | UNAVAILABLE | SKIPPED
    detail: Optional[str] = None


class HealthStatusSchema(BaseModel):
    """Dependency-probing readiness and liveness schema."""
    status: str  # healthy | degraded | unhealthy
    profile: str
    timestamp: str
    app_name: str
    version: str
    checks: Dict[str, DependencyCheckSchema]


class SystemStatusResponse(BaseModel):
    """Overall system health and synchronization status."""
    status: str
    version: str
    environment: str
    current_time: str
    database_connected: bool
    total_candles_stored: int
    total_forecasts_generated: int
    total_reconciled_forecasts: int
    active_models_count: int
    checkpoints: List[CheckpointSummarySchema]


SystemStatusSchema = SystemStatusResponse


class MeasuredResourcesSchema(BaseModel):
    """Live process RSS/CPU, host memory/disk, and per-layer storage footprint."""
    process_pid: int
    process_rss_mb: float
    memory_budget_mb: int
    budget_utilization_pct: float
    process_cpu_percent: float
    host_ram_total_mb: float
    host_ram_available_mb: float
    host_ram_used_pct: float
    disk_free_gb: float
    disk_used_pct: float
    storage_mb: Dict[str, float]


class StreamingSummarySchema(BaseModel):
    """Summary of real-time broker, ingestor, producer, and consumer metrics."""
    status: str = "AVAILABLE"
    broker_connected: bool
    broker_backend: Optional[str] = None
    broker_messages: int = 0
    total_consumer_lag: int = 0
    ws_connected: bool = False
    events_received: int = 0
    events_published: int = 0
    events_consumed: int = 0
    queue_depth: int = 0
    backpressure_active: bool = False
    dlq_count: int = 0


class ResourceMetricsSchema(BaseModel):
    """Typed response contract for /api/v1/system/resources."""
    profile: str
    embedded_in_api: bool
    limits: Dict[str, Any]
    measured: MeasuredResourcesSchema
    streaming: StreamingSummarySchema
    workers: Dict[str, Any]

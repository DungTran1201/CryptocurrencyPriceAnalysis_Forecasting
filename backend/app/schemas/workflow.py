"""Typed Pydantic request and response schemas for durable SQL workflow orchestration (IFC-DP-007)."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class TriggerPipelineRequest(BaseModel):
    """Payload to enqueue or trigger a durable Medallion pipeline workflow run."""

    symbol: str = Field(default="BTCUSDT", description="Trading pair symbol")
    timeframe: str = Field(default="1h", description="Candle timeframe (e.g. 1m, 5m, 15m, 1h, 4h, 1d)")
    trigger_type: str = Field(
        default="MANUAL",
        description="Trigger mechanism (MANUAL, SCHEDULED, RETRY, BACKFILL, RECOMPUTE, RECONNECT)",
    )
    lookback_days: int = Field(default=30, ge=1, le=180, description="Lookback window if initial seed")
    skip_network_ingest: bool = Field(
        default=False,
        description="If true, skip REST network sync and recompute Silver/Gold/Features from stored candles",
    )


class WorkflowEnqueuedResponse(BaseModel):
    """Typed HTTP 202 (or bounded sync) response returned when dispatching a workflow run."""

    model_config = ConfigDict(from_attributes=True)

    run_id: str
    workflow_type: str
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    status: str
    idempotency_key: str
    deduplicated: bool = False
    created_at: Optional[datetime] = None
    pipeline_status: Optional[str] = None
    duration_seconds: Optional[float] = None
    rows_inserted: Optional[int] = None
    message: str


class WorkflowTaskSchema(BaseModel):
    """Step-level DAG task state representation."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    task_name: str
    sequence_order: int
    depends_on: Optional[str] = None
    status: str
    attempt: int
    max_attempts: int
    checkpoint_json: Optional[Dict[str, Any]] = None
    records_processed: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    error_code: Optional[str] = None
    error_summary: Optional[str] = None


class WorkflowRunSummarySchema(BaseModel):
    """Summary representation of a durable workflow run."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_type: str
    pipeline_name: str
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    trigger_type: str
    idempotency_key: str
    status: str
    priority: int
    attempt: int
    max_attempts: int
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    next_run_at: datetime
    rows_read: int = 0
    rows_inserted: int = 0
    gaps_detected: int = 0
    error_code: Optional[str] = None
    error_summary: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    created_at: datetime


class WorkflowRunDetailSchema(WorkflowRunSummarySchema):
    """Detailed workflow run breakdown including params and child task steps."""

    params: Optional[Dict[str, Any]] = None
    tasks: List[WorkflowTaskSchema] = Field(default_factory=list)


class PipelineOverviewSchema(BaseModel):
    """Aggregated workflow execution KPIs (IFC-DP-007)."""

    total_runs: int
    queued_runs: int
    running_runs: int
    retry_wait_runs: int
    succeeded_runs: int
    failed_runs: int
    cancelled_runs: int
    success_rate_pct: float
    total_rows_read: int
    total_rows_inserted: int
    avg_duration_seconds: float
    latest_successful_run_at: Optional[datetime] = None
    latest_error_code: Optional[str] = None
    latest_error_summary: Optional[str] = None
    latest_error_message: Optional[str] = None


class WorkflowScheduleSchema(BaseModel):
    """Persisted recurring workflow schedule view."""

    model_config = ConfigDict(from_attributes=True)

    schedule_id: str
    workflow_type: str
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    interval_seconds: int
    enabled: bool
    params: Optional[Dict[str, Any]] = None
    last_run_id: Optional[str] = None
    last_triggered_at: Optional[datetime] = None
    next_trigger_at: datetime
    updated_at: datetime


class WorkflowScheduleUpsertRequest(BaseModel):
    """Create or replace a persisted recurring workflow schedule."""

    schedule_id: Optional[str] = Field(default=None, min_length=3, max_length=64)
    workflow_type: str = Field(..., description="Target workflow type (e.g. MARKET_SYNC, WAREHOUSE_BUILD)")
    symbol: Optional[str] = Field(default=None, description="Optional target symbol")
    timeframe: Optional[str] = Field(default=None, description="Optional target timeframe")
    interval_seconds: int = Field(..., ge=10, le=604800, description="Execution interval in seconds")
    enabled: bool = Field(default=True)
    params: Optional[Dict[str, Any]] = Field(default=None)


class WorkflowSchedulePatchRequest(BaseModel):
    """Partially update an existing recurring workflow schedule."""

    interval_seconds: Optional[int] = Field(default=None, ge=10, le=604800)
    enabled: Optional[bool] = Field(default=None)
    params: Optional[Dict[str, Any]] = Field(default=None)

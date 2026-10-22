"""Pipeline orchestration and task execution tracking models."""

from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Text,
    ForeignKey,
    Index
)
from backend.app.core.database import Base


class PipelineRun(Base):
    """Tracks end-to-end execution of data pipelines (Medallion: Ingest -> Validate -> Gold Marts -> Features)."""
    __tablename__ = "pipeline_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pipeline_name = Column(String(64), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    timeframe = Column(String(16), nullable=False, index=True)
    
    status = Column(String(24), default="PENDING", nullable=False, index=True)  # PENDING, RUNNING, SUCCESS, FAILED, CANCELLED
    trigger_type = Column(String(24), default="MANUAL", nullable=False)          # MANUAL, SCHEDULED, RETRY, BACKFILL
    
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    
    # Throughput and data statistics
    rows_read = Column(Integer, default=0, nullable=False)
    rows_inserted = Column(Integer, default=0, nullable=False)
    rows_updated = Column(Integer, default=0, nullable=False)
    rows_rejected = Column(Integer, default=0, nullable=False)
    gaps_detected = Column(Integer, default=0, nullable=False)
    
    start_watermark = Column(DateTime, nullable=True)
    end_watermark = Column(DateTime, nullable=True)
    
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False, index=True)


class PipelineTaskRun(Base):
    """Tracks execution of individual tasks within a pipeline run."""
    __tablename__ = "pipeline_task_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pipeline_run_id = Column(String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    task_name = Column(String(64), nullable=False)  # e.g., ingest_bronze, validate_silver, build_gold_marts, extract_features
    sequence_order = Column(Integer, default=1, nullable=False)
    
    status = Column(String(24), default="PENDING", nullable=False)  # PENDING, RUNNING, SUCCESS, FAILED, SKIPPED
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    
    records_processed = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    logs = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)

    __table_args__ = (
        Index("ix_task_runs_pipeline_task", "pipeline_run_id", "sequence_order"),
    )

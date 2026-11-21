"""Data Quality runs and rule-level result models."""

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


class DataQualityRun(Base):
    """Execution record for an automated batch or streaming data quality validation suite."""
    __tablename__ = "data_quality_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_name = Column(String(64), default="silver_klines", nullable=False)
    check_mode = Column(String(16), default="BATCH", nullable=False, index=True)  # BATCH | STREAM
    symbol = Column(String(32), nullable=False, index=True)
    timeframe = Column(String(16), nullable=False, index=True)

    run_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False, index=True)
    status = Column(String(24), default="PASSED", nullable=False)  # PASSED, WARNING, FAILED

    total_rules_evaluated = Column(Integer, default=0, nullable=False)
    rules_passed = Column(Integer, default=0, nullable=False)
    rules_failed = Column(Integer, default=0, nullable=False)
    evaluated_row_count = Column(Integer, default=0, nullable=False)
    duration_ms = Column(Float, default=0.0, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)

    __table_args__ = (
        Index("ix_dq_runs_symbol_tf", "symbol", "timeframe"),
    )


class DataQualityResult(Base):
    """Detailed evaluation result for an individual data quality rule."""
    __tablename__ = "data_quality_results"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(36), ForeignKey("data_quality_runs.id", ondelete="CASCADE"), nullable=False, index=True)

    rule_id = Column(String(64), nullable=False, index=True)
    rule_name = Column(String(128), nullable=False)
    category = Column(String(32), nullable=False)
    severity = Column(String(16), default="ERROR", nullable=False)

    status = Column(String(16), default="PASS", nullable=False, index=True)
    failed_records_count = Column(Integer, default=0, nullable=False)
    sample_failures = Column(Text, nullable=True)
    message = Column(Text, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)

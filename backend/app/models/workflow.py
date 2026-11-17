"""Durable SQL workflow orchestration models (runs, child tasks, leases, and schedules)."""

from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from backend.app.core.database import Base


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WorkflowRun(Base):
    """Durable workflow job ledger with active-run mutual exclusion and lease tracking."""
    __tablename__ = "workflow_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_type = Column(String(32), nullable=False)
    symbol = Column(String(32), nullable=True)
    timeframe = Column(String(16), nullable=True)
    trigger_type = Column(String(24), default="MANUAL", nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    status = Column(String(24), default="QUEUED", nullable=False)
    priority = Column(Integer, default=5, nullable=False)
    attempt = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    next_run_at = Column(DateTime, default=_utc_now_naive, nullable=False)

    lease_owner = Column(String(64), nullable=True)
    lease_token = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)

    params_json = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_summary = Column(String(512), nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False)

    __table_args__ = (
        Index("ix_workflow_runs_claim", "status", "next_run_at", "priority"),
        Index("ix_workflow_runs_lease", "status", "lease_expires_at"),
        Index(
            "uq_workflow_active_idempotency",
            "idempotency_key",
            unique=True,
            sqlite_where=text("status IN ('QUEUED', 'RUNNING', 'RETRY_WAIT')"),
            postgresql_where=text("status IN ('QUEUED', 'RUNNING', 'RETRY_WAIT')"),
        ),
    )

    @property
    def pipeline_name(self) -> str:
        return self.workflow_type or "MEDALLION_DAG"

    @property
    def workflow_version(self) -> str:
        return "2.0"

    @property
    def retry_count(self) -> int:
        return self.attempt or 0

    @property
    def error_message(self) -> Optional[str]:
        return self.error_summary

    @property
    def rows_read(self) -> int:
        if self.result_json:
            try:
                import json
                data = json.loads(self.result_json)
                return sum(v.get("rows_read", 0) for v in data.values() if isinstance(v, dict))
            except Exception:
                pass
        return 0

    @property
    def rows_inserted(self) -> int:
        if self.result_json:
            try:
                import json
                data = json.loads(self.result_json)
                return sum(v.get("rows_inserted", 0) for v in data.values() if isinstance(v, dict))
            except Exception:
                pass
        return 0

    @property
    def rows_updated(self) -> int:
        return 0

    @property
    def rows_rejected(self) -> int:
        return 0

    @property
    def gaps_detected(self) -> int:
        if self.result_json:
            try:
                import json
                data = json.loads(self.result_json)
                return sum(v.get("gaps_detected", 0) for v in data.values() if isinstance(v, dict))
            except Exception:
                pass
        return 0

    @property
    def start_watermark(self) -> Optional[datetime]:
        return None

    @property
    def end_watermark(self) -> Optional[datetime]:
        return None


class WorkflowTask(Base):
    """Step-level DAG task state supporting idempotent resume on worker crash."""
    __tablename__ = "workflow_tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    task_name = Column(String(64), nullable=False)
    sequence_order = Column(Integer, default=1, nullable=False)
    depends_on = Column(String(128), nullable=True)
    status = Column(String(24), default="PENDING", nullable=False)
    attempt = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=2, nullable=False)
    checkpoint_json = Column(Text, nullable=True)
    records_processed = Column(BigInteger, default=0, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_summary = Column(String(512), nullable=True)

    __table_args__ = (
        Index("ix_workflow_tasks_run_seq", "run_id", "sequence_order"),
    )


class WorkflowSchedule(Base):
    """Persisted recurring workflow triggers replacing in-memory sleep loops."""
    __tablename__ = "workflow_schedules"

    schedule_id = Column(String(64), primary_key=True)
    workflow_type = Column(String(32), nullable=False)
    symbol = Column(String(32), nullable=True)
    timeframe = Column(String(16), nullable=True)
    interval_seconds = Column(Integer, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    params_json = Column(Text, nullable=True)
    last_run_id = Column(String(36), ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True)
    last_triggered_at = Column(DateTime, nullable=True)
    next_trigger_at = Column(DateTime, default=_utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=_utc_now_naive, onupdate=_utc_now_naive, nullable=False)

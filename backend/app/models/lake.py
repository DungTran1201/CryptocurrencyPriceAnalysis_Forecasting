"""Data Lake manifest, batch commit ledger, and Warehouse snapshot pointer models."""

from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from backend.app.core.database import Base


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BatchLedger(Base):
    """Transactional ledger tracking micro-batch, backfill, compaction, and ETL units."""
    __tablename__ = "batch_ledger"

    batch_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_type = Column(String(32), nullable=False)
    producer_name = Column(String(64), nullable=False)
    symbol = Column(String(32), nullable=True)
    timeframe = Column(String(16), nullable=True)
    idempotency_key = Column(String(128), unique=True, nullable=False)
    status = Column(String(24), default="PREPARED", nullable=False)
    nats_seq_start = Column(BigInteger, nullable=True)
    nats_seq_end = Column(BigInteger, nullable=True)
    records_received = Column(Integer, default=0, nullable=False)
    records_written = Column(Integer, default=0, nullable=False)
    records_rejected = Column(Integer, default=0, nullable=False)
    staged_keys_json = Column(Text, nullable=True)
    snapshot_id = Column(String(36), nullable=True)
    error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False)
    committed_at = Column(DateTime, nullable=True)
    acked_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_batch_ledger_status", "status", "created_at"),
    )


class LakeSnapshot(Base):
    """Immutable dataset version pointer for Bronze, Silver, and Gold Parquet/JSONL layers."""
    __tablename__ = "lake_snapshots"

    snapshot_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_id = Column(String(64), nullable=False)
    version_seq = Column(BigInteger, nullable=False)
    parent_snapshot_id = Column(String(36), nullable=True)
    schema_version = Column(String(32), nullable=False)
    schema_hash = Column(String(64), nullable=False)
    batch_id = Column(String(36), ForeignKey("batch_ledger.batch_id", ondelete="SET NULL"), nullable=True)
    status = Column(String(24), default="STAGING", nullable=False)
    total_files = Column(Integer, default=0, nullable=False)
    total_rows = Column(BigInteger, default=0, nullable=False)
    total_bytes = Column(BigInteger, default=0, nullable=False)
    min_event_time = Column(DateTime, nullable=True)
    max_event_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False)
    published_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("dataset_id", "version_seq", name="uq_lake_snapshot_ds_ver"),
        Index("ix_lake_snapshots_ds_status", "dataset_id", "status"),
    )


class LakeManifestFile(Base):
    """Exact immutable object inventory belonging to a LakeSnapshot."""
    __tablename__ = "lake_manifest_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(String(36), ForeignKey("lake_snapshots.snapshot_id", ondelete="CASCADE"), nullable=False)
    object_key = Column(String(512), nullable=False)
    partition_symbol = Column(String(32), nullable=True)
    partition_timeframe = Column(String(16), nullable=True)
    partition_dt = Column(String(10), nullable=True)
    file_format = Column(String(16), nullable=False)
    row_count = Column(BigInteger, nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    min_ts = Column(DateTime, nullable=True)
    max_ts = Column(DateTime, nullable=True)
    is_compacted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False)

    __table_args__ = (
        UniqueConstraint("snapshot_id", "object_key", name="uq_manifest_snap_key"),
        Index("ix_manifest_lookup", "snapshot_id", "partition_symbol", "partition_timeframe", "partition_dt"),
    )


class WarehouseSnapshot(Base):
    """Versioned immutable DuckDB Warehouse snapshot pointer and GC metadata."""
    __tablename__ = "warehouse_snapshots"

    dw_snapshot_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    warehouse_version = Column(BigInteger, unique=True, nullable=False)
    source_lake_snapshot_id = Column(String(36), ForeignKey("lake_snapshots.snapshot_id", ondelete="SET NULL"), nullable=True)
    file_path = Column(String(512), nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    row_count_total = Column(BigInteger, default=0, nullable=False)
    status = Column(String(24), default="STAGING", nullable=False)
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False)
    published_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_warehouse_snap_status", "status", "warehouse_version"),
    )

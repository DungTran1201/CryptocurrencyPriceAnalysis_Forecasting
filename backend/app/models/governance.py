"""Governance, Data Catalog, Data Lineage, Dead-Letter, and Stream Checkpoint models."""

from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    UniqueConstraint,
    Index,
)
from backend.app.core.database import Base


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DataCatalogEntry(Base):
    """Persistent lightweight Data Catalog tracking datasets across Medallion layers."""
    __tablename__ = "data_catalog_entries"

    dataset_id = Column(String(64), primary_key=True)
    dataset_name = Column(String(128), nullable=False)
    layer = Column(String(32), nullable=False, index=True)  # SOURCE, BRONZE, SILVER, GOLD, FEATURES, SERVING
    description = Column(Text, nullable=False)
    schema_json = Column(Text, nullable=False)
    data_type = Column(String(32), nullable=False)  # JSONL_ZSTD, PARQUET, SQL_TABLE, JOBLIB
    source = Column(String(64), nullable=False)
    partition_spec = Column(String(128), nullable=True)
    row_count = Column(Integer, default=0, nullable=False)
    size_bytes = Column(Integer, default=0, nullable=False)
    storage_location = Column(String(256), nullable=False)
    owner = Column(String(64), default="data-platform", nullable=False)
    retention_policy = Column(String(64), nullable=False)
    version = Column(String(32), default="1.0.0", nullable=False)
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=_utc_now_naive, onupdate=_utc_now_naive, nullable=False)


class DataLineageEdge(Base):
    """Queryable persistent lineage record tracing dataset-to-dataset transformations."""
    __tablename__ = "data_lineage_edges"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(64), nullable=True, index=True)
    source_dataset = Column(String(64), nullable=False, index=True)
    target_dataset = Column(String(64), nullable=False, index=True)
    transformation = Column(String(128), nullable=False)
    records_in = Column(Integer, default=0, nullable=False)
    records_out = Column(Integer, default=0, nullable=False)
    status = Column(String(24), default="SUCCESS", nullable=False)
    metadata_json = Column(Text, nullable=True)
    recorded_at = Column(DateTime, default=_utc_now_naive, nullable=False, index=True)

    __table_args__ = (
        Index("ix_lineage_src_tgt", "source_dataset", "target_dataset"),
    )


class DeadLetterEvent(Base):
    """Persisted record of failed/malformed stream events routed to Dead-Letter Queue."""
    __tablename__ = "dead_letter_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    subject = Column(String(128), nullable=False, index=True)
    stream_type = Column(String(32), nullable=False)
    symbol = Column(String(32), nullable=False, index=True)
    event_id = Column(String(128), nullable=True, index=True)
    payload_json = Column(Text, nullable=False)
    error_reason = Column(Text, nullable=False)
    delivery_count = Column(Integer, default=1, nullable=False)
    status = Column(String(24), default="QUARANTINED", nullable=False, index=True)  # QUARANTINED, REPLAYED, IGNORED
    created_at = Column(DateTime, default=_utc_now_naive, nullable=False, index=True)
    replayed_at = Column(DateTime, nullable=True)


class StreamCheckpoint(Base):
    """Durable stream consumer and ingestion watermark checkpoints."""
    __tablename__ = "stream_checkpoints"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    consumer_name = Column(String(64), nullable=False)
    subject = Column(String(128), nullable=False)
    symbol = Column(String(32), nullable=False)
    stream_type = Column(String(32), nullable=False)
    last_event_time = Column(DateTime, nullable=True)
    last_stream_seq = Column(Integer, default=0, nullable=False)
    processed_count = Column(Integer, default=0, nullable=False)
    error_count = Column(Integer, default=0, nullable=False)
    status = Column(String(24), default="ACTIVE", nullable=False)
    state_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=_utc_now_naive, onupdate=_utc_now_naive, nullable=False)

    __table_args__ = (
        UniqueConstraint("consumer_name", "symbol", "stream_type", name="uq_stream_checkpoint"),
    )


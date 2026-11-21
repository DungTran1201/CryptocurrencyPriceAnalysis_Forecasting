"""Data Governance Service: Persistent Catalog, Lineage, DLQ, and Retention Enforcement."""

from datetime import datetime, timezone, timedelta
import json
from typing import Any, Dict, List, Optional
from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.models.governance import (
    DataCatalogEntry,
    DataLineageEdge,
    DeadLetterEvent,
    StreamCheckpoint,
)
from backend.app.models.market import Kline, SyncCheckpoint
from backend.app.models.forecast import ForecastRecord
from backend.app.models.ml_model import ModelRegistryEntry
from backend.app.models.data_quality import DataQualityRun
from backend.app.storage import get_storage_backend
from backend.app.storage.medallion import MedallionStorageManager

logger = get_logger("GovernanceService")


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


CATALOG_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "dataset_id": "binance_public_stream",
        "dataset_name": "Binance Public WS & REST Source",
        "layer": "SOURCE",
        "data_type": "WEBSOCKET_REST_JSON",
        "source": "binance_vision_api",
        "partition_spec": "symbol / stream (aggTrade, kline_1m)",
        "storage_location": "wss://data-stream.binance.vision:9443",
        "retention_policy": "External transient stream",
        "version": "1.0.0",
        "description": "Public Binance WebSocket real-time aggTrade & kline_1m streams plus REST historical backfill.",
        "schema": [
            {"name": "event_type", "type": "STRING", "nullable": False, "description": "aggTrade or kline"},
            {"name": "symbol", "type": "STRING", "nullable": False, "description": "Normalized pair symbol"},
            {"name": "event_time", "type": "TIMESTAMP_UTC", "nullable": False, "description": "Exchange event timestamp"},
        ],
    },
    {
        "dataset_id": "bronze_market_events",
        "dataset_name": "Bronze Raw Market Events",
        "layer": "BRONZE",
        "data_type": "JSONL_ZSTD",
        "source": "binance_ws_rest",
        "partition_spec": "source=binance/stream={stream}/dt={YYYY-MM-DD}/symbol={SYMBOL}",
        "storage_location": "data/bronze",
        "retention_policy": "Age & byte cap per runtime profile",
        "version": "1.0.0",
        "description": "Immutable compressed JSONL micro-batches preserving original source payloads and ingestion metadata.",
        "schema": [
            {"name": "schema_version", "type": "STRING", "nullable": False, "description": "Canonical schema version"},
            {"name": "event_id", "type": "STRING", "nullable": False, "description": "Deterministic idempotency key"},
            {"name": "ingestion_time", "type": "TIMESTAMP_UTC", "nullable": False, "description": "Connector UTC receipt time"},
            {"name": "payload", "type": "JSON", "nullable": False, "description": "Raw normalized event envelope"},
        ],
    },
    {
        "dataset_id": "silver_klines",
        "dataset_name": "Silver Validated OHLCV Klines",
        "layer": "SILVER",
        "data_type": "PARQUET_AND_SQL",
        "source": "bronze_market_events",
        "partition_spec": "event_type=klines/timeframe={tf}/dt={YYYY-MM-DD}/symbol={SYMBOL}",
        "storage_location": "data/silver + klines",
        "retention_policy": "Age & byte cap per runtime profile",
        "version": "1.0.0",
        "description": "Deduplicated, OHLC-validated candlestick records stored as partitioned Parquet and transactional SQLite/Postgres.",
        "schema": [
            {"name": "symbol", "type": "VARCHAR(32)", "nullable": False, "description": "Trading pair symbol"},
            {"name": "timeframe", "type": "VARCHAR(16)", "nullable": False, "description": "Candle interval"},
            {"name": "open_time", "type": "TIMESTAMP_UTC", "nullable": False, "description": "Bar open timestamp"},
            {"name": "close_time", "type": "TIMESTAMP_UTC", "nullable": False, "description": "Bar close timestamp"},
            {"name": "open", "type": "DOUBLE", "nullable": False, "description": "Open price"},
            {"name": "high", "type": "DOUBLE", "nullable": False, "description": "High price"},
            {"name": "low", "type": "DOUBLE", "nullable": False, "description": "Low price"},
            {"name": "close", "type": "DOUBLE", "nullable": False, "description": "Close price"},
            {"name": "volume", "type": "DOUBLE", "nullable": False, "description": "Base asset volume"},
            {"name": "is_closed", "type": "BOOLEAN", "nullable": False, "description": "Bar finalized flag"},
        ],
    },
    {
        "dataset_id": "silver_agg_trades",
        "dataset_name": "Silver Validated Aggregate Trades",
        "layer": "SILVER",
        "data_type": "PARQUET",
        "source": "bronze_market_events",
        "partition_spec": "event_type=agg_trades/dt={YYYY-MM-DD}/symbol={SYMBOL}",
        "storage_location": "data/silver/source=binance/event_type=agg_trades",
        "retention_policy": "Age & byte cap per runtime profile",
        "version": "1.0.0",
        "description": "Micro-batched, compacted aggregate trade tick Parquet partitions (never stored row-by-row in SQL).",
        "schema": [
            {"name": "symbol", "type": "STRING", "nullable": False, "description": "Trading pair symbol"},
            {"name": "agg_trade_id", "type": "INT64", "nullable": False, "description": "Binance aggregate trade ID"},
            {"name": "price", "type": "DOUBLE", "nullable": False, "description": "Execution price"},
            {"name": "quantity", "type": "DOUBLE", "nullable": False, "description": "Executed quantity"},
            {"name": "trade_time", "type": "TIMESTAMP_UTC", "nullable": False, "description": "UTC execution time"},
        ],
    },
    {
        "dataset_id": "gold_analytics_marts",
        "dataset_name": "Gold Financial & Risk Analytics Marts",
        "layer": "GOLD",
        "data_type": "PARQUET_DUCKDB",
        "source": "silver_klines",
        "partition_spec": "dataset=analytics_marts/timeframe={tf}/dt={YYYY-MM-DD}/symbol={SYMBOL}",
        "storage_location": "data/gold/dataset=analytics_marts",
        "retention_policy": "Age & byte cap per runtime profile",
        "version": "1.0.0",
        "description": "Materialized returns, log returns, ATR, VWAP, rolling volatility, and drawdown Parquet marts queried via DuckDB.",
        "schema": [
            {"name": "symbol", "type": "STRING", "nullable": False, "description": "Trading pair symbol"},
            {"name": "open_time", "type": "TIMESTAMP_UTC", "nullable": False, "description": "Bar timestamp"},
            {"name": "simple_return", "type": "DOUBLE", "nullable": True, "description": "Simple period return"},
            {"name": "log_return", "type": "DOUBLE", "nullable": True, "description": "Logarithmic return"},
            {"name": "atr_14", "type": "DOUBLE", "nullable": True, "description": "14-period Average True Range"},
            {"name": "vwap", "type": "DOUBLE", "nullable": True, "description": "Session Volume Weighted Average Price"},
            {"name": "drawdown_pct", "type": "DOUBLE", "nullable": True, "description": "Drawdown from running peak (%)"},
        ],
    },
    {
        "dataset_id": "gold_feature_sets",
        "dataset_name": "Gold ML Technical Feature Sets",
        "layer": "FEATURES",
        "data_type": "PARQUET_DUCKDB",
        "source": "silver_klines",
        "partition_spec": "dataset=feature_sets/timeframe={tf}/dt={YYYY-MM-DD}/symbol={SYMBOL}",
        "storage_location": "data/gold/dataset=feature_sets",
        "retention_policy": "Age & byte cap per runtime profile",
        "version": "1.0.0",
        "description": "Zero-lookahead normalized technical indicators, lagged returns, and volatility features for walk-forward ML.",
        "schema": [
            {"name": "symbol", "type": "STRING", "nullable": False, "description": "Trading pair symbol"},
            {"name": "open_time", "type": "TIMESTAMP_UTC", "nullable": False, "description": "Feature cutoff timestamp"},
            {"name": "rsi_14", "type": "DOUBLE", "nullable": True, "description": "Normalized RSI(14)"},
            {"name": "boll_pct_b", "type": "DOUBLE", "nullable": True, "description": "Bollinger %B"},
            {"name": "atr_norm", "type": "DOUBLE", "nullable": True, "description": "Normalized ATR(14)"},
        ],
    },
    {
        "dataset_id": "forecast_records",
        "dataset_name": "Serving Forecasts & Reconciliation Ledger",
        "layer": "SERVING",
        "data_type": "SQL_TABLE",
        "source": "gold_feature_sets",
        "partition_spec": "symbol / target_time",
        "storage_location": "forecast_records",
        "retention_policy": "Permanent audit ledger",
        "version": "1.0.0",
        "description": "Immutable point-in-time ML predictions, confidence intervals, and post-close realized outcomes.",
        "schema": [
            {"name": "model_id", "type": "VARCHAR(64)", "nullable": False, "description": "Serving model ID"},
            {"name": "symbol", "type": "VARCHAR(32)", "nullable": False, "description": "Trading pair symbol"},
            {"name": "predicted_price", "type": "DOUBLE", "nullable": False, "description": "Projected price"},
            {"name": "status", "type": "VARCHAR(16)", "nullable": False, "description": "PENDING or RECONCILED"},
        ],
    },
]


class GovernanceService:
    """Manages persistent Data Catalog, Lineage DAG, DLQ records, and Retention cleanup."""

    @staticmethod
    async def sync_catalog_entries(db: AsyncSession) -> List[DataCatalogEntry]:
        """Synchronize persistent Data Catalog entries with actual SQL & file storage statistics."""
        storage = get_storage_backend()
        medallion = MedallionStorageManager(storage)

        kline_count = int(await db.scalar(select(func.count(Kline.id))) or 0)
        fc_count = int(await db.scalar(select(func.count(ForecastRecord.id))) or 0)
        bronze_stat = storage.stat_prefix(settings.storage.bronze_subdir)
        silver_kline_stat = storage.stat_prefix(f"{settings.storage.silver_subdir}/source=binance/event_type=klines")
        silver_trade_stat = storage.stat_prefix(f"{settings.storage.silver_subdir}/source=binance/event_type=agg_trades")
        gold_mart_stat = storage.stat_prefix(f"{settings.storage.gold_subdir}/dataset=analytics_marts")
        gold_feat_stat = storage.stat_prefix(f"{settings.storage.gold_subdir}/dataset=feature_sets")

        silver_trade_rows = 0
        if silver_trade_stat["file_count"] > 0:
            try:
                import pyarrow.parquet as pq
                import io
                for k in storage.list_keys(f"{settings.storage.silver_subdir}/source=binance/event_type=agg_trades", ".parquet")[-20:]:
                    silver_trade_rows += pq.read_metadata(io.BytesIO(storage.read_bytes(k))).num_rows
            except Exception:
                pass

        gold_mart_rows = 0
        if gold_mart_stat["file_count"] > 0:
            try:
                gold_mart_rows = len(medallion.read_gold_dataset("analytics_marts", limit=5000))
            except Exception:
                pass

        gold_feat_rows = 0
        if gold_feat_stat["file_count"] > 0:
            try:
                gold_feat_rows = len(medallion.read_gold_dataset("feature_sets", limit=5000))
            except Exception:
                pass

        stream_events = int(await db.scalar(select(func.sum(StreamCheckpoint.processed_count))) or 0)
        counts_and_sizes = {
            "binance_public_stream": (stream_events + kline_count, 0, "External transient"),
            "bronze_market_events": (
                stream_events + kline_count,
                int(bronze_stat["total_bytes"]),
                f"{settings.resources.retention_bronze_days}d / {settings.resources.retention_bronze_max_mb}MB",
            ),
            "silver_klines": (
                kline_count,
                int(silver_kline_stat["total_bytes"]),
                f"{settings.resources.retention_silver_days}d / {settings.resources.retention_silver_max_mb}MB",
            ),
            "silver_agg_trades": (
                silver_trade_rows,
                int(silver_trade_stat["total_bytes"]),
                f"{settings.resources.retention_silver_days}d / {settings.resources.retention_silver_max_mb}MB",
            ),
            "gold_analytics_marts": (
                gold_mart_rows,
                int(gold_mart_stat["total_bytes"]),
                f"{settings.resources.retention_gold_days}d / {settings.resources.retention_gold_max_mb}MB",
            ),
            "gold_feature_sets": (
                gold_feat_rows,
                int(gold_feat_stat["total_bytes"]),
                f"{settings.resources.retention_gold_days}d / {settings.resources.retention_gold_max_mb}MB",
            ),
            "forecast_records": (fc_count, 0, "Permanent audit ledger"),
        }

        now = _utc_now_naive()
        entries: List[DataCatalogEntry] = []
        for d in CATALOG_DEFINITIONS:
            did = d["dataset_id"]
            row_count, size_bytes, retention = counts_and_sizes[did]
            existing = await db.get(DataCatalogEntry, did)
            if existing is None:
                existing = DataCatalogEntry(
                    dataset_id=did,
                    dataset_name=d["dataset_name"],
                    layer=d["layer"],
                    description=d["description"],
                    schema_json=json.dumps(d["schema"]),
                    data_type=d["data_type"],
                    source=d["source"],
                    partition_spec=d["partition_spec"],
                    row_count=row_count,
                    size_bytes=size_bytes,
                    storage_location=d["storage_location"],
                    owner="data-platform",
                    retention_policy=retention,
                    version=d["version"],
                    created_at=now,
                    updated_at=now,
                )
                db.add(existing)
            else:
                existing.row_count = row_count
                existing.size_bytes = size_bytes
                existing.retention_policy = retention
                existing.updated_at = now
            entries.append(existing)

        await db.commit()
        return entries

    @staticmethod
    async def list_catalog(db: AsyncSession, layer: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query persistent Data Catalog entries, refreshing counts first."""
        await GovernanceService.sync_catalog_entries(db)
        stmt = select(DataCatalogEntry)
        if layer:
            stmt = stmt.where(DataCatalogEntry.layer == layer.upper())
        res = await db.execute(stmt.order_by(DataCatalogEntry.created_at.asc()))
        rows = res.scalars().all()
        return [
            {
                "dataset_id": r.dataset_id,
                "dataset_name": r.dataset_name,
                "layer": r.layer,
                "description": r.description,
                "schema": json.loads(r.schema_json),
                "data_type": r.data_type,
                "source": r.source,
                "partition_spec": r.partition_spec,
                "row_count": r.row_count,
                "size_bytes": r.size_bytes,
                "storage_location": r.storage_location,
                "owner": r.owner,
                "retention_policy": r.retention_policy,
                "version": r.version,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]

    @staticmethod
    async def record_lineage_edge(
        db: AsyncSession,
        source_dataset: str,
        target_dataset: str,
        transformation: str,
        records_in: int,
        records_out: int,
        run_id: Optional[str] = None,
        status: str = "SUCCESS",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DataLineageEdge:
        """Persist an auditable data lineage edge."""
        edge = DataLineageEdge(
            run_id=run_id,
            source_dataset=source_dataset,
            target_dataset=target_dataset,
            transformation=transformation,
            records_in=records_in,
            records_out=records_out,
            status=status,
            metadata_json=json.dumps(metadata) if metadata else None,
            recorded_at=_utc_now_naive(),
        )
        db.add(edge)
        await db.flush()
        return edge

    @staticmethod
    async def get_lineage_graph(db: AsyncSession, dataset_filter: Optional[str] = None) -> Dict[str, Any]:
        """Build real, queryable lineage DAG backed by persistent catalog & lineage edge tables."""
        catalog = await GovernanceService.list_catalog(db)
        cat_map = {c["dataset_id"]: c for c in catalog}

        edges_stmt = select(DataLineageEdge).order_by(DataLineageEdge.recorded_at.desc()).limit(100)
        if dataset_filter:
            edges_stmt = edges_stmt.where(
                (DataLineageEdge.source_dataset == dataset_filter)
                | (DataLineageEdge.target_dataset == dataset_filter)
            )
        persisted_edges = list((await db.execute(edges_stmt)).scalars().all())

        latest_cp = await db.scalar(select(SyncCheckpoint).order_by(SyncCheckpoint.updated_at.desc()).limit(1))
        latest_dq = await db.scalar(select(DataQualityRun).order_by(DataQualityRun.run_timestamp.desc()).limit(1))
        active_models = int(
            await db.scalar(select(func.count(ModelRegistryEntry.model_id)).where(ModelRegistryEntry.is_active == True)) or 0
        )

        def _status_for(row_count: int, default_active: str = "HEALTHY") -> str:
            return default_active if row_count > 0 else "IDLE"

        nodes = [
            {
                "id": "src_binance",
                "label": "Binance Public WS & REST",
                "layer": "SOURCE",
                "type": "api",
                "status": "HEALTHY" if cat_map.get("binance_public_stream", {}).get("row_count", 0) > 0 else "IDLE",
                "details": "Public WS (aggTrade, kline_1m) & REST klines",
                "records": cat_map.get("binance_public_stream", {}).get("row_count", 0),
                "freshness": latest_cp.updated_at.strftime("%Y-%m-%d %H:%M UTC") if latest_cp else "Awaiting stream/sync",
            },
            {
                "id": "bronze_raw",
                "label": "Bronze Raw Storage",
                "layer": "BRONZE",
                "type": "lakehouse",
                "status": _status_for(cat_map.get("bronze_market_events", {}).get("row_count", 0)),
                "details": "Immutable zstd JSONL micro-batches + NATS JetStream",
                "records": cat_map.get("bronze_market_events", {}).get("row_count", 0),
                "freshness": cat_map.get("bronze_market_events", {}).get("updated_at", "")[:19].replace("T", " "),
            },
            {
                "id": "silver_klines",
                "label": "Silver Validated Layer",
                "layer": "SILVER",
                "type": "table",
                "status": (
                    "FAILED" if (latest_dq and latest_dq.status == "FAILED")
                    else "WARNING" if (latest_dq and latest_dq.status == "WARNING")
                    else _status_for(cat_map.get("silver_klines", {}).get("row_count", 0))
                ),
                "details": "Partitioned Parquet + SQLite/Postgres deduplicated OHLCV",
                "records": cat_map.get("silver_klines", {}).get("row_count", 0)
                + cat_map.get("silver_agg_trades", {}).get("row_count", 0),
                "freshness": latest_dq.run_timestamp.strftime("%Y-%m-%d %H:%M UTC") if latest_dq else "No DQ run yet",
            },
            {
                "id": "gold_analytics",
                "label": "Gold DuckDB Marts",
                "layer": "GOLD",
                "type": "analytics",
                "status": _status_for(cat_map.get("gold_analytics_marts", {}).get("row_count", 0)),
                "details": "DuckDB-backed Returns, Volatility, VaR/CVaR, MDD, VWAP, ATR",
                "records": cat_map.get("gold_analytics_marts", {}).get("row_count", 0),
                "freshness": cat_map.get("gold_analytics_marts", {}).get("updated_at", "")[:19].replace("T", " "),
            },
            {
                "id": "feature_store",
                "label": "Feature Engineering Layer",
                "layer": "FEATURES",
                "type": "ml",
                "status": _status_for(cat_map.get("gold_feature_sets", {}).get("row_count", 0)),
                "details": "Zero-lookahead Parquet features + online rolling state",
                "records": cat_map.get("gold_feature_sets", {}).get("row_count", 0),
                "freshness": cat_map.get("gold_feature_sets", {}).get("updated_at", "")[:19].replace("T", " "),
            },
            {
                "id": "serving_forecasts",
                "label": "Forecast & Model Serving",
                "layer": "SERVING",
                "type": "service",
                "status": "HEALTHY" if (cat_map.get("forecast_records", {}).get("row_count", 0) > 0 or active_models > 0) else "IDLE",
                "details": f"{active_models} active gated models • Forecast reconciliation ledger",
                "records": cat_map.get("forecast_records", {}).get("row_count", 0),
                "freshness": cat_map.get("forecast_records", {}).get("updated_at", "")[:19].replace("T", " "),
            },
        ]

        canonical_edges = [
            {"source": "src_binance", "target": "bronze_raw", "contract": "WS/REST -> NATS JetStream -> zstd JSONL"},
            {"source": "bronze_raw", "target": "silver_klines", "contract": "Schema + OHLC DQ Gate -> Parquet/SQL"},
            {"source": "silver_klines", "target": "gold_analytics", "contract": "DuckDB Aggregation & Risk Marts"},
            {"source": "silver_klines", "target": "feature_store", "contract": "Zero-Lookahead Feature Vectors"},
            {"source": "feature_store", "target": "serving_forecasts", "contract": "Walk-Forward ML & Triggered Inference"},
        ]

        return {
            "nodes": nodes,
            "edges": canonical_edges,
            "recorded_runs": [
                {
                    "id": e.id,
                    "run_id": e.run_id,
                    "source_dataset": e.source_dataset,
                    "target_dataset": e.target_dataset,
                    "transformation": e.transformation,
                    "records_in": e.records_in,
                    "records_out": e.records_out,
                    "status": e.status,
                    "recorded_at": e.recorded_at.isoformat(),
                }
                for e in persisted_edges[:30]
            ],
            "last_updated": _utc_now_naive().strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    @staticmethod
    def enforce_retention() -> Dict[str, Any]:
        """Prune Bronze/Silver/Gold files exceeding age or size budget limits."""
        storage = get_storage_backend()
        now_ts = datetime.now(timezone.utc).timestamp()

        policies = [
            ("bronze", settings.storage.bronze_subdir, settings.resources.retention_bronze_days, settings.resources.retention_bronze_max_mb),
            ("silver", settings.storage.silver_subdir, settings.resources.retention_silver_days, settings.resources.retention_silver_max_mb),
            ("gold", settings.storage.gold_subdir, settings.resources.retention_gold_days, settings.resources.retention_gold_max_mb),
        ]

        deleted_files = 0
        freed_bytes = 0
        summary: Dict[str, Any] = {}

        for layer_name, prefix, max_days, max_mb in policies:
            max_age_sec = max_days * 86400
            max_bytes = max_mb * 1024 * 1024
            keys = storage.list_keys(prefix=prefix)
            file_stats = []
            for k in keys:
                try:
                    p = storage.local_path(k)
                    st = p.stat()
                    file_stats.append((k, st.st_mtime, st.st_size))
                except Exception:
                    continue

            layer_deleted = 0
            layer_freed = 0
            remaining = []
            # 1. Age-based pruning
            for k, mtime, sz in file_stats:
                if (now_ts - mtime) > max_age_sec:
                    if storage.delete(k):
                        layer_deleted += 1
                        layer_freed += sz
                else:
                    remaining.append((k, mtime, sz))

            # 2. Size-cap pruning (oldest first)
            total_bytes = sum(sz for _, _, sz in remaining)
            if total_bytes > max_bytes:
                remaining.sort(key=lambda x: x[1])
                for k, _, sz in remaining:
                    if total_bytes <= max_bytes:
                        break
                    if storage.delete(k):
                        total_bytes -= sz
                        layer_deleted += 1
                        layer_freed += sz

            deleted_files += layer_deleted
            freed_bytes += layer_freed
            summary[layer_name] = {
                "deleted_files": layer_deleted,
                "freed_bytes": layer_freed,
                "remaining_bytes": total_bytes,
                "limit_mb": max_mb,
            }

        logger.info(f"Retention check complete: removed {deleted_files} files ({freed_bytes} bytes).")
        return {"deleted_files": deleted_files, "freed_bytes": freed_bytes, "layers": summary}


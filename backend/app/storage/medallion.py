"""Real Medallion Storage Engine: Bronze (zstd JSONL), Silver (Parquet), Gold (DuckDB + Parquet), & SQL Manifests."""

from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
import zstandard as zstd

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.core.metrics import BATCH_WRITE_LATENCY, EVENTS_PERSISTED
from backend.app.models.governance import DataCatalogEntry
from backend.app.models.lake import BatchLedger, LakeManifestFile, LakeSnapshot
from backend.app.storage import StorageBackend, get_storage_backend
from backend.app.storage.duckdb_engine import open_bounded_duckdb
from ml.features import extract_features
from ml.incremental_analytics import compute_batch_reference_metrics

logger = get_logger("MedallionStorage")


class CorruptParquetError(RuntimeError):
    """Raised when reading an existing Parquet partition fails instead of silently dropping data."""


SILVER_KLINE_SCHEMA_VERSION = "1.1.0"
SILVER_KLINE_SCHEMA = pa.schema([
    ("symbol", pa.string()),
    ("timeframe", pa.string()),
    ("open_time", pa.timestamp("us")),
    ("close_time", pa.timestamp("us")),
    ("open", pa.float64()),
    ("high", pa.float64()),
    ("low", pa.float64()),
    ("close", pa.float64()),
    ("volume", pa.float64()),
    ("quote_asset_volume", pa.float64()),
    ("number_of_trades", pa.int64()),
    ("taker_buy_base_asset_volume", pa.float64()),
    ("taker_buy_quote_asset_volume", pa.float64()),
    ("is_closed", pa.bool_()),
    ("source", pa.string()),
    ("ingestion_time", pa.timestamp("us")),
])

SILVER_TRADE_SCHEMA_VERSION = "1.0.0"
SILVER_TRADE_SCHEMA = pa.schema([
    ("symbol", pa.string()),
    ("agg_trade_id", pa.int64()),
    ("price", pa.float64()),
    ("quantity", pa.float64()),
    ("quote_quantity", pa.float64()),
    ("is_buyer_maker", pa.bool_()),
    ("trade_time", pa.timestamp("us")),
    ("event_time", pa.timestamp("us")),
    ("ingestion_time", pa.timestamp("us")),
    ("source", pa.string()),
])

GOLD_ANALYTICS_SCHEMA_VERSION = "1.0.0"
GOLD_ANALYTICS_SCHEMA = pa.schema([
    ("symbol", pa.string()),
    ("timeframe", pa.string()),
    ("open_time", pa.timestamp("us")),
    ("close", pa.float64()),
    ("volume", pa.float64()),
    ("simple_return", pa.float64()),
    ("log_return", pa.float64()),
    ("atr_14", pa.float64()),
    ("vwap", pa.float64()),
    ("vol_7_ann_pct", pa.float64()),
    ("vol_14_ann_pct", pa.float64()),
    ("vol_30_ann_pct", pa.float64()),
    ("running_peak", pa.float64()),
    ("drawdown_pct", pa.float64()),
])

GOLD_FEATURE_SCHEMA_VERSION = "1.0.0"
GOLD_FEATURE_SCHEMA = pa.schema([
    ("symbol", pa.string()),
    ("timeframe", pa.string()),
    ("open_time", pa.timestamp("us")),
    ("close", pa.float64()),
    ("return_1", pa.float64()),
    ("return_3", pa.float64()),
    ("return_6", pa.float64()),
    ("return_12", pa.float64()),
    ("return_24", pa.float64()),
    ("ratio_sma_7", pa.float64()),
    ("ratio_sma_14", pa.float64()),
    ("ratio_sma_50", pa.float64()),
    ("ratio_ema_14", pa.float64()),
    ("ratio_sma_cross", pa.float64()),
    ("volatility_7", pa.float64()),
    ("volatility_14", pa.float64()),
    ("volatility_30", pa.float64()),
    ("rsi_14", pa.float64()),
    ("rsi_7", pa.float64()),
    ("boll_pct_b", pa.float64()),
    ("macd_line", pa.float64()),
    ("macd_signal", pa.float64()),
    ("macd_hist", pa.float64()),
    ("atr_norm", pa.float64()),
    ("volume_ratio_14", pa.float64()),
    ("volume_change_1", pa.float64()),
    ("lag_return_1", pa.float64()),
    ("lag_return_2", pa.float64()),
    ("lag_return_3", pa.float64()),
])

_PARTITION_LOCKS_GUARD = threading.Lock()
_PARTITION_LOCKS: Dict[Tuple[str, ...], threading.RLock] = {}


def _get_partition_lock(*parts: str) -> threading.RLock:
    with _PARTITION_LOCKS_GUARD:
        lock = _PARTITION_LOCKS.get(parts)
        if lock is None:
            lock = threading.RLock()
            _PARTITION_LOCKS[parts] = lock
        return lock


def _schema_hash(schema: pa.Schema) -> str:
    canonical = json.dumps([(f.name, str(f.type), f.nullable) for f in schema], sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc).replace(tzinfo=None) if val.tzinfo else val
    dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def merge_kline_records(
    existing: Optional[Dict[str, Any]],
    incoming: Dict[str, Any],
    force_reconcile: bool = False,
) -> Dict[str, Any]:
    """Unified open->closed promotion rule for SQL & Silver Parquet klines.

    - None -> incoming: INSERT
    - open + closed -> incoming: PROMOTE to closed
    - open + open -> incoming if newer close_time and volume >= existing
    - closed + open -> existing: REJECT downgrade
    - closed + closed -> existing (or incoming if force_reconcile=True)
    """
    if existing is None:
        return incoming
    ex_closed = bool(existing.get("is_closed", False))
    in_closed = bool(incoming.get("is_closed", False))
    if not ex_closed and in_closed:
        return incoming
    if not ex_closed and not in_closed:
        ex_ct = _parse_dt(existing["close_time"])
        in_ct = _parse_dt(incoming["close_time"])
        if in_ct >= ex_ct and float(incoming["volume"]) >= float(existing["volume"]):
            return incoming
        return existing
    if ex_closed and not in_closed:
        return existing
    return incoming if force_reconcile else existing


def _escape_duckdb_path(path_str: str) -> str:
    return path_str.replace("\\", "/").replace("'", "''")


class MedallionStorageManager:
    """Manages Bronze raw archival, immutable Silver/Gold Parquet, compaction, & SQL manifests."""

    def __init__(self, backend: Optional[StorageBackend] = None):
        self.backend = backend or get_storage_backend()
        self._compressor = zstd.ZstdCompressor(level=3)
        self._decompressor = zstd.ZstdDecompressor()

    # ------------------------------------------------------------------
    # BRONZE LAYER (Immutable unified zstd-compressed JSONL micro-batches)
    # ------------------------------------------------------------------
    def write_bronze_batch(
        self,
        stream_name: str,
        symbol: str,
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Compress and persist immutable raw event records to Bronze storage."""
        if not records:
            return {"key": None, "records": 0, "bytes": 0, "file_meta": None}

        t0 = time.perf_counter()
        now = datetime.now(timezone.utc)
        now_naive = now.replace(tzinfo=None)
        dt_str = now.strftime("%Y-%m-%d")
        ts_str = now.strftime("%Y%m%dT%H%M%S")
        sym_up = symbol.upper()
        stream_low = stream_name.lower()
        key = (
            f"{settings.storage.bronze_subdir}/source=binance/stream={stream_low}/"
            f"dt={dt_str}/symbol={sym_up}/part-{ts_str}-{uuid.uuid4().hex[:8]}.jsonl.zst"
        )

        normalized_lines: List[str] = []
        min_ts: Optional[datetime] = None
        max_ts: Optional[datetime] = None
        for r in records:
            env = dict(r)
            env.setdefault("schema_version", "1.1.0")
            env.setdefault("source", "binance_rest" if stream_low.startswith("rest_") else "binance_ws")
            env.setdefault("symbol", sym_up)
            env.setdefault("event_type", "rest_kline" if stream_low.startswith("rest_") else stream_low)
            ing_raw = env.get("ingestion_time") or now.isoformat()
            env["ingestion_time"] = ing_raw
            if not env.get("event_id"):
                raw_k = env.get("raw_kline")
                if isinstance(raw_k, list) and raw_k:
                    tf_part = env.get("timeframe", stream_low)
                    env["event_id"] = f"rest_kline:{sym_up}:{tf_part}:{raw_k[0]}"
                else:
                    env["event_id"] = f"{env['event_type']}:{sym_up}:{uuid.uuid4().hex[:12]}"
            ev_ts = _parse_dt(env.get("event_time") or ing_raw)
            if min_ts is None or ev_ts < min_ts:
                min_ts = ev_ts
            if max_ts is None or ev_ts > max_ts:
                max_ts = ev_ts
            normalized_lines.append(json.dumps(env, default=str, ensure_ascii=True))

        raw_bytes = ("\n".join(normalized_lines) + "\n").encode("utf-8")
        compressed = self._compressor.compress(raw_bytes)
        sha = hashlib.sha256(compressed).hexdigest()
        written_bytes = self.backend.write_bytes(key, compressed)

        BATCH_WRITE_LATENCY.labels(layer="bronze").observe(time.perf_counter() - t0)
        EVENTS_PERSISTED.labels(layer="bronze", symbol=sym_up).inc(len(records))
        return {
            "key": key,
            "uri": self.backend.resolve_uri(key),
            "records": len(records),
            "raw_bytes": len(raw_bytes),
            "bytes": written_bytes,
            "file_meta": {
                "object_key": key,
                "partition_symbol": sym_up,
                "partition_timeframe": None,
                "partition_dt": dt_str,
                "file_format": "JSONL_ZSTD",
                "row_count": len(records),
                "size_bytes": written_bytes,
                "sha256": sha,
                "min_ts": min_ts or now_naive,
                "max_ts": max_ts or now_naive,
                "is_compacted": False,
            },
        }

    def read_bronze_records(self, prefix: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        """Read bounded raw JSONL.zst records from Bronze storage."""
        pfx = prefix or settings.storage.bronze_subdir
        keys = self.backend.list_keys(prefix=pfx, suffix=".jsonl.zst")
        rows: List[Dict[str, Any]] = []
        for key in reversed(keys):
            raw = self._decompressor.decompress(self.backend.read_bytes(key)).decode("utf-8")
            for line in reversed(raw.splitlines()):
                if not line.strip():
                    continue
                rows.append(json.loads(line))
                if len(rows) >= limit:
                    return rows
        return rows

    # ------------------------------------------------------------------
    # SILVER LAYER (Immutable partitioned Parquet + open->closed upsert)
    # ------------------------------------------------------------------
    def _normalize_silver_kline_row(self, row: Dict[str, Any], symbol: str, timeframe: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": _parse_dt(row["open_time"]),
            "close_time": _parse_dt(row["close_time"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "quote_asset_volume": (
                float(row["quote_asset_volume"]) if row.get("quote_asset_volume") is not None else None
            ),
            "number_of_trades": (
                int(row["number_of_trades"]) if row.get("number_of_trades") is not None else None
            ),
            "taker_buy_base_asset_volume": (
                float(row["taker_buy_base_asset_volume"])
                if row.get("taker_buy_base_asset_volume") is not None else None
            ),
            "taker_buy_quote_asset_volume": (
                float(row["taker_buy_quote_asset_volume"])
                if row.get("taker_buy_quote_asset_volume") is not None else None
            ),
            "is_closed": bool(row.get("is_closed", True)),
            "source": str(row.get("source", "binance")),
            "ingestion_time": _parse_dt(row.get("ingestion_time") or datetime.now(timezone.utc)),
        }

    def write_silver_klines(
        self,
        symbol: str,
        timeframe: str,
        records: List[Dict[str, Any]],
        cleanup_replaced: bool = True,
        force_reconcile: bool = False,
        source_keys_override: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        """Deduplicate and persist validated OHLCV klines to immutable partitioned Silver Parquet."""
        if not records:
            return {"records": 0, "files": [], "file_metas": []}

        t0 = time.perf_counter()
        symbol = symbol.upper()
        timeframe = timeframe.lower()
        root_key = self.backend.resolve_uri("")

        by_date: Dict[str, List[Dict[str, Any]]] = {}
        for r in records:
            o, h, l, c, v = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["volume"])
            if h < l or h < o or h < c or l > o or l > c or v < 0:
                continue
            norm = self._normalize_silver_kline_row(r, symbol, timeframe)
            dt_key = norm["open_time"].strftime("%Y-%m-%d")
            by_date.setdefault(dt_key, []).append(norm)

        written_files: List[str] = []
        file_metas: List[Dict[str, Any]] = []
        total_rows = 0

        for dt_key, batch in by_date.items():
            part_lock = _get_partition_lock(root_key, "silver_klines", symbol, timeframe, dt_key)
            with part_lock:
                dedup_map: Dict[Tuple[str, str, datetime], Dict[str, Any]] = {}
                for b in batch:
                    k = (b["symbol"], b["timeframe"], b["open_time"])
                    dedup_map[k] = merge_kline_records(dedup_map.get(k), b, force_reconcile=force_reconcile)
                clean_batch = sorted(dedup_map.values(), key=lambda x: x["open_time"])
                if not clean_batch:
                    continue

                part_prefix = (
                    f"{settings.storage.silver_subdir}/source=binance/event_type=klines/"
                    f"timeframe={timeframe}/dt={dt_key}/symbol={symbol}"
                )
                if source_keys_override is not None and dt_key in source_keys_override:
                    existing_keys = list(source_keys_override[dt_key])
                else:
                    existing_keys = self.backend.list_keys(prefix=part_prefix, suffix=".parquet")

                merged_rows: Dict[Tuple[str, str, datetime], Dict[str, Any]] = {}
                for old_key in existing_keys:
                    try:
                        old_table = pq.read_table(io.BytesIO(self.backend.read_bytes(old_key)))
                        for row in old_table.to_pylist():
                            norm_old = self._normalize_silver_kline_row(row, row["symbol"], row["timeframe"])
                            rk = (norm_old["symbol"], norm_old["timeframe"], norm_old["open_time"])
                            merged_rows[rk] = merge_kline_records(merged_rows.get(rk), norm_old, force_reconcile=False)
                    except Exception as exc:
                        raise CorruptParquetError(f"Failed reading Silver Parquet {old_key}: {exc}") from exc

                for item in clean_batch:
                    rk = (item["symbol"], item["timeframe"], item["open_time"])
                    merged_rows[rk] = merge_kline_records(merged_rows.get(rk), item, force_reconcile=force_reconcile)

                final_list = sorted(merged_rows.values(), key=lambda x: x["open_time"])
                table = pa.Table.from_pylist(final_list, schema=SILVER_KLINE_SCHEMA)
                buf = io.BytesIO()
                pq.write_table(table, buf, compression="snappy")
                payload = buf.getvalue()
                sha = hashlib.sha256(payload).hexdigest()

                target_key = f"{part_prefix}/part-{dt_key}-{uuid.uuid4().hex[:8]}.parquet"
                written_bytes = self.backend.write_bytes(target_key, payload)

                if cleanup_replaced:
                    for old_key in existing_keys:
                        if old_key != target_key:
                            self.backend.delete(old_key)

                written_files.append(target_key)
                file_metas.append({
                    "object_key": target_key,
                    "partition_symbol": symbol,
                    "partition_timeframe": timeframe,
                    "partition_dt": dt_key,
                    "file_format": "PARQUET",
                    "row_count": len(final_list),
                    "size_bytes": written_bytes,
                    "sha256": sha,
                    "min_ts": final_list[0]["open_time"],
                    "max_ts": final_list[-1]["open_time"],
                    "is_compacted": False,
                })
                total_rows += len(clean_batch)

        BATCH_WRITE_LATENCY.labels(layer="silver").observe(time.perf_counter() - t0)
        EVENTS_PERSISTED.labels(layer="silver", symbol=symbol).inc(total_rows)
        return {"records": total_rows, "files": written_files, "file_metas": file_metas}

    def write_silver_trades(
        self,
        symbol: str,
        records: List[Dict[str, Any]],
        cleanup_replaced: bool = True,
        auto_compact_threshold: int = 6,
    ) -> Dict[str, Any]:
        """Persist micro-batch validated aggTrade events into immutable partitioned Silver Parquet."""
        if not records:
            return {"records": 0, "files": [], "file_metas": [], "compacted": False}

        t0 = time.perf_counter()
        symbol = symbol.upper()
        root_key = self.backend.resolve_uri("")
        by_date: Dict[str, List[Dict[str, Any]]] = {}

        for r in records:
            price = float(r["price"])
            qty = float(r["quantity"])
            if price <= 0 or qty < 0:
                continue
            trade_dt = _parse_dt(r["trade_time"])
            event_dt = _parse_dt(r.get("event_time") or trade_dt)
            ing_dt = _parse_dt(r.get("ingestion_time") or datetime.now(timezone.utc))
            dt_key = trade_dt.strftime("%Y-%m-%d")
            by_date.setdefault(dt_key, []).append({
                "symbol": symbol,
                "agg_trade_id": int(r["agg_trade_id"]),
                "price": price,
                "quantity": qty,
                "quote_quantity": float(r.get("quote_quantity", price * qty)),
                "is_buyer_maker": bool(r["is_buyer_maker"]),
                "trade_time": trade_dt,
                "event_time": event_dt,
                "ingestion_time": ing_dt,
                "source": str(r.get("source", "binance_ws")),
            })

        written_files: List[str] = []
        file_metas: List[Dict[str, Any]] = []
        total_rows = 0
        compacted_any = False
        now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

        for dt_key, batch in by_date.items():
            part_lock = _get_partition_lock(root_key, "silver_agg_trades", symbol, dt_key)
            with part_lock:
                dedup = {(b["symbol"], b["agg_trade_id"]): b for b in batch}
                clean = sorted(dedup.values(), key=lambda x: x["agg_trade_id"])
                part_prefix = f"{settings.storage.silver_subdir}/source=binance/event_type=agg_trades/dt={dt_key}/symbol={symbol}"
                target_key = f"{part_prefix}/part-{now_str}-{uuid.uuid4().hex[:8]}.parquet"
                table = pa.Table.from_pylist(clean, schema=SILVER_TRADE_SCHEMA)
                buf = io.BytesIO()
                pq.write_table(table, buf, compression="snappy")
                payload = buf.getvalue()
                sha = hashlib.sha256(payload).hexdigest()
                written_bytes = self.backend.write_bytes(target_key, payload)

                meta = {
                    "object_key": target_key,
                    "partition_symbol": symbol,
                    "partition_timeframe": None,
                    "partition_dt": dt_key,
                    "file_format": "PARQUET",
                    "row_count": len(clean),
                    "size_bytes": written_bytes,
                    "sha256": sha,
                    "min_ts": clean[0]["trade_time"],
                    "max_ts": clean[-1]["trade_time"],
                    "is_compacted": False,
                }
                total_rows += len(clean)

                existing = self.backend.list_keys(prefix=part_prefix, suffix=".parquet")
                if auto_compact_threshold > 0 and len(existing) >= auto_compact_threshold:
                    comp_meta = self._compact_trade_partition(
                        part_prefix,
                        existing,
                        dt_key,
                        symbol=symbol,
                        cleanup_replaced=cleanup_replaced,
                    )
                    if comp_meta is not None:
                        compacted_any = True
                        written_files.append(comp_meta["object_key"])
                        file_metas.append(comp_meta)
                        continue

                written_files.append(target_key)
                file_metas.append(meta)

        BATCH_WRITE_LATENCY.labels(layer="silver").observe(time.perf_counter() - t0)
        EVENTS_PERSISTED.labels(layer="silver", symbol=symbol).inc(total_rows)
        return {
            "records": total_rows,
            "files": written_files,
            "file_metas": file_metas,
            "compacted": compacted_any,
        }

    def _compact_trade_partition(
        self,
        prefix: str,
        keys: List[str],
        dt_key: str,
        symbol: Optional[str] = None,
        cleanup_replaced: bool = True,
    ) -> Optional[Dict[str, Any]]:
        merged: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for k in keys:
            try:
                tbl = pq.read_table(io.BytesIO(self.backend.read_bytes(k)))
                for row in tbl.to_pylist():
                    merged[(row["symbol"], int(row["agg_trade_id"]))] = row
            except Exception as exc:
                raise CorruptParquetError(f"Failed reading Silver agg_trade Parquet {k}: {exc}") from exc
        if not merged:
            return None
        rows = sorted(merged.values(), key=lambda x: x["agg_trade_id"])
        table = pa.Table.from_pylist(rows, schema=SILVER_TRADE_SCHEMA)
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        payload = buf.getvalue()
        sha = hashlib.sha256(payload).hexdigest()
        compacted_key = f"{prefix}/compacted-{dt_key}-{uuid.uuid4().hex[:8]}.parquet"
        written_bytes = self.backend.write_bytes(compacted_key, payload)
        if cleanup_replaced:
            for k in keys:
                if k != compacted_key:
                    self.backend.delete(k)
        sym_val = symbol or rows[0]["symbol"]
        return {
            "object_key": compacted_key,
            "partition_symbol": sym_val,
            "partition_timeframe": None,
            "partition_dt": dt_key,
            "file_format": "PARQUET",
            "row_count": len(rows),
            "size_bytes": written_bytes,
            "sha256": sha,
            "min_ts": _parse_dt(rows[0]["trade_time"]),
            "max_ts": _parse_dt(rows[-1]["trade_time"]),
            "is_compacted": True,
        }

    def read_silver_klines_df(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 1000,
        keys_override: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Query Silver Parquet klines via DuckDB (local FS) or PyArrow fallback, deduplicated."""
        symbol_up = symbol.upper()
        tf_low = timeframe.lower()
        if keys_override is not None:
            keys = list(keys_override)
        else:
            prefix = f"{settings.storage.silver_subdir}/source=binance/event_type=klines/timeframe={tf_low}"
            keys = [
                k for k in self.backend.list_keys(prefix=prefix, suffix=".parquet")
                if f"/symbol={symbol_up}/" in k
            ]
        if not keys:
            return pd.DataFrame()

        try:
            local_paths = [_escape_duckdb_path(str(self.backend.local_path(k))) for k in keys]
            with open_bounded_duckdb() as conn:
                files_literal = ", ".join(f"'{p}'" for p in local_paths)
                query = f"""
                    SELECT * FROM (
                        SELECT symbol, timeframe, open_time, close_time, open, high, low, close, volume,
                               quote_asset_volume, number_of_trades, is_closed, source
                        FROM read_parquet([{files_literal}], union_by_name=true)
                        WHERE symbol = ? AND timeframe = ?
                        QUALIFY ROW_NUMBER() OVER (
                            PARTITION BY symbol, timeframe, open_time
                            ORDER BY is_closed DESC, close_time DESC, ingestion_time DESC
                        ) = 1
                        ORDER BY open_time DESC
                        LIMIT ?
                    ) sub
                    ORDER BY open_time ASC
                """
                return conn.execute(query, [symbol_up, tf_low, limit]).df()
        except NotImplementedError:
            frames = [pq.read_table(io.BytesIO(self.backend.read_bytes(k))).to_pandas() for k in keys]
            df = pd.concat(frames, ignore_index=True)
            df = df[(df["symbol"] == symbol_up) & (df["timeframe"] == tf_low)]
            sort_cols = [c for c in ("open_time", "is_closed", "close_time", "ingestion_time") if c in df.columns]
            df = df.sort_values(sort_cols).drop_duplicates(subset=["symbol", "timeframe", "open_time"], keep="last")
            return df.sort_values("open_time").tail(limit).reset_index(drop=True)

    # ------------------------------------------------------------------
    # GOLD LAYER (Real dt= partitioned Parquet Analytical Marts & Features)
    # ------------------------------------------------------------------
    def materialize_gold_marts(
        self,
        symbol: str,
        timeframe: str,
        klines_df: pd.DataFrame,
        cleanup_replaced: bool = True,
    ) -> Dict[str, Any]:
        """Compute and persist real-dt partitioned Gold analytics mart and ML feature Parquet datasets."""
        if klines_df.empty:
            return {
                "rows_in": 0,
                "analytics_rows": 0,
                "feature_rows": 0,
                "files": [],
                "analytics_file_metas": [],
                "feature_file_metas": [],
            }

        t0 = time.perf_counter()
        symbol = symbol.upper()
        timeframe = timeframe.lower()
        root_key = self.backend.resolve_uri("")
        df = klines_df.sort_values("open_time").drop_duplicates(subset=["open_time"], keep="last").reset_index(drop=True)

        ref = compute_batch_reference_metrics(df, timeframe=timeframe)
        series = ref.get("series", {})
        open_dt_series = pd.to_datetime(df["open_time"])
        if getattr(open_dt_series.dt, "tz", None) is not None:
            open_dt_series = open_dt_series.dt.tz_convert("UTC").dt.tz_localize(None)
        open_dt_us = open_dt_series.astype("datetime64[us]")

        analytics_df = pd.DataFrame({
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": open_dt_us,
            "close": df["close"].astype(float),
            "volume": df["volume"].astype(float),
            "simple_return": series["simple_return"].astype(float),
            "log_return": series["log_return"].astype(float),
            "atr_14": series["atr_14"].astype(float),
            "vwap": series["vwap"].astype(float),
            "vol_7_ann_pct": series["vol_7"].astype(float),
            "vol_14_ann_pct": series["vol_14"].astype(float),
            "vol_30_ann_pct": series["vol_30"].astype(float),
            "running_peak": series["running_peak"].astype(float),
            "drawdown_pct": series["drawdown_pct"].astype(float),
        })

        features_df = extract_features(df)
        features_df["open_time"] = open_dt_us
        features_df.insert(0, "symbol", symbol)
        features_df.insert(1, "timeframe", timeframe)
        for col in GOLD_FEATURE_SCHEMA.names:
            if col not in ("symbol", "timeframe", "open_time"):
                features_df[col] = features_df[col].astype(float)

        dt_tags = open_dt_series.dt.strftime("%Y-%m-%d")
        analytics_df["_dt"] = dt_tags.values
        features_df["_dt"] = dt_tags.values

        written_files: List[str] = []
        analytics_metas: List[Dict[str, Any]] = []
        feature_metas: List[Dict[str, Any]] = []

        for dt_key, a_part in analytics_df.groupby("_dt", sort=True):
            f_part = features_df[features_df["_dt"] == dt_key].drop(columns=["_dt"]).reset_index(drop=True)
            a_clean = a_part.drop(columns=["_dt"]).reset_index(drop=True)

            part_lock = _get_partition_lock(root_key, "gold", symbol, timeframe, str(dt_key))
            with part_lock:
                a_prefix = (
                    f"{settings.storage.gold_subdir}/dataset=analytics_marts/"
                    f"timeframe={timeframe}/dt={dt_key}/symbol={symbol}"
                )
                f_prefix = (
                    f"{settings.storage.gold_subdir}/dataset=feature_sets/"
                    f"timeframe={timeframe}/dt={dt_key}/symbol={symbol}"
                )
                old_a_keys = self.backend.list_keys(prefix=a_prefix, suffix=".parquet") if cleanup_replaced else []
                old_f_keys = self.backend.list_keys(prefix=f_prefix, suffix=".parquet") if cleanup_replaced else []

                tag = uuid.uuid4().hex[:8]
                analytics_key = f"{a_prefix}/mart-{dt_key}-{tag}.parquet"
                features_key = f"{f_prefix}/features-{dt_key}-{tag}.parquet"

                a_buf = io.BytesIO()
                pq.write_table(
                    pa.Table.from_pandas(a_clean, schema=GOLD_ANALYTICS_SCHEMA, preserve_index=False),
                    a_buf,
                    compression="snappy",
                )
                a_bytes = a_buf.getvalue()
                a_sha = hashlib.sha256(a_bytes).hexdigest()
                a_written = self.backend.write_bytes(analytics_key, a_bytes)

                f_buf = io.BytesIO()
                pq.write_table(
                    pa.Table.from_pandas(f_part, schema=GOLD_FEATURE_SCHEMA, preserve_index=False),
                    f_buf,
                    compression="snappy",
                )
                f_bytes = f_buf.getvalue()
                f_sha = hashlib.sha256(f_bytes).hexdigest()
                f_written = self.backend.write_bytes(features_key, f_bytes)

                if cleanup_replaced:
                    for old_k in old_a_keys:
                        if old_k != analytics_key:
                            self.backend.delete(old_k)
                    for old_k in old_f_keys:
                        if old_k != features_key:
                            self.backend.delete(old_k)

                min_ts = _parse_dt(a_clean["open_time"].iloc[0].to_pydatetime())
                max_ts = _parse_dt(a_clean["open_time"].iloc[-1].to_pydatetime())
                written_files.extend([analytics_key, features_key])
                analytics_metas.append({
                    "object_key": analytics_key,
                    "partition_symbol": symbol,
                    "partition_timeframe": timeframe,
                    "partition_dt": str(dt_key),
                    "file_format": "PARQUET",
                    "row_count": len(a_clean),
                    "size_bytes": a_written,
                    "sha256": a_sha,
                    "min_ts": min_ts,
                    "max_ts": max_ts,
                    "is_compacted": True,
                })
                feature_metas.append({
                    "object_key": features_key,
                    "partition_symbol": symbol,
                    "partition_timeframe": timeframe,
                    "partition_dt": str(dt_key),
                    "file_format": "PARQUET",
                    "row_count": len(f_part),
                    "size_bytes": f_written,
                    "sha256": f_sha,
                    "min_ts": min_ts,
                    "max_ts": max_ts,
                    "is_compacted": True,
                })

        elapsed = time.perf_counter() - t0
        BATCH_WRITE_LATENCY.labels(layer="gold").observe(elapsed)
        EVENTS_PERSISTED.labels(layer="gold", symbol=symbol).inc(len(analytics_df))
        return {
            "rows_in": len(df),
            "analytics_rows": len(analytics_df),
            "feature_rows": len(features_df),
            "feature_columns": len(features_df.columns) - 5,
            "files": written_files,
            "analytics_file_metas": analytics_metas,
            "feature_file_metas": feature_metas,
            "summary": {
                "var_95_pct": ref.get("var_95_pct"),
                "cvar_95_pct": ref.get("cvar_95_pct"),
                "max_drawdown_pct": ref.get("max_drawdown_pct"),
                "vwap": ref.get("vwap"),
                "atr_14": ref.get("atr_14"),
            },
            "duration_seconds": round(elapsed, 4),
        }

    def read_gold_dataset(
        self,
        dataset: str,
        symbol: Optional[str] = None,
        limit: int = 200,
        keys_override: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Query Gold Parquet datasets via DuckDB, deduplicating across partitions."""
        if keys_override is not None:
            keys = list(keys_override)
        else:
            prefix = f"{settings.storage.gold_subdir}/dataset={dataset}"
            keys = self.backend.list_keys(prefix=prefix, suffix=".parquet")
            if symbol:
                keys = [k for k in keys if f"/symbol={symbol.upper()}/" in k]
        if not keys:
            return []

        try:
            local_paths = [_escape_duckdb_path(str(self.backend.local_path(k))) for k in keys]
            files_literal = ", ".join(f"'{p}'" for p in local_paths)
            with open_bounded_duckdb() as conn:
                rel = conn.execute(
                    f"""
                    SELECT * FROM read_parquet([{files_literal}], union_by_name=true)
                    QUALIFY ROW_NUMBER() OVER (
                        PARTITION BY symbol, timeframe, open_time
                        ORDER BY open_time DESC
                    ) = 1
                    ORDER BY open_time DESC
                    LIMIT ?
                    """,
                    [limit],
                )
                cols = [d[0] for d in rel.description]
                rows = []
                for row in rel.fetchall():
                    rec = {}
                    for col, val in zip(cols, row):
                        if isinstance(val, datetime):
                            rec[col] = val.isoformat()
                        elif isinstance(val, float) and pd.isna(val):
                            rec[col] = None
                        else:
                            rec[col] = val
                    rows.append(rec)
                return rows
        except NotImplementedError:
            frames = [pq.read_table(io.BytesIO(self.backend.read_bytes(k))).to_pandas() for k in keys]
            df = pd.concat(frames, ignore_index=True)
            df = df.drop_duplicates(subset=["symbol", "timeframe", "open_time"], keep="last")
            df = df.sort_values("open_time", ascending=False).head(limit)
            return json.loads(df.to_json(orient="records", date_format="iso"))

    # ------------------------------------------------------------------
    # SQL MANIFESTS, COMPACTION & GRACE-TTL GARBAGE COLLECTION
    # ------------------------------------------------------------------
    async def commit_manifest(
        self,
        db: AsyncSession,
        dataset_id: str,
        new_file_metas: List[Dict[str, Any]],
        schema_version: str,
        schema_hash: str,
        batch_type: str = "LAKE_WRITE",
        producer_name: str = "medallion_manager",
        idempotency_key: Optional[str] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        replace_partitions: bool = True,
        batch_id: Optional[str] = None,
        nats_seq_start: Optional[int] = None,
        nats_seq_end: Optional[int] = None,
        records_received: Optional[int] = None,
        records_rejected: int = 0,
    ) -> LakeSnapshot:
        """Atomically publish a new ACTIVE LakeSnapshot + LakeManifestFile set in SQL."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        idem = idempotency_key or f"{dataset_id}:{batch_type}:{uuid.uuid4().hex}"

        prev_snap = (
            await db.execute(
                select(LakeSnapshot)
                .where(and_(LakeSnapshot.dataset_id == dataset_id, LakeSnapshot.status == "ACTIVE"))
                .order_by(desc(LakeSnapshot.version_seq))
                .limit(1)
            )
        ).scalar_one_or_none()

        max_ver = await db.scalar(
            select(func.max(LakeSnapshot.version_seq)).where(LakeSnapshot.dataset_id == dataset_id)
        )
        next_ver = int(max_ver or 0) + 1

        # Build carried-forward file inventory
        carried: List[Dict[str, Any]] = []
        replaced_keys = {
            (m.get("partition_symbol"), m.get("partition_timeframe"), m.get("partition_dt"))
            for m in new_file_metas
        }
        if prev_snap is not None:
            prev_files = (
                await db.execute(
                    select(LakeManifestFile).where(LakeManifestFile.snapshot_id == prev_snap.snapshot_id)
                )
            ).scalars().all()
            for pf in prev_files:
                part_id = (pf.partition_symbol, pf.partition_timeframe, pf.partition_dt)
                if replace_partitions and part_id in replaced_keys:
                    continue
                carried.append({
                    "object_key": pf.object_key,
                    "partition_symbol": pf.partition_symbol,
                    "partition_timeframe": pf.partition_timeframe,
                    "partition_dt": pf.partition_dt,
                    "file_format": pf.file_format,
                    "row_count": pf.row_count,
                    "size_bytes": pf.size_bytes,
                    "sha256": pf.sha256,
                    "min_ts": pf.min_ts,
                    "max_ts": pf.max_ts,
                    "is_compacted": pf.is_compacted,
                })

        all_files = carried + list(new_file_metas)
        dedup_files: Dict[str, Dict[str, Any]] = {}
        for fmeta in all_files:
            dedup_files[fmeta["object_key"]] = fmeta
        final_files = list(dedup_files.values())

        total_rows = sum(int(f["row_count"]) for f in final_files)
        total_bytes = sum(int(f["size_bytes"]) for f in final_files)
        min_ev = min((f["min_ts"] for f in final_files if f.get("min_ts") is not None), default=None)
        max_ev = max((f["max_ts"] for f in final_files if f.get("max_ts") is not None), default=None)

        snapshot_id = str(uuid.uuid4())
        staged_keys = [m["object_key"] for m in new_file_metas]
        written_new_rows = sum(int(m["row_count"]) for m in new_file_metas)

        ledger: Optional[BatchLedger] = None
        if batch_id:
            ledger = await db.get(BatchLedger, batch_id)
        if ledger is None:
            ledger = BatchLedger(
                batch_id=batch_id or str(uuid.uuid4()),
                batch_type=batch_type,
                producer_name=producer_name,
                symbol=symbol.upper() if symbol else None,
                timeframe=timeframe.lower() if timeframe else None,
                idempotency_key=idem,
                status="COMMITTED",
                nats_seq_start=nats_seq_start,
                nats_seq_end=nats_seq_end,
                records_received=records_received if records_received is not None else written_new_rows,
                records_written=written_new_rows,
                records_rejected=records_rejected,
                staged_keys_json=json.dumps(staged_keys),
                snapshot_id=snapshot_id,
                created_at=now,
                committed_at=now,
            )
            db.add(ledger)
            await db.flush()
        else:
            ledger.status = "COMMITTED"
            ledger.snapshot_id = snapshot_id
            ledger.records_written = written_new_rows
            ledger.staged_keys_json = json.dumps(staged_keys)
            ledger.committed_at = now

        if prev_snap is not None:
            prev_snap.status = "SUPERSEDED"

        snap = LakeSnapshot(
            snapshot_id=snapshot_id,
            dataset_id=dataset_id,
            version_seq=next_ver,
            parent_snapshot_id=prev_snap.snapshot_id if prev_snap else None,
            schema_version=schema_version,
            schema_hash=schema_hash,
            batch_id=ledger.batch_id,
            status="ACTIVE",
            total_files=len(final_files),
            total_rows=total_rows,
            total_bytes=total_bytes,
            min_event_time=min_ev,
            max_event_time=max_ev,
            created_at=now,
            published_at=now,
        )
        db.add(snap)
        await db.flush()

        for fmeta in final_files:
            db.add(LakeManifestFile(
                snapshot_id=snapshot_id,
                object_key=fmeta["object_key"],
                partition_symbol=fmeta.get("partition_symbol"),
                partition_timeframe=fmeta.get("partition_timeframe"),
                partition_dt=fmeta.get("partition_dt"),
                file_format=fmeta["file_format"],
                row_count=int(fmeta["row_count"]),
                size_bytes=int(fmeta["size_bytes"]),
                sha256=fmeta["sha256"],
                min_ts=fmeta.get("min_ts"),
                max_ts=fmeta.get("max_ts"),
                is_compacted=bool(fmeta.get("is_compacted", False)),
                created_at=now,
            ))

        cat_entry = await db.get(DataCatalogEntry, dataset_id)
        if cat_entry is not None:
            cat_entry.row_count = total_rows
            cat_entry.size_bytes = total_bytes
            cat_entry.version = schema_version
            cat_entry.active_snapshot_id = snapshot_id
            cat_entry.schema_hash = schema_hash
            cat_entry.updated_at = now

        await db.flush()
        return snap

    async def publish_lake_snapshot(
        self,
        db: AsyncSession,
        dataset_id: str,
        new_file_metas: List[Dict[str, Any]],
        schema_version: str = SILVER_KLINE_SCHEMA_VERSION,
        schema_hash: Optional[str] = None,
        **kwargs: Any,
    ) -> LakeSnapshot:
        """Alias wrapper around commit_manifest deriving schema_hash if omitted."""
        resolved_hash = schema_hash or _schema_hash(SILVER_KLINE_SCHEMA)
        return await self.commit_manifest(
            db=db,
            dataset_id=dataset_id,
            new_file_metas=new_file_metas,
            schema_version=schema_version,
            schema_hash=resolved_hash,
            **kwargs,
        )

    async def get_active_manifest_keys(
        self,
        db: AsyncSession,
        dataset_id: str,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        dt_key: Optional[str] = None,
    ) -> List[str]:
        """Return object keys belonging to the currently ACTIVE LakeSnapshot."""
        snap = (
            await db.execute(
                select(LakeSnapshot)
                .where(and_(LakeSnapshot.dataset_id == dataset_id, LakeSnapshot.status == "ACTIVE"))
                .order_by(desc(LakeSnapshot.version_seq))
                .limit(1)
            )
        ).scalar_one_or_none()
        if snap is None:
            return []
        stmt = select(LakeManifestFile.object_key).where(LakeManifestFile.snapshot_id == snap.snapshot_id)
        if symbol:
            stmt = stmt.where(LakeManifestFile.partition_symbol == symbol.upper())
        if timeframe:
            stmt = stmt.where(LakeManifestFile.partition_timeframe == timeframe.lower())
        if dt_key:
            stmt = stmt.where(LakeManifestFile.partition_dt == dt_key)
        stmt = stmt.order_by(LakeManifestFile.object_key.asc())
        return list((await db.execute(stmt)).scalars().all())

    async def compact_silver_trades(
        self,
        db: AsyncSession,
        symbol: str,
        dt_key: str,
        cleanup_replaced: bool = False,
    ) -> Optional[LakeSnapshot]:
        """Compact all silver_agg_trades fragments for (symbol, dt_key) into a new ACTIVE snapshot."""
        symbol_up = symbol.upper()
        part_prefix = f"{settings.storage.silver_subdir}/source=binance/event_type=agg_trades/dt={dt_key}/symbol={symbol_up}"
        manifest_keys = await self.get_active_manifest_keys(
            db, "silver_agg_trades", symbol=symbol_up, dt_key=dt_key
        )
        keys = manifest_keys or self.backend.list_keys(prefix=part_prefix, suffix=".parquet")
        if len(keys) <= 1:
            return None
        comp_meta = self._compact_trade_partition(
            part_prefix,
            keys,
            dt_key,
            symbol=symbol_up,
            cleanup_replaced=cleanup_replaced,
        )
        if comp_meta is None:
            return None
        return await self.commit_manifest(
            db=db,
            dataset_id="silver_agg_trades",
            new_file_metas=[comp_meta],
            schema_version=SILVER_TRADE_SCHEMA_VERSION,
            schema_hash=_schema_hash(SILVER_TRADE_SCHEMA),
            batch_type="PARQUET_COMPACTION",
            producer_name="medallion_compactor",
            symbol=symbol_up,
            replace_partitions=True,
        )

    async def compact_silver_klines(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        dt_key: str,
        cleanup_replaced: bool = False,
    ) -> Optional[LakeSnapshot]:
        """Compact all silver_klines fragments for (symbol, timeframe, dt_key) into one compacted file."""
        symbol_up = symbol.upper()
        tf_low = timeframe.lower()
        part_prefix = (
            f"{settings.storage.silver_subdir}/source=binance/event_type=klines/"
            f"timeframe={tf_low}/dt={dt_key}/symbol={symbol_up}"
        )
        manifest_keys = await self.get_active_manifest_keys(
            db, "silver_klines", symbol=symbol_up, timeframe=tf_low, dt_key=dt_key
        )
        keys = manifest_keys or self.backend.list_keys(prefix=part_prefix, suffix=".parquet")
        if not keys:
            return None
        merged: Dict[Tuple[str, str, datetime], Dict[str, Any]] = {}
        for k in keys:
            try:
                tbl = pq.read_table(io.BytesIO(self.backend.read_bytes(k)))
                for row in tbl.to_pylist():
                    norm = self._normalize_silver_kline_row(row, symbol_up, tf_low)
                    rk = (norm["symbol"], norm["timeframe"], norm["open_time"])
                    merged[rk] = merge_kline_records(merged.get(rk), norm, force_reconcile=False)
            except Exception as exc:
                raise CorruptParquetError(f"Failed reading Silver kline Parquet {k}: {exc}") from exc
        if not merged:
            return None
        rows = sorted(merged.values(), key=lambda x: x["open_time"])
        table = pa.Table.from_pylist(rows, schema=SILVER_KLINE_SCHEMA)
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        payload = buf.getvalue()
        sha = hashlib.sha256(payload).hexdigest()
        compacted_key = f"{part_prefix}/compacted-{dt_key}-{uuid.uuid4().hex[:8]}.parquet"
        written_bytes = self.backend.write_bytes(compacted_key, payload)
        if cleanup_replaced:
            for k in keys:
                if k != compacted_key:
                    self.backend.delete(k)
        comp_meta = {
            "object_key": compacted_key,
            "partition_symbol": symbol_up,
            "partition_timeframe": tf_low,
            "partition_dt": dt_key,
            "file_format": "PARQUET",
            "row_count": len(rows),
            "size_bytes": written_bytes,
            "sha256": sha,
            "min_ts": rows[0]["open_time"],
            "max_ts": rows[-1]["open_time"],
            "is_compacted": True,
        }
        return await self.commit_manifest(
            db=db,
            dataset_id="silver_klines",
            new_file_metas=[comp_meta],
            schema_version=SILVER_KLINE_SCHEMA_VERSION,
            schema_hash=_schema_hash(SILVER_KLINE_SCHEMA),
            batch_type="PARQUET_COMPACTION",
            producer_name="medallion_compactor",
            symbol=symbol_up,
            timeframe=tf_low,
            replace_partitions=True,
        )

    async def gc_superseded_objects(
        self,
        db: AsyncSession,
        dataset_id: Optional[str] = None,
        retain_snapshots: Optional[int] = None,
        grace_ttl_sec: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Safely delete superseded Parquet/Bronze objects outside retained snapshots & grace TTL."""
        keep_n = retain_snapshots if retain_snapshots is not None else settings.warehouse.retain_snapshots
        grace_sec = grace_ttl_sec if grace_ttl_sec is not None else settings.warehouse.reader_grace_ttl_sec
        cutoff_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=grace_sec)

        ds_stmt = select(LakeSnapshot.dataset_id).distinct()
        if dataset_id:
            ds_stmt = ds_stmt.where(LakeSnapshot.dataset_id == dataset_id)
        dataset_ids = list((await db.execute(ds_stmt)).scalars().all())

        protected_keys: set[str] = set()
        candidate_keys: set[str] = set()
        expired_snapshots = 0

        for did in dataset_ids:
            snaps = list((
                await db.execute(
                    select(LakeSnapshot)
                    .where(LakeSnapshot.dataset_id == did)
                    .order_by(desc(LakeSnapshot.version_seq))
                )
            ).scalars().all())

            superseded_kept = 0
            for s in snaps:
                f_keys = list((
                    await db.execute(
                        select(LakeManifestFile.object_key).where(LakeManifestFile.snapshot_id == s.snapshot_id)
                    )
                ).scalars().all())
                if s.status in ("ACTIVE", "STAGING"):
                    protected_keys.update(f_keys)
                elif s.status == "SUPERSEDED":
                    ref_ts = s.published_at or s.created_at
                    if superseded_kept < keep_n or ref_ts > cutoff_dt:
                        protected_keys.update(f_keys)
                        superseded_kept += 1
                    else:
                        candidate_keys.update(f_keys)
                        s.status = "EXPIRED"
                        expired_snapshots += 1
                elif s.status == "EXPIRED":
                    candidate_keys.update(f_keys)

        deleted = 0
        freed_bytes = 0
        for obj_key in sorted(candidate_keys - protected_keys):
            meta = self.backend.head_object(obj_key)
            if meta is None:
                continue
            if meta.last_modified_utc > cutoff_dt:
                continue
            if self.backend.delete(obj_key):
                deleted += 1
                freed_bytes += meta.size_bytes

        await db.flush()
        return {
            "expired_snapshots": expired_snapshots,
            "deleted_objects": deleted,
            "freed_bytes": freed_bytes,
        }

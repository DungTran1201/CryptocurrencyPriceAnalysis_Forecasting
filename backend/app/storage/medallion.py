"""Real Medallion Storage Engine: Bronze (zstd JSONL), Silver (Parquet), Gold (DuckDB + Parquet)."""

from datetime import datetime, timezone
import io
import json
import time
from typing import Any, Dict, List, Optional
import uuid
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import zstandard as zstd

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.core.metrics import BATCH_WRITE_LATENCY, EVENTS_PERSISTED
from backend.app.storage import StorageBackend, get_storage_backend
from backend.app.storage.duckdb_engine import open_bounded_duckdb
from ml.features import extract_features
from ml.incremental_analytics import compute_batch_reference_metrics

logger = get_logger("MedallionStorage")

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
    ("is_closed", pa.bool_()),
    ("source", pa.string()),
    ("ingestion_time", pa.timestamp("us")),
])

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


def _parse_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val.replace(tzinfo=None) if val.tzinfo else val
    dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


class MedallionStorageManager:
    """Manages Bronze raw archival, Silver Parquet partitioning/compaction, and Gold marts."""

    def __init__(self, backend: Optional[StorageBackend] = None):
        self.backend = backend or get_storage_backend()
        self._compressor = zstd.ZstdCompressor(level=3)
        self._decompressor = zstd.ZstdDecompressor()

    # ------------------------------------------------------------------
    # BRONZE LAYER (Immutable zstd-compressed JSONL micro-batches)
    # ------------------------------------------------------------------
    def write_bronze_batch(
        self,
        stream_name: str,
        symbol: str,
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Compress and persist immutable raw event records to Bronze storage."""
        if not records:
            return {"key": None, "records": 0, "bytes": 0}

        t0 = time.perf_counter()
        now = datetime.now(timezone.utc)
        dt_str = now.strftime("%Y-%m-%d")
        ts_str = now.strftime("%Y%m%dT%H%M%S")
        key = (
            f"{settings.storage.bronze_subdir}/source=binance/stream={stream_name.lower()}/"
            f"dt={dt_str}/symbol={symbol.upper()}/part-{ts_str}-{uuid.uuid4().hex[:8]}.jsonl.zst"
        )
        lines = [json.dumps(r, default=str, ensure_ascii=True) for r in records]
        raw_bytes = ("\n".join(lines) + "\n").encode("utf-8")
        compressed = self._compressor.compress(raw_bytes)
        written_bytes = self.backend.write_bytes(key, compressed)

        BATCH_WRITE_LATENCY.labels(layer="bronze").observe(time.perf_counter() - t0)
        EVENTS_PERSISTED.labels(layer="bronze", symbol=symbol.upper()).inc(len(records))
        return {
            "key": key,
            "uri": self.backend.resolve_uri(key),
            "records": len(records),
            "raw_bytes": len(raw_bytes),
            "bytes": written_bytes,
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
    # SILVER LAYER (Validated, deduplicated partitioned Parquet)
    # ------------------------------------------------------------------
    def write_silver_klines(
        self,
        symbol: str,
        timeframe: str,
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Deduplicate and persist validated OHLCV klines to partitioned Silver Parquet."""
        if not records:
            return {"records": 0, "files": []}

        t0 = time.perf_counter()
        symbol = symbol.upper()
        timeframe = timeframe.lower()

        # Group by UTC date partition
        by_date: Dict[str, List[Dict[str, Any]]] = {}
        for r in records:
            open_dt = _parse_dt(r["open_time"])
            close_dt = _parse_dt(r["close_time"])
            ing_dt = _parse_dt(r.get("ingestion_time") or datetime.now(timezone.utc))
            # Enforce OHLC geometry validation before writing Silver
            o, h, l, c, v = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["volume"])
            if h < l or h < o or h < c or l > o or l > c or v < 0:
                continue
            dt_key = open_dt.strftime("%Y-%m-%d")
            by_date.setdefault(dt_key, []).append({
                "symbol": symbol,
                "timeframe": timeframe,
                "open_time": open_dt,
                "close_time": close_dt,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "quote_asset_volume": float(r["quote_asset_volume"]) if r.get("quote_asset_volume") is not None else None,
                "number_of_trades": int(r["number_of_trades"]) if r.get("number_of_trades") is not None else None,
                "is_closed": bool(r.get("is_closed", True)),
                "source": str(r.get("source", "binance")),
                "ingestion_time": ing_dt,
            })

        written_files: List[str] = []
        total_rows = 0
        for dt_key, batch in by_date.items():
            # Deduplicate inside batch by (symbol, timeframe, open_time), keeping latest
            dedup_map = {(b["symbol"], b["timeframe"], b["open_time"]): b for b in batch}
            clean_batch = sorted(dedup_map.values(), key=lambda x: x["open_time"])
            if not clean_batch:
                continue

            part_prefix = (
                f"{settings.storage.silver_subdir}/source=binance/event_type=klines/"
                f"timeframe={timeframe}/dt={dt_key}/symbol={symbol}"
            )
            existing_keys = self.backend.list_keys(prefix=part_prefix, suffix=".parquet")

            # Merge with existing daily partition file to preserve strict uniqueness and avoid tiny files
            merged_rows: Dict[Any, Dict[str, Any]] = {}
            for old_key in existing_keys:
                try:
                    old_table = pq.read_table(io.BytesIO(self.backend.read_bytes(old_key)))
                    for row in old_table.to_pylist():
                        merged_rows[(row["symbol"], row["timeframe"], _parse_dt(row["open_time"]))] = row
                except Exception as exc:
                    logger.warning(f"Skipping unreadable Silver Parquet {old_key}: {exc}")

            for item in clean_batch:
                merged_rows[(item["symbol"], item["timeframe"], item["open_time"])] = item

            final_list = sorted(merged_rows.values(), key=lambda x: x["open_time"])
            table = pa.Table.from_pylist(final_list, schema=SILVER_KLINE_SCHEMA)
            buf = io.BytesIO()
            pq.write_table(table, buf, compression="snappy")

            target_key = f"{part_prefix}/part-{dt_key}.parquet"
            self.backend.write_bytes(target_key, buf.getvalue())
            # Clean up superseded fragment files if any
            for old_key in existing_keys:
                if old_key != target_key:
                    self.backend.delete(old_key)

            written_files.append(target_key)
            total_rows += len(clean_batch)

        BATCH_WRITE_LATENCY.labels(layer="silver").observe(time.perf_counter() - t0)
        EVENTS_PERSISTED.labels(layer="silver", symbol=symbol).inc(total_rows)
        return {"records": total_rows, "files": written_files}

    def write_silver_trades(self, symbol: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Persist micro-batch validated aggTrade events into partitioned Silver Parquet."""
        if not records:
            return {"records": 0, "files": []}

        t0 = time.perf_counter()
        symbol = symbol.upper()
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
        total_rows = 0
        now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        for dt_key, batch in by_date.items():
            dedup = {(b["symbol"], b["agg_trade_id"]): b for b in batch}
            clean = sorted(dedup.values(), key=lambda x: x["agg_trade_id"])
            part_prefix = f"{settings.storage.silver_subdir}/source=binance/event_type=agg_trades/dt={dt_key}/symbol={symbol}"
            target_key = f"{part_prefix}/part-{now_str}-{uuid.uuid4().hex[:8]}.parquet"
            table = pa.Table.from_pylist(clean, schema=SILVER_TRADE_SCHEMA)
            buf = io.BytesIO()
            pq.write_table(table, buf, compression="snappy")
            self.backend.write_bytes(target_key, buf.getvalue())
            written_files.append(target_key)
            total_rows += len(clean)

            # Bounded compaction when fragment count reaches threshold (>= 6 small files)
            existing = self.backend.list_keys(prefix=part_prefix, suffix=".parquet")
            if len(existing) >= 6:
                self._compact_trade_partition(part_prefix, existing, dt_key)

        BATCH_WRITE_LATENCY.labels(layer="silver").observe(time.perf_counter() - t0)
        EVENTS_PERSISTED.labels(layer="silver", symbol=symbol).inc(total_rows)
        return {"records": total_rows, "files": written_files}

    def _compact_trade_partition(self, prefix: str, keys: List[str], dt_key: str) -> None:
        merged: Dict[Any, Dict[str, Any]] = {}
        for k in keys:
            try:
                tbl = pq.read_table(io.BytesIO(self.backend.read_bytes(k)))
                for row in tbl.to_pylist():
                    merged[(row["symbol"], int(row["agg_trade_id"]))] = row
            except Exception:
                pass
        if not merged:
            return
        rows = sorted(merged.values(), key=lambda x: x["agg_trade_id"])
        table = pa.Table.from_pylist(rows, schema=SILVER_TRADE_SCHEMA)
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        compacted_key = f"{prefix}/compacted-{dt_key}.parquet"
        self.backend.write_bytes(compacted_key, buf.getvalue())
        for k in keys:
            if k != compacted_key:
                self.backend.delete(k)

    def read_silver_klines_df(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Query Silver Parquet klines via DuckDB (local FS) or PyArrow fallback."""
        prefix = f"{settings.storage.silver_subdir}/source=binance/event_type=klines/timeframe={timeframe.lower()}"
        keys = [
            k for k in self.backend.list_keys(prefix=prefix, suffix=".parquet")
            if f"/symbol={symbol.upper()}/" in k
        ]
        if not keys:
            return pd.DataFrame()

        try:
            local_paths = [str(self.backend.local_path(k)).replace("\\", "/") for k in keys]
            with open_bounded_duckdb() as conn:
                files_literal = ", ".join(f"'{p}'" for p in local_paths)
                query = f"""
                    SELECT * FROM (
                        SELECT symbol, timeframe, open_time, close_time, open, high, low, close, volume,
                               quote_asset_volume, number_of_trades, is_closed, source
                        FROM read_parquet([{files_literal}], union_by_name=true)
                        WHERE symbol = ? AND timeframe = ?
                        ORDER BY open_time DESC
                        LIMIT ?
                    ) sub
                    ORDER BY open_time ASC
                """
                return conn.execute(query, [symbol.upper(), timeframe.lower(), limit]).df()
        except NotImplementedError:
            frames = [pq.read_table(io.BytesIO(self.backend.read_bytes(k))).to_pandas() for k in keys]
            df = pd.concat(frames, ignore_index=True)
            df = df[(df["symbol"] == symbol.upper()) & (df["timeframe"] == timeframe.lower())]
            return df.sort_values("open_time").tail(limit).reset_index(drop=True)

    # ------------------------------------------------------------------
    # GOLD LAYER (Materialized Parquet Analytical Marts & Feature Sets)
    # ------------------------------------------------------------------
    def materialize_gold_marts(
        self,
        symbol: str,
        timeframe: str,
        klines_df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """Compute and persist real Gold analytics mart and ML feature Parquet datasets."""
        if klines_df.empty:
            return {"rows_in": 0, "analytics_rows": 0, "feature_rows": 0, "files": []}

        t0 = time.perf_counter()
        symbol = symbol.upper()
        timeframe = timeframe.lower()
        df = klines_df.sort_values("open_time").drop_duplicates(subset=["open_time"], keep="last").reset_index(drop=True)

        ref = compute_batch_reference_metrics(df, timeframe=timeframe)
        series = ref.get("series", {})
        analytics_df = pd.DataFrame({
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": pd.to_datetime(df["open_time"]),
            "close": df["close"].astype(float),
            "volume": df["volume"].astype(float),
            "simple_return": series["simple_return"],
            "log_return": series["log_return"],
            "atr_14": series["atr_14"],
            "vwap": series["vwap"],
            "vol_7_ann_pct": series["vol_7"],
            "vol_14_ann_pct": series["vol_14"],
            "vol_30_ann_pct": series["vol_30"],
            "running_peak": series["running_peak"],
            "drawdown_pct": series["drawdown_pct"],
        })

        features_df = extract_features(df)
        features_df.insert(0, "symbol", symbol)
        features_df.insert(1, "timeframe", timeframe)

        date_tag = pd.to_datetime(df["open_time"]).max().strftime("%Y-%m-%d")
        analytics_key = (
            f"{settings.storage.gold_subdir}/dataset=analytics_marts/"
            f"timeframe={timeframe}/dt={date_tag}/symbol={symbol}/mart.parquet"
        )
        features_key = (
            f"{settings.storage.gold_subdir}/dataset=feature_sets/"
            f"timeframe={timeframe}/dt={date_tag}/symbol={symbol}/features.parquet"
        )

        a_buf = io.BytesIO()
        pq.write_table(pa.Table.from_pandas(analytics_df, preserve_index=False), a_buf, compression="snappy")
        self.backend.write_bytes(analytics_key, a_buf.getvalue())

        f_buf = io.BytesIO()
        pq.write_table(pa.Table.from_pandas(features_df, preserve_index=False), f_buf, compression="snappy")
        self.backend.write_bytes(features_key, f_buf.getvalue())

        elapsed = time.perf_counter() - t0
        BATCH_WRITE_LATENCY.labels(layer="gold").observe(elapsed)
        EVENTS_PERSISTED.labels(layer="gold", symbol=symbol).inc(len(analytics_df))
        return {
            "rows_in": len(df),
            "analytics_rows": len(analytics_df),
            "feature_rows": len(features_df),
            "feature_columns": len(features_df.columns) - 4,
            "files": [analytics_key, features_key],
            "summary": {
                "var_95_pct": ref.get("var_95_pct"),
                "cvar_95_pct": ref.get("cvar_95_pct"),
                "max_drawdown_pct": ref.get("max_drawdown_pct"),
                "vwap": ref.get("vwap"),
                "atr_14": ref.get("atr_14"),
            },
            "duration_seconds": round(elapsed, 4),
        }

    def read_gold_dataset(self, dataset: str, symbol: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        """Query Gold Parquet datasets via DuckDB."""
        prefix = f"{settings.storage.gold_subdir}/dataset={dataset}"
        keys = self.backend.list_keys(prefix=prefix, suffix=".parquet")
        if symbol:
            keys = [k for k in keys if f"/symbol={symbol.upper()}/" in k]
        if not keys:
            return []

        try:
            local_paths = [str(self.backend.local_path(k)).replace("\\", "/") for k in keys]
            files_literal = ", ".join(f"'{p}'" for p in local_paths)
            with open_bounded_duckdb() as conn:
                rel = conn.execute(
                    f"SELECT * FROM read_parquet([{files_literal}], union_by_name=true) ORDER BY open_time DESC LIMIT ?",
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
            df = pd.concat(frames, ignore_index=True).sort_values("open_time", ascending=False).head(limit)
            return json.loads(df.to_json(orient="records", date_format="iso"))


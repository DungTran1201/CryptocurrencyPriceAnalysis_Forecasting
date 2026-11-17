"""Persistent DuckDB Data Warehouse Engine with Snapshot Swap & Star Schema (ADR-DP-004).

Implements:
- Star schema DDL: dim_symbols, dim_time, fact_market_klines_1m, fact_market_aggtrades, fact_model_forecasts, agg_kline_daily_marts
- Staging-to-snapshot copy swap eliminating Windows file locking conflicts
- Concurrent read_only connections over active versioned snapshots
- Resource-bounded query execution adhering to active profile memory & thread limits
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Dict, Iterator, List, Optional
import duckdb

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.core.metrics import WAREHOUSE_QUERY_LATENCY
from backend.app.storage import get_data_root

logger = get_logger("DuckDBWarehouse")

# Canonical Star Schema DDL
DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS dim_symbols (
        symbol VARCHAR PRIMARY KEY,
        base_asset VARCHAR,
        quote_asset VARCHAR,
        is_active BOOLEAN DEFAULT TRUE,
        first_seen_at TIMESTAMP,
        last_seen_at TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_time (
        time_key BIGINT PRIMARY KEY,
        ts TIMESTAMP,
        year INT,
        month INT,
        day INT,
        hour INT,
        minute INT,
        day_of_week INT,
        is_weekend BOOLEAN
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_market_klines_1m (
        symbol VARCHAR,
        timeframe VARCHAR,
        open_time TIMESTAMP,
        close_time TIMESTAMP,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        close DOUBLE,
        volume DOUBLE,
        quote_asset_volume DOUBLE,
        number_of_trades BIGINT,
        taker_buy_base_asset_volume DOUBLE,
        taker_buy_quote_asset_volume DOUBLE,
        is_closed BOOLEAN,
        PRIMARY KEY (symbol, timeframe, open_time)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_market_aggtrades (
        symbol VARCHAR,
        agg_trade_id BIGINT,
        price DOUBLE,
        quantity DOUBLE,
        quote_quantity DOUBLE,
        is_buyer_maker BOOLEAN,
        trade_time TIMESTAMP,
        PRIMARY KEY (symbol, agg_trade_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_model_forecasts (
        forecast_id VARCHAR PRIMARY KEY,
        symbol VARCHAR,
        model_id VARCHAR,
        horizon_minutes INT,
        target_time TIMESTAMP,
        predicted_price DOUBLE,
        lower_bound DOUBLE,
        upper_bound DOUBLE,
        actual_price DOUBLE,
        absolute_error DOUBLE,
        created_at TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS agg_kline_daily_marts (
        symbol VARCHAR,
        dt DATE,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        close DOUBLE,
        volume DOUBLE,
        vwap DOUBLE,
        quote_volume DOUBLE,
        trade_count BIGINT,
        PRIMARY KEY (symbol, dt)
    );
    """,
]


class DuckDBWarehouseEngine:
    """Manages the lifecycle of persistent DuckDB analytical warehouse snapshots."""

    _write_lock = threading.Lock()

    def __init__(self, warehouse_dir: Optional[Path] = None):
        self.warehouse_dir = Path(warehouse_dir) if warehouse_dir else (get_data_root() / "warehouse")
        self.staging_dir = self.warehouse_dir / "staging"
        self.snapshots_dir = self.warehouse_dir / "snapshots"
        self.manifest_file = self.warehouse_dir / "active_snapshot.json"

        self.warehouse_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def get_active_manifest(self) -> Optional[Dict[str, Any]]:
        """Read active snapshot metadata JSON."""
        if not self.manifest_file.exists():
            return None
        try:
            return json.loads(self.manifest_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed reading warehouse active manifest: %s", exc)
            return None

    def get_active_snapshot_path(self) -> Optional[Path]:
        """Return the absolute path to the active readable snapshot if available."""
        manifest = self.get_active_manifest()
        if not manifest or "path" not in manifest:
            # Fallback check for any existing snapshot in snapshots/
            snaps = sorted(self.snapshots_dir.glob("dw-v*.duckdb"))
            return snaps[-1] if snaps else None
        p = Path(manifest["path"])
        return p if p.exists() else None

    @contextmanager
    def open_reader(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Open a read-only DuckDB connection against the active snapshot."""
        snap_path = self.get_active_snapshot_path()
        if snap_path is None:
            # No snapshot built yet; fall back to an ephemeral memory connection
            conn = duckdb.connect(database=":memory:", read_only=False)
            try:
                conn.execute(f"SET memory_limit='{settings.resources.duckdb_memory_limit}';")
                conn.execute(f"SET threads={int(settings.resources.duckdb_threads)};")
                for ddl in DDL_STATEMENTS:
                    conn.execute(ddl)
                yield conn
            finally:
                conn.close()
            return

        conn = duckdb.connect(database=str(snap_path), read_only=True)
        try:
            conn.execute(f"SET memory_limit='{settings.resources.duckdb_memory_limit}';")
            conn.execute(f"SET threads={int(settings.resources.duckdb_threads)};")
            yield conn
        finally:
            conn.close()

    def query(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Execute a read-only SQL query against the warehouse snapshot."""
        t0 = time.perf_counter()
        with self.open_reader() as conn:
            rel = conn.execute(sql, params or [])
            cols = [d[0] for d in rel.description] if rel.description else []
            rows = rel.fetchall()
            duration = time.perf_counter() - t0
            WAREHOUSE_QUERY_LATENCY.observe(duration)
            return [dict(zip(cols, r)) for r in rows]

    def build_snapshot(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        silver_root: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Materialize a new immutable DuckDB snapshot from Silver Parquet datasets.

        Uses the staging-checkpoint-close-copy pattern:
        1. Single writer exclusive lock
        2. Build tables in staging/dw_staging.duckdb
        3. Ingest Silver Parquet files
        4. Populate daily aggregated analytical marts
        5. CHECKPOINT and close() staging connection
        6. Copy staging file to snapshots/dw-v{version}.duckdb
        7. Atomically replace active_snapshot.json manifest
        """
        t0 = time.perf_counter()
        with self._write_lock:
            staging_db = self.staging_dir / "dw_staging.duckdb"
            if staging_db.exists():
                try:
                    staging_db.unlink()
                except OSError:
                    pass

            writer_conn = duckdb.connect(database=str(staging_db), read_only=False)
            total_klines = 0
            total_trades = 0
            daily_marts = 0

            try:
                writer_conn.execute(f"SET memory_limit='{settings.resources.duckdb_memory_limit}';")
                writer_conn.execute(f"SET threads={int(settings.resources.duckdb_threads)};")

                for ddl in DDL_STATEMENTS:
                    writer_conn.execute(ddl)

                s_root = Path(silver_root or (get_data_root() / settings.storage.silver_subdir))

                # Ingest Silver Klines if files exist
                if s_root.exists():
                    kline_files = [
                        p.as_posix()
                        for p in s_root.rglob("*.parquet")
                        if "event_type=klines" in p.as_posix() or "klines" in p.as_posix()
                    ]
                    if kline_files:
                        try:
                            writer_conn.execute(
                                """
                                INSERT OR REPLACE INTO fact_market_klines_1m
                                SELECT
                                    symbol,
                                    timeframe,
                                    open_time,
                                    close_time,
                                    open,
                                    high,
                                    low,
                                    close,
                                    volume,
                                    quote_asset_volume,
                                    number_of_trades,
                                    taker_buy_base_asset_volume,
                                    taker_buy_quote_asset_volume,
                                    is_closed
                                FROM read_parquet(?, union_by_name=true);
                                """,
                                [kline_files],
                            )
                            total_klines = writer_conn.execute("SELECT count(*) FROM fact_market_klines_1m").fetchone()[0]
                        except Exception as k_exc:
                            logger.warning("Error ingesting silver klines into warehouse: %s", k_exc)

                # Ingest Silver Trades if files exist
                if s_root.exists():
                    trade_files = [
                        p.as_posix()
                        for p in s_root.rglob("*.parquet")
                        if "event_type=agg_trades" in p.as_posix() or "agg_trades" in p.as_posix()
                    ]
                    if trade_files:
                        try:
                            writer_conn.execute(
                                """
                                INSERT OR REPLACE INTO fact_market_aggtrades
                                SELECT
                                    symbol,
                                    agg_trade_id,
                                    price,
                                    quantity,
                                    quote_quantity,
                                    is_buyer_maker,
                                    trade_time
                                FROM read_parquet(?, union_by_name=true);
                                """,
                                [trade_files],
                            )
                            total_trades = writer_conn.execute("SELECT count(*) FROM fact_market_aggtrades").fetchone()[0]
                        except Exception as t_exc:
                            logger.warning("Error ingesting silver trades into warehouse: %s", t_exc)

                # Materialize daily aggregation mart
                if total_klines > 0:
                    writer_conn.execute(
                        """
                        INSERT OR REPLACE INTO agg_kline_daily_marts
                        SELECT
                            symbol,
                            CAST(open_time AS DATE) AS dt,
                            FIRST(open ORDER BY open_time ASC) AS open,
                            MAX(high) AS high,
                            MIN(low) AS low,
                            LAST(close ORDER BY open_time ASC) AS close,
                            SUM(volume) AS volume,
                            CASE WHEN SUM(volume) > 0 THEN SUM(close * volume) / SUM(volume) ELSE 0.0 END AS vwap,
                            SUM(quote_asset_volume) AS quote_volume,
                            SUM(number_of_trades) AS trade_count
                        FROM fact_market_klines_1m
                        GROUP BY symbol, CAST(open_time AS DATE);
                        """
                    )
                    daily_marts = writer_conn.execute("SELECT count(*) FROM agg_kline_daily_marts").fetchone()[0]

                # Update dim_symbols
                if total_klines > 0:
                    writer_conn.execute(
                        """
                        INSERT OR REPLACE INTO dim_symbols
                        SELECT
                            symbol,
                            CASE WHEN symbol LIKE '%USDT' THEN REPLACE(symbol, 'USDT', '') ELSE symbol END AS base_asset,
                            CASE WHEN symbol LIKE '%USDT' THEN 'USDT' ELSE 'UNKNOWN' END AS quote_asset,
                            TRUE AS is_active,
                            MIN(open_time) AS first_seen_at,
                            MAX(close_time) AS last_seen_at
                        FROM fact_market_klines_1m
                        GROUP BY symbol;
                        """
                    )

                writer_conn.execute("CHECKPOINT;")
            finally:
                writer_conn.close()

            # Versioning & Snapshot promotion
            current_manifest = self.get_active_manifest()
            next_version = (current_manifest.get("version", 0) + 1) if current_manifest else 1
            snap_filename = f"dw-v{next_version}.duckdb"
            snap_path = self.snapshots_dir / snap_filename

            # Atomic copy to snapshot
            shutil.copyfile(staging_db, snap_path)

            now_iso = datetime.now(timezone.utc).isoformat()
            manifest_data = {
                "version": next_version,
                "path": str(snap_path),
                "created_at": now_iso,
                "klines_count": total_klines,
                "trades_count": total_trades,
                "daily_marts_count": daily_marts,
                "duration_seconds": round(time.perf_counter() - t0, 3),
            }

            # Atomic manifest swap
            tmp_manifest = self.manifest_file.with_name(f".manifest.{next_version}.tmp")
            tmp_manifest.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
            os.replace(tmp_manifest, self.manifest_file)

            # Cleanup older snapshots keeping latest 3
            all_snaps = sorted(self.snapshots_dir.glob("dw-v*.duckdb"))
            if len(all_snaps) > 3:
                for old_snap in all_snaps[:-3]:
                    try:
                        old_snap.unlink()
                    except OSError:
                        pass

            logger.info(
                "Promoted DuckDB warehouse snapshot v%d (%d klines, %d trades, %d daily marts in %.2fs)",
                next_version,
                total_klines,
                total_trades,
                daily_marts,
                manifest_data["duration_seconds"],
            )
            return manifest_data

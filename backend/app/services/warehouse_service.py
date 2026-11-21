"""Warehouse Analytics & Star-Schema Query Service (IFC-DP-006).

Provides:
- Orchestrated warehouse snapshot building
- High-level queries for daily OHLCV marts & cross-market aggregations
- Status reporting on the active DuckDB snapshot version and size
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.app.core.logging import get_logger
from backend.app.storage.warehouse import DuckDBWarehouseEngine

logger = get_logger("WarehouseService")


class WarehouseService:
    """Service facade for querying and managing the DuckDB Star Schema warehouse."""

    def __init__(self, engine: Optional[DuckDBWarehouseEngine] = None):
        self.engine = engine or DuckDBWarehouseEngine()

    def get_status(self) -> Dict[str, Any]:
        """Return metadata about current active warehouse snapshot."""
        manifest = self.engine.get_active_manifest()
        if not manifest:
            return {
                "status": "UNINITIALIZED",
                "version": 0,
                "path": None,
                "klines_count": 0,
                "trades_count": 0,
                "daily_marts_count": 0,
                "created_at": None,
            }
        p = Path(manifest["path"])
        size_bytes = p.stat().st_size if p.exists() else 0
        return {
            "status": "ACTIVE",
            "version": manifest.get("version", 1),
            "path": manifest.get("path"),
            "size_bytes": size_bytes,
            "klines_count": manifest.get("klines_count", 0),
            "trades_count": manifest.get("trades_count", 0),
            "daily_marts_count": manifest.get("daily_marts_count", 0),
            "created_at": manifest.get("created_at"),
            "duration_seconds": manifest.get("duration_seconds"),
        }

    def build_warehouse(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a warehouse snapshot build from Silver datasets."""
        return self.engine.build_snapshot(symbol=symbol, timeframe=timeframe)

    def get_daily_summary(self, symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Retrieve daily OHLCV + VWAP bars for a given symbol from the daily marts table."""
        sql = """
            SELECT
                symbol,
                dt,
                open,
                high,
                low,
                close,
                volume,
                vwap,
                quote_volume,
                trade_count
            FROM agg_kline_daily_marts
            WHERE symbol = ?
            ORDER BY dt DESC
            LIMIT ?;
        """
        return self.engine.query(sql, [symbol.upper(), limit])

    def query_star_schema(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Run arbitrary analytical read query against the Star Schema tables."""
        # Safety check: enforce read-only statements
        sql_clean = sql.strip().upper()
        if not (sql_clean.startswith("SELECT") or sql_clean.startswith("WITH") or sql_clean.startswith("DESCRIBE")):
            raise ValueError("Only SELECT queries are permitted on the data warehouse.")
        return self.engine.query(sql, params)

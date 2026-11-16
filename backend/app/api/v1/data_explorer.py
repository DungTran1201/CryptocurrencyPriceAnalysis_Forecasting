"""Data Explorer API for Medallion dataset preview, column profiling, DuckDB reads, & bounded CSV export."""

import asyncio
import csv
from datetime import datetime, timezone
import io
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Response, status
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.models.market import Kline
from backend.app.models.data_quality import DataQualityResult
from backend.app.models.forecast import ForecastRecord
from backend.app.services.governance_service import GovernanceService
from backend.app.storage.medallion import MedallionStorageManager

router = APIRouter(prefix="/data-explorer", tags=["Data Explorer"])

DATASETS_METADATA = [
    {
        "id": "silver_klines",
        "name": "Silver Validated Klines",
        "layer": "SILVER",
        "description": "Normalized, deduplicated OHLCV market candles with closed-candle flags.",
        "primary_keys": ["symbol", "timeframe", "open_time"],
        "columns": [
            {"name": "symbol", "type": "VARCHAR(32)", "nullable": False, "description": "Trading pair symbol"},
            {"name": "timeframe", "type": "VARCHAR(16)", "nullable": False, "description": "Candlestick interval"},
            {"name": "open_time", "type": "DATETIME", "nullable": False, "description": "Bar start timestamp in UTC"},
            {"name": "close_time", "type": "DATETIME", "nullable": False, "description": "Bar end timestamp in UTC"},
            {"name": "open", "type": "FLOAT", "nullable": False, "description": "Opening price in quote asset"},
            {"name": "high", "type": "FLOAT", "nullable": False, "description": "Highest traded price in bar"},
            {"name": "low", "type": "FLOAT", "nullable": False, "description": "Lowest traded price in bar"},
            {"name": "close", "type": "FLOAT", "nullable": False, "description": "Closing traded price in bar"},
            {"name": "volume", "type": "FLOAT", "nullable": False, "description": "Base asset volume traded"},
            {"name": "quote_asset_volume", "type": "FLOAT", "nullable": True, "description": "Quote asset volume traded"},
            {"name": "number_of_trades", "type": "INTEGER", "nullable": True, "description": "Trade execution count"},
            {"name": "is_closed", "type": "BOOLEAN", "nullable": False, "description": "Whether candle period is concluded"},
        ],
    },
    {
        "id": "bronze_market_events",
        "name": "Bronze Raw Market Events (zstd JSONL)",
        "layer": "BRONZE",
        "description": "Immutable raw compressed market event payloads with ingestion timestamps.",
        "primary_keys": ["event_id"],
        "columns": [
            {"name": "schema_version", "type": "STRING", "nullable": False, "description": "Canonical schema version"},
            {"name": "event_type", "type": "STRING", "nullable": True, "description": "aggTrade or kline"},
            {"name": "symbol", "type": "STRING", "nullable": False, "description": "Trading pair"},
            {"name": "ingestion_time", "type": "DATETIME", "nullable": False, "description": "UTC receipt timestamp"},
        ],
    },
    {
        "id": "gold_analytics_marts",
        "name": "Gold Financial & Risk Marts (DuckDB Parquet)",
        "layer": "GOLD",
        "description": "Materialized returns, ATR, VWAP, rolling volatility, and drawdown Parquet marts.",
        "primary_keys": ["symbol", "timeframe", "open_time"],
        "columns": [
            {"name": "symbol", "type": "STRING", "nullable": False, "description": "Trading pair"},
            {"name": "timeframe", "type": "STRING", "nullable": False, "description": "Interval"},
            {"name": "open_time", "type": "DATETIME", "nullable": False, "description": "Bar timestamp"},
            {"name": "close", "type": "DOUBLE", "nullable": False, "description": "Closing price"},
            {"name": "simple_return", "type": "DOUBLE", "nullable": True, "description": "Simple period return"},
            {"name": "log_return", "type": "DOUBLE", "nullable": True, "description": "Log return"},
            {"name": "atr_14", "type": "DOUBLE", "nullable": True, "description": "14-period Average True Range"},
            {"name": "vwap", "type": "DOUBLE", "nullable": True, "description": "Session VWAP"},
            {"name": "drawdown_pct", "type": "DOUBLE", "nullable": True, "description": "Running drawdown %"},
        ],
    },
    {
        "id": "gold_feature_sets",
        "name": "Gold ML Technical Feature Sets (DuckDB Parquet)",
        "layer": "FEATURES",
        "description": "Zero-lookahead normalized technical features persisted as Parquet.",
        "primary_keys": ["symbol", "timeframe", "open_time"],
        "columns": [
            {"name": "symbol", "type": "STRING", "nullable": False, "description": "Trading pair"},
            {"name": "open_time", "type": "DATETIME", "nullable": False, "description": "Feature cutoff timestamp"},
            {"name": "rsi_14", "type": "DOUBLE", "nullable": True, "description": "Normalized RSI(14)"},
            {"name": "boll_pct_b", "type": "DOUBLE", "nullable": True, "description": "Bollinger %B"},
            {"name": "atr_norm", "type": "DOUBLE", "nullable": True, "description": "Normalized ATR(14)"},
        ],
    },
    {
        "id": "data_quality_results",
        "name": "Data Quality Rule Audit Log",
        "layer": "SILVER_DQ",
        "description": "Rule-level evaluation results, severity classifications, and violation samples.",
        "primary_keys": ["id"],
        "columns": [
            {"name": "rule_id", "type": "VARCHAR(64)", "nullable": False, "description": "Identifier for rule check"},
            {"name": "rule_name", "type": "VARCHAR(128)", "nullable": False, "description": "Human-readable rule name"},
            {"name": "category", "type": "VARCHAR(32)", "nullable": False, "description": "Rule category"},
            {"name": "severity", "type": "VARCHAR(16)", "nullable": False, "description": "Severity level"},
            {"name": "status", "type": "VARCHAR(16)", "nullable": False, "description": "PASS or FAIL status"},
            {"name": "failed_records_count", "type": "INTEGER", "nullable": False, "description": "Number of violating records"},
            {"name": "message", "type": "TEXT", "nullable": False, "description": "Evaluation summary explanation"},
            {"name": "created_at", "type": "DATETIME", "nullable": False, "description": "Audit execution timestamp"},
        ],
    },
    {
        "id": "forecast_records",
        "name": "Forecasts & Realizations Registry",
        "layer": "GOLD_SERVING",
        "description": "Point-in-time predictions with frozen cutoff times and reconciled outcomes.",
        "primary_keys": ["id"],
        "columns": [
            {"name": "model_id", "type": "VARCHAR(64)", "nullable": False, "description": "Serving model ID"},
            {"name": "symbol", "type": "VARCHAR(32)", "nullable": False, "description": "Asset symbol"},
            {"name": "horizon_steps", "type": "INTEGER", "nullable": False, "description": "Prediction horizon step count"},
            {"name": "forecast_timestamp", "type": "DATETIME", "nullable": False, "description": "Generation timestamp"},
            {"name": "target_time", "type": "DATETIME", "nullable": False, "description": "Forecast realization timestamp"},
            {"name": "current_price", "type": "FLOAT", "nullable": False, "description": "Price at inference cutoff"},
            {"name": "predicted_price", "type": "FLOAT", "nullable": False, "description": "Model predicted price"},
            {"name": "predicted_direction", "type": "VARCHAR(8)", "nullable": False, "description": "UP or DOWN"},
            {"name": "status", "type": "VARCHAR(16)", "nullable": False, "description": "PENDING or RECONCILED"},
        ],
    },
]


@router.get("/datasets", summary="List available Medallion datasets and schema dictionaries")
async def list_datasets(db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    """Return catalog of queryable datasets enriched with live persisted catalog stats."""
    catalog_rows = await GovernanceService.list_catalog(db)
    cat_by_id = {c["dataset_id"]: c for c in catalog_rows}
    enriched = []
    for ds in DATASETS_METADATA:
        item = dict(ds)
        cat = cat_by_id.get(ds["id"])
        if cat:
            item["row_count"] = cat["row_count"]
            item["size_bytes"] = cat["size_bytes"]
            item["retention_policy"] = cat["retention_policy"]
            item["storage_location"] = cat["storage_location"]
        enriched.append(item)
    return enriched


@router.get("/preview", summary="Paginated dataset inspection with profile statistics")
async def preview_dataset(
    dataset: str = Query("silver_klines", description="Dataset identifier"),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=5, le=100),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Provide server-side paginated data table and summary statistical profile."""
    offset = (page - 1) * page_size
    medallion = MedallionStorageManager()

    if dataset == "silver_klines":
        query = select(Kline)
        count_query = select(func.count(Kline.id))
        filters = []
        if symbol:
            filters.append(Kline.symbol == symbol.upper())
        if timeframe:
            filters.append(Kline.timeframe == timeframe.lower())
        if filters:
            query = query.where(and_(*filters))
            count_query = count_query.where(and_(*filters))

        total_rows = await db.scalar(count_query) or 0
        res = await db.execute(query.order_by(Kline.open_time.desc()).limit(page_size).offset(offset))
        rows = res.scalars().all()
        formatted_rows = [
            {
                "symbol": r.symbol,
                "timeframe": r.timeframe,
                "open_time": r.open_time.isoformat(),
                "close_time": r.close_time.isoformat(),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "quote_asset_volume": r.quote_asset_volume,
                "number_of_trades": r.number_of_trades,
                "is_closed": r.is_closed,
            }
            for r in rows
        ]
        profile = {
            "total_records": total_rows,
            "sample_size": len(rows),
            "columns_count": 12,
            "min_open_time": formatted_rows[-1]["open_time"] if formatted_rows else None,
            "max_open_time": formatted_rows[0]["open_time"] if formatted_rows else None,
        }

    elif dataset == "bronze_market_events":
        raw_rows = await asyncio.to_thread(medallion.read_bronze_records, None, page_size * page)
        if symbol:
            raw_rows = [r for r in raw_rows if str(r.get("symbol", "")).upper() == symbol.upper()]
        total_rows = len(raw_rows)
        page_rows = raw_rows[offset:offset + page_size]
        formatted_rows = [
            {
                "schema_version": r.get("schema_version", "1.0.0"),
                "event_type": r.get("event_type") or r.get("source", "rest"),
                "symbol": r.get("symbol"),
                "ingestion_time": r.get("ingestion_time"),
                "event_id": r.get("event_id") or "rest_batch",
            }
            for r in page_rows
        ]
        profile = {"total_records": total_rows, "sample_size": len(formatted_rows), "columns_count": 5}

    elif dataset in ("gold_analytics_marts", "gold_feature_sets"):
        ds_dir = "analytics_marts" if dataset == "gold_analytics_marts" else "feature_sets"
        all_rows = await asyncio.to_thread(medallion.read_gold_dataset, ds_dir, symbol, 1000)
        if timeframe:
            all_rows = [r for r in all_rows if r.get("timeframe") == timeframe.lower()]
        total_rows = len(all_rows)
        formatted_rows = all_rows[offset:offset + page_size]
        col_cnt = len(formatted_rows[0]) if formatted_rows else 0
        profile = {"total_records": total_rows, "sample_size": len(formatted_rows), "columns_count": col_cnt}

    elif dataset == "data_quality_results":
        total_rows = await db.scalar(select(func.count(DataQualityResult.id))) or 0
        res = await db.execute(select(DataQualityResult).order_by(DataQualityResult.created_at.desc()).limit(page_size).offset(offset))
        rows = res.scalars().all()
        formatted_rows = [
            {
                "id": r.id,
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "category": r.category,
                "severity": r.severity,
                "status": r.status,
                "failed_records_count": r.failed_records_count,
                "message": r.message,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
        profile = {"total_records": total_rows, "sample_size": len(rows), "columns_count": 8}

    elif dataset == "forecast_records":
        total_rows = await db.scalar(select(func.count(ForecastRecord.id))) or 0
        res = await db.execute(select(ForecastRecord).order_by(ForecastRecord.forecast_timestamp.desc()).limit(page_size).offset(offset))
        rows = res.scalars().all()
        formatted_rows = [
            {
                "id": r.id,
                "model_id": r.model_id,
                "symbol": r.symbol,
                "horizon_steps": r.horizon_steps,
                "forecast_timestamp": r.forecast_timestamp.isoformat(),
                "target_time": r.target_time.isoformat(),
                "current_price": r.current_price,
                "predicted_price": r.predicted_price,
                "predicted_direction": r.predicted_direction,
                "status": r.status,
            }
            for r in rows
        ]
        profile = {"total_records": total_rows, "sample_size": len(rows), "columns_count": 9}

    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown dataset '{dataset}'")

    metadata = next((d for d in DATASETS_METADATA if d["id"] == dataset), None)

    return {
        "dataset": dataset,
        "metadata": metadata,
        "page": page,
        "page_size": page_size,
        "total_rows": total_rows,
        "total_pages": (total_rows + page_size - 1) // page_size if total_rows > 0 else 0,
        "profile": profile,
        "rows": formatted_rows,
    }


@router.get("/export", summary="Export bounded dataset records as CSV")
async def export_csv(
    dataset: str = Query("silver_klines"),
    symbol: Optional[str] = Query(None),
    timeframe: Optional[str] = Query(None),
    limit: int = Query(2000, ge=1, le=5000, description="Max bounded export size"),
    db: AsyncSession = Depends(get_db),
):
    """Generate a downloadable CSV extract with bounded limits."""
    output = io.StringIO()
    writer = csv.writer(output)
    medallion = MedallionStorageManager()

    if dataset == "silver_klines":
        query = select(Kline)
        filters = []
        if symbol:
            filters.append(Kline.symbol == symbol.upper())
        if timeframe:
            filters.append(Kline.timeframe == timeframe.lower())
        if filters:
            query = query.where(and_(*filters))

        rows = (await db.execute(query.order_by(Kline.open_time.desc()).limit(limit))).scalars().all()
        writer.writerow(["symbol", "timeframe", "open_time", "close_time", "open", "high", "low", "close", "volume", "is_closed"])
        for r in rows:
            writer.writerow([r.symbol, r.timeframe, r.open_time.isoformat(), r.close_time.isoformat(), r.open, r.high, r.low, r.close, r.volume, r.is_closed])

    elif dataset in ("gold_analytics_marts", "gold_feature_sets"):
        ds_dir = "analytics_marts" if dataset == "gold_analytics_marts" else "feature_sets"
        rows = await asyncio.to_thread(medallion.read_gold_dataset, ds_dir, symbol, limit)
        if rows:
            cols = list(rows[0].keys())
            writer.writerow(cols)
            for r in rows:
                writer.writerow([r.get(c) for c in cols])

    elif dataset == "data_quality_results":
        rows = (await db.execute(select(DataQualityResult).order_by(DataQualityResult.created_at.desc()).limit(limit))).scalars().all()
        writer.writerow(["rule_id", "rule_name", "category", "severity", "status", "failed_records_count", "message", "created_at"])
        for r in rows:
            writer.writerow([r.rule_id, r.rule_name, r.category, r.severity, r.status, r.failed_records_count, r.message, r.created_at.isoformat()])

    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported export dataset '{dataset}'")

    csv_content = output.getvalue()
    filename = f"{dataset}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

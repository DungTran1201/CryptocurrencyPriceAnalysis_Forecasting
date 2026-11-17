"""Pipeline Orchestration Helpers & Medallion DAG Step Execution Service.

Provides:
- Sanitized workflow error taxonomy (never exposes raw exception strings publicly)
- Four non-stub Medallion DAG stage executors:
  1. ingest_bronze   (REST sync with rollback-on-retry + true batch delta watermarks)
  2. validate_silver (Full-table DQ evaluation + gap scan + Silver Parquet sync)
  3. build_gold_marts (Off-loop Silver->Gold analytical & risk mart materialization)
  4. extract_features (Standalone Silver read + zero-leakage ml.features computation & verification)
- Compatibility entrypoints delegating durable run management to WorkflowService
"""

import asyncio
from datetime import datetime, timezone
import inspect
import json
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx
import pandas as pd
from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.models.market import Kline
from backend.app.services.data_quality_service import DataQualityService
from backend.app.services.governance_service import GovernanceService
from backend.app.services.sync_service import BinanceSyncService
from backend.app.storage.medallion import MedallionStorageManager
from ml.features import extract_features as compute_zero_leakage_features

logger = get_logger("PipelineService")


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SafeWorkflowError(RuntimeError):
    """Domain error carrying a pre-sanitized code and client-safe summary."""

    def __init__(self, error_code: str, error_summary: str):
        super().__init__(error_summary)
        self.error_code = error_code[:64]
        self.error_summary = error_summary[:512]


class ActiveRunConflictError(SafeWorkflowError):
    """Raised when an active workflow run already holds the idempotency lock."""

    def __init__(self, existing_run_id: str, idempotency_key: str):
        super().__init__(
            error_code="ACTIVE_WORKFLOW_CONFLICT",
            error_summary=f"An active workflow run ({existing_run_id}) already holds lock '{idempotency_key}'.",
        )
        self.existing_run_id = existing_run_id
        self.idempotency_key = idempotency_key


def sanitize_error(exc: Exception, *, default_code: str = "WORKFLOW_EXECUTION_ERROR") -> Tuple[str, str]:
    """Map an exception into a client-safe (error_code, error_summary) pair without leaking internals."""
    if isinstance(exc, SafeWorkflowError):
        return exc.error_code[:64], exc.error_summary[:512]
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ("WORKFLOW_TIMEOUT", "Workflow step timed out waiting on an upstream or local resource.")
    if isinstance(exc, httpx.HTTPError):
        return ("UPSTREAM_HTTP_ERROR", "Upstream market data HTTP request failed.")
    if isinstance(exc, SQLAlchemyError):
        return ("DATABASE_ERROR", "Operational SQL metadata operation failed.")
    if isinstance(exc, OSError):
        return ("STORAGE_IO_ERROR", "Storage filesystem read/write operation failed.")
    if isinstance(exc, ValueError):
        return ("VALIDATION_ERROR", "Workflow input or dataset integrity validation failed.")
    return (default_code[:64], "Workflow execution failed due to an internal error. Check server logs.")


async def _load_klines_for_symbol(
    db: AsyncSession,
    symbol: str,
    timeframe: str,
) -> List[Kline]:
    res = await db.execute(
        select(Kline)
        .where(and_(Kline.symbol == symbol, Kline.timeframe == timeframe))
        .order_by(Kline.open_time.asc())
    )
    return list(res.scalars().all())


def _klines_to_dataframe(kline_rows: List[Kline]) -> pd.DataFrame:
    if not kline_rows:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])
    return pd.DataFrame(
        [
            {
                "open_time": k.open_time,
                "close_time": k.close_time,
                "open": float(k.open),
                "high": float(k.high),
                "low": float(k.low),
                "close": float(k.close),
                "volume": float(k.volume),
                "quote_asset_volume": float(k.quote_asset_volume or 0.0),
                "number_of_trades": int(k.number_of_trades or 0),
                "is_closed": bool(k.is_closed),
            }
            for k in kline_rows
        ]
    )


class PipelineService:
    """Executes Medallion pipeline stages cleanly and delegates workflow state to WorkflowService."""

    @staticmethod
    async def step_ingest_bronze(
        db: AsyncSession,
        *,
        run_id: str,
        symbol: str,
        timeframe: str,
        lookback_days: int = 30,
        skip_network_ingest: bool = False,
        max_step_retries: int = 2,
    ) -> Dict[str, Any]:
        """Stage 1: Execute bounded incremental sync with rollback-on-retry & delta watermarks."""
        symbol = symbol.upper()
        timeframe = timeframe.lower()
        t0 = time.perf_counter()

        if skip_network_ingest:
            return {
                "skipped": True,
                "records_processed": 0,
                "rows_read": 0,
                "rows_inserted": 0,
                "start_watermark": None,
                "end_watermark": None,
                "duration_seconds": round(time.perf_counter() - t0, 4),
                "note": "Skipped external REST ingest (local recomputation mode).",
            }

        prev_close_wm: Optional[datetime] = await db.scalar(
            select(func.max(Kline.close_time)).where(
                and_(Kline.symbol == symbol, Kline.timeframe == timeframe)
            )
        )

        sync_service = BinanceSyncService()
        sync_res: Dict[str, Any] = {}
        last_exc: Optional[Exception] = None

        for attempt in range(max_step_retries + 1):
            try:
                sync_res = await sync_service.sync_incremental(
                    db,
                    symbol=symbol,
                    timeframe=timeframe,
                    lookback_days_if_empty=lookback_days,
                )
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Pipeline %s ingest_bronze attempt %s/%s failed for %s %s: %s",
                    run_id,
                    attempt + 1,
                    max_step_retries + 1,
                    symbol,
                    timeframe,
                    type(exc).__name__,
                )
                try:
                    await db.rollback()
                except Exception:
                    pass
                if attempt < max_step_retries:
                    await asyncio.sleep(0.25 * (attempt + 1))
        else:
            err_code, err_summary = sanitize_error(last_exc or RuntimeError("Ingest failed"))
            raise SafeWorkflowError(err_code, f"Bronze ingestion failed after retries: {err_summary}")

        added_count = int(sync_res.get("added_candles", 0))
        read_count = int(sync_res.get("rows_read", added_count))

        # True batch delta watermark calculation (never blindly report full history on 0-delta syncs)
        delta_start_wm: Optional[datetime] = None
        delta_end_wm: Optional[datetime] = None
        if added_count > 0:
            delta_cond = [Kline.symbol == symbol, Kline.timeframe == timeframe]
            if prev_close_wm is not None:
                delta_cond.append(Kline.close_time > prev_close_wm)
            wm_row = (
                await db.execute(
                    select(func.min(Kline.open_time), func.max(Kline.close_time)).where(and_(*delta_cond))
                )
            ).first()
            if wm_row and wm_row[0] is not None:
                delta_start_wm = wm_row[0]
                delta_end_wm = wm_row[1]
        elif prev_close_wm is not None:
            delta_start_wm = prev_close_wm
            delta_end_wm = prev_close_wm

        await GovernanceService.record_lineage_edge(
            db,
            run_id=run_id,
            source_dataset="binance_public_stream",
            target_dataset="bronze_market_events",
            transformation="rest_incremental_ingest",
            records_in=read_count,
            records_out=added_count,
            metadata={
                "delta_start_watermark": delta_start_wm.isoformat() if delta_start_wm else None,
                "delta_end_watermark": delta_end_wm.isoformat() if delta_end_wm else None,
            },
        )
        await db.commit()

        return {
            "skipped": False,
            "records_processed": added_count,
            "rows_read": read_count,
            "rows_inserted": added_count,
            "start_watermark": delta_start_wm.isoformat() if delta_start_wm else None,
            "end_watermark": delta_end_wm.isoformat() if delta_end_wm else None,
            "duration_seconds": round(time.perf_counter() - t0, 4),
        }

    @staticmethod
    async def step_validate_silver(
        db: AsyncSession,
        *,
        run_id: str,
        symbol: str,
        timeframe: str,
        medallion: Optional[MedallionStorageManager] = None,
    ) -> Dict[str, Any]:
        """Stage 2: Validate ALL stored SQL klines (not capped at 1000), sync Silver Parquet, check gaps."""
        symbol = symbol.upper()
        timeframe = timeframe.lower()
        t0 = time.perf_counter()
        med = medallion or MedallionStorageManager()
        sync_service = BinanceSyncService(medallion=med)

        total_count = int(
            await db.scalar(
                select(func.count(Kline.id)).where(
                    and_(Kline.symbol == symbol, Kline.timeframe == timeframe)
                )
            )
            or 0
        )

        dq_kwargs: Dict[str, Any] = {}
        if "commit" in inspect.signature(DataQualityService.evaluate_klines).parameters:
            dq_kwargs["commit"] = False

        dq_run = await DataQualityService.evaluate_klines(
            db,
            symbol=symbol,
            timeframe=timeframe,
            limit=max(total_count, 1),
            check_mode="BATCH",
            **dq_kwargs,
        )
        gaps = await sync_service.detect_gaps(db, symbol, timeframe)
        kline_rows = await _load_klines_for_symbol(db, symbol, timeframe)

        if kline_rows:
            silver_dicts = [
                {
                    "symbol": k.symbol,
                    "timeframe": k.timeframe,
                    "open_time": k.open_time,
                    "close_time": k.close_time,
                    "open": k.open,
                    "high": k.high,
                    "low": k.low,
                    "close": k.close,
                    "volume": k.volume,
                    "quote_asset_volume": k.quote_asset_volume,
                    "number_of_trades": k.number_of_trades,
                    "taker_buy_base_asset_volume": getattr(k, "taker_buy_base_asset_volume", 0.0) or 0.0,
                    "taker_buy_quote_asset_volume": getattr(k, "taker_buy_quote_asset_volume", 0.0) or 0.0,
                    "is_closed": k.is_closed,
                    "source": "silver_sync",
                }
                for k in kline_rows
            ]
            await asyncio.to_thread(med.write_silver_klines, symbol, timeframe, silver_dicts)

        if dq_run.status == "FAILED":
            await db.commit()
            raise SafeWorkflowError(
                "SILVER_DQ_FAILED",
                f"Silver DQ gate failed ({dq_run.rules_passed}/{dq_run.total_rules_evaluated} rules passed).",
            )

        await GovernanceService.record_lineage_edge(
            db,
            run_id=run_id,
            source_dataset="bronze_market_events",
            target_dataset="silver_klines",
            transformation="dq_validate_and_parquet_dedup",
            records_in=len(kline_rows),
            records_out=int(dq_run.evaluated_row_count or 0),
        )
        await db.commit()

        return {
            "records_processed": int(dq_run.evaluated_row_count or 0),
            "gaps_detected": len(gaps),
            "total_klines": len(kline_rows),
            "dq_status": dq_run.status,
            "rules_passed": int(dq_run.rules_passed or 0),
            "total_rules": int(dq_run.total_rules_evaluated or 0),
            "duration_seconds": round(time.perf_counter() - t0, 4),
        }

    @staticmethod
    async def step_build_gold_marts(
        db: AsyncSession,
        *,
        run_id: str,
        symbol: str,
        timeframe: str,
        medallion: Optional[MedallionStorageManager] = None,
    ) -> Dict[str, Any]:
        """Stage 3: Read Silver layer and materialize Gold analytical & risk marts off the event loop."""
        symbol = symbol.upper()
        timeframe = timeframe.lower()
        t0 = time.perf_counter()
        med = medallion or MedallionStorageManager()

        total_sql = int(
            await db.scalar(
                select(func.count(Kline.id)).where(
                    and_(Kline.symbol == symbol, Kline.timeframe == timeframe)
                )
            )
            or 0
        )
        read_limit = max(total_sql, 100000)

        klines_df = await asyncio.to_thread(med.read_silver_klines_df, symbol, timeframe, read_limit)
        if klines_df.empty:
            kline_rows = await _load_klines_for_symbol(db, symbol, timeframe)
            klines_df = _klines_to_dataframe(kline_rows)

        if klines_df.empty:
            raise SafeWorkflowError("GOLD_SOURCE_EMPTY", f"No Silver kline rows available for {symbol} {timeframe}.")

        gold_res = await asyncio.to_thread(med.materialize_gold_marts, symbol, timeframe, klines_df)
        if int(gold_res.get("analytics_rows", 0)) == 0:
            raise SafeWorkflowError(
                "GOLD_MART_EMPTY",
                f"Gold mart materialization produced 0 rows for {symbol} {timeframe}.",
            )

        await GovernanceService.record_lineage_edge(
            db,
            run_id=run_id,
            source_dataset="silver_klines",
            target_dataset="gold_analytics_marts",
            transformation="materialize_gold_analytics_parquet",
            records_in=len(klines_df),
            records_out=int(gold_res["analytics_rows"]),
            metadata=gold_res.get("summary"),
        )
        await db.commit()

        return {
            "records_processed": int(gold_res["analytics_rows"]),
            "summary": gold_res.get("summary", {}),
            "duration_seconds": round(time.perf_counter() - t0, 4),
        }

    @staticmethod
    async def step_extract_features(
        db: AsyncSession,
        *,
        run_id: str,
        symbol: str,
        timeframe: str,
        medallion: Optional[MedallionStorageManager] = None,
    ) -> Dict[str, Any]:
        """Stage 4: Standalone Silver->Features execution, verification, lineage & catalog sync."""
        symbol = symbol.upper()
        timeframe = timeframe.lower()
        t0 = time.perf_counter()
        med = medallion or MedallionStorageManager()

        total_sql = int(
            await db.scalar(
                select(func.count(Kline.id)).where(
                    and_(Kline.symbol == symbol, Kline.timeframe == timeframe)
                )
            )
            or 0
        )
        read_limit = max(total_sql, 100000)

        silver_df = await asyncio.to_thread(med.read_silver_klines_df, symbol, timeframe, read_limit)
        if silver_df.empty:
            kline_rows = await _load_klines_for_symbol(db, symbol, timeframe)
            silver_df = _klines_to_dataframe(kline_rows)

        if silver_df.empty:
            raise SafeWorkflowError("FEATURE_SOURCE_EMPTY", f"No Silver rows available to extract features for {symbol} {timeframe}.")

        def _extract_and_verify() -> Tuple[int, int, int]:
            feat_df = compute_zero_leakage_features(silver_df)
            persisted = med.read_gold_dataset("feature_sets", symbol=symbol, limit=read_limit)
            feature_cols = max(len(feat_df.columns) - 2, 0)
            return len(feat_df), feature_cols, len(persisted)

        feat_rows, feat_cols, persisted_rows = await asyncio.to_thread(_extract_and_verify)
        if feat_rows == 0:
            raise SafeWorkflowError("FEATURE_EXTRACTION_EMPTY", f"Feature extraction produced 0 rows for {symbol} {timeframe}.")

        await GovernanceService.record_lineage_edge(
            db,
            run_id=run_id,
            source_dataset="silver_klines",
            target_dataset="gold_feature_sets",
            transformation="extract_zero_leakage_features_parquet",
            records_in=len(silver_df),
            records_out=feat_rows,
            metadata={"feature_columns": feat_cols, "persisted_feature_rows": persisted_rows},
        )
        await GovernanceService.sync_catalog_entries(db)

        return {
            "records_processed": feat_rows,
            "feature_columns": feat_cols,
            "persisted_feature_rows": persisted_rows,
            "duration_seconds": round(time.perf_counter() - t0, 4),
        }

    @staticmethod
    async def get_overview_stats(db: AsyncSession) -> Dict[str, Any]:
        """Aggregate workflow execution KPIs via WorkflowService."""
        from backend.app.services.workflow_service import WorkflowService

        return await WorkflowService.get_overview_stats(db)

    @staticmethod
    async def list_runs(
        db: AsyncSession,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query workflow runs formatted for summary response."""
        from backend.app.services.workflow_service import WorkflowService

        return await WorkflowService.list_runs(
            db, status=status, symbol=symbol, timeframe=timeframe, limit=limit, offset=offset
        )

    @staticmethod
    async def get_run_details(db: AsyncSession, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve workflow run metadata and per-step task breakdown."""
        from backend.app.services.workflow_service import WorkflowService

        return await WorkflowService.get_run_details(db, run_id)

    @staticmethod
    async def execute_medallion_pipeline(
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        trigger_type: str = "MANUAL",
        lookback_days: int = 30,
        skip_network_ingest: bool = False,
    ):
        """Synchronously enqueue, claim, and execute a durable MEDALLION_DAG WorkflowRun."""
        from backend.app.services.workflow_service import WorkflowService

        symbol = symbol.upper()
        timeframe = timeframe.lower()
        params = {
            "lookback_days": lookback_days,
            "skip_network_ingest": skip_network_ingest,
        }
        run, deduplicated = await WorkflowService.enqueue_run(
            db,
            workflow_type="MEDALLION_DAG",
            symbol=symbol,
            timeframe=timeframe,
            trigger_type=trigger_type,
            params=params,
            conflict_mode="return_existing",
        )
        if deduplicated and run.status != "QUEUED":
            raise ActiveRunConflictError(run.id, run.idempotency_key)

        claimed = await WorkflowService.claim_run_by_id(
            db, run_id=run.id, worker_id="api-sync-inline", lease_ttl_sec=120
        )
        if claimed is None:
            raise ActiveRunConflictError(run.id, run.idempotency_key)

        return await WorkflowService.execute_run(
            db,
            claimed.id,
            lease_token=claimed.lease_token or "",
        )

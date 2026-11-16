"""Pipeline Orchestration & Execution Service.

Provides a lightweight persisted DAG runner with:
- Sequential task dependencies (ingest_bronze -> validate_silver -> build_gold_marts -> extract_features)
- Real Bronze zstd JSONL, Silver Parquet, Gold DuckDB/Parquet, & ML Feature materialization
- Persisted Data Catalog & Data Lineage tracking
- Retry handling and historical recomputation
"""

import asyncio
from datetime import datetime, timezone
import json
import time
import traceback
from typing import List, Dict, Any, Optional
import pandas as pd
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.models.pipeline import PipelineRun, PipelineTaskRun
from backend.app.models.market import Kline
from backend.app.services.sync_service import BinanceSyncService
from backend.app.services.data_quality_service import DataQualityService
from backend.app.services.governance_service import GovernanceService
from backend.app.storage.medallion import MedallionStorageManager

logger = get_logger("PipelineService")


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PipelineService:
    """Manages and executes tracked Medallion DAG pipelines."""

    @staticmethod
    async def get_overview_stats(db: AsyncSession) -> Dict[str, Any]:
        """Aggregate pipeline execution statistics for Data Operations Overview."""
        total_runs = await db.scalar(select(func.count(PipelineRun.id))) or 0
        succeeded_runs = await db.scalar(
            select(func.count(PipelineRun.id)).where(PipelineRun.status == "SUCCESS")
        ) or 0
        failed_runs = await db.scalar(
            select(func.count(PipelineRun.id)).where(PipelineRun.status == "FAILED")
        ) or 0
        running_runs = await db.scalar(
            select(func.count(PipelineRun.id)).where(PipelineRun.status == "RUNNING")
        ) or 0

        total_rows_inserted = await db.scalar(select(func.sum(PipelineRun.rows_inserted))) or 0
        total_rows_read = await db.scalar(select(func.sum(PipelineRun.rows_read))) or 0

        latest_success = await db.scalar(
            select(PipelineRun)
            .where(PipelineRun.status == "SUCCESS")
            .order_by(PipelineRun.completed_at.desc())
            .limit(1)
        )
        latest_failure = await db.scalar(
            select(PipelineRun)
            .where(PipelineRun.status == "FAILED")
            .order_by(PipelineRun.completed_at.desc())
            .limit(1)
        )
        avg_duration = await db.scalar(
            select(func.avg(PipelineRun.duration_seconds)).where(PipelineRun.status == "SUCCESS")
        ) or 0.0

        return {
            "total_runs": total_runs,
            "succeeded_runs": succeeded_runs,
            "failed_runs": failed_runs,
            "running_runs": running_runs,
            "success_rate_pct": round((succeeded_runs / total_runs * 100.0), 1) if total_runs > 0 else 100.0,
            "total_rows_read": int(total_rows_read),
            "total_rows_inserted": int(total_rows_inserted),
            "avg_duration_seconds": round(float(avg_duration), 2),
            "latest_successful_run_at": latest_success.completed_at.isoformat() if latest_success and latest_success.completed_at else None,
            "latest_error_message": latest_failure.error_message if latest_failure else None,
        }

    @staticmethod
    async def list_runs(
        db: AsyncSession,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[PipelineRun]:
        """Query historical pipeline runs with optional filters."""
        query = select(PipelineRun).order_by(PipelineRun.created_at.desc())
        if status:
            query = query.where(PipelineRun.status == status.upper())
        if symbol:
            query = query.where(PipelineRun.symbol == symbol.upper())
        if timeframe:
            query = query.where(PipelineRun.timeframe == timeframe.lower())

        query = query.limit(limit).offset(offset)
        res = await db.execute(query)
        return list(res.scalars().all())

    @staticmethod
    async def get_run_details(db: AsyncSession, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full details of a pipeline run and its individual tasks."""
        run_res = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
        run = run_res.scalar_one_or_none()
        if not run:
            return None

        tasks_res = await db.execute(
            select(PipelineTaskRun)
            .where(PipelineTaskRun.pipeline_run_id == run_id)
            .order_by(PipelineTaskRun.sequence_order.asc())
        )
        tasks = list(tasks_res.scalars().all())

        return {
            "id": run.id,
            "pipeline_name": run.pipeline_name,
            "workflow_version": run.workflow_version,
            "symbol": run.symbol,
            "timeframe": run.timeframe,
            "status": run.status,
            "trigger_type": run.trigger_type,
            "retry_count": run.retry_count,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "duration_seconds": run.duration_seconds,
            "rows_read": run.rows_read,
            "rows_inserted": run.rows_inserted,
            "rows_updated": run.rows_updated,
            "rows_rejected": run.rows_rejected,
            "gaps_detected": run.gaps_detected,
            "start_watermark": run.start_watermark.isoformat() if run.start_watermark else None,
            "end_watermark": run.end_watermark.isoformat() if run.end_watermark else None,
            "input_datasets": json.loads(run.input_datasets) if run.input_datasets else [],
            "output_datasets": json.loads(run.output_datasets) if run.output_datasets else [],
            "error_message": run.error_message,
            "tasks": [
                {
                    "id": t.id,
                    "task_name": t.task_name,
                    "sequence_order": t.sequence_order,
                    "depends_on": t.depends_on,
                    "status": t.status,
                    "retry_count": t.retry_count,
                    "started_at": t.started_at.isoformat() if t.started_at else None,
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                    "duration_seconds": t.duration_seconds,
                    "records_processed": t.records_processed,
                    "input_dataset": t.input_dataset,
                    "output_dataset": t.output_dataset,
                    "error_message": t.error_message,
                    "logs": t.logs,
                }
                for t in tasks
            ],
        }

    @staticmethod
    async def execute_medallion_pipeline(
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        trigger_type: str = "MANUAL",
        lookback_days: int = 30,
        skip_network_ingest: bool = False,
    ) -> PipelineRun:
        """Execute end-to-end Medallion DAG with real transformations, persistence, & lineage."""
        symbol = symbol.upper()
        timeframe = timeframe.lower()
        start_wall = time.perf_counter()
        now_utc = _utc_now_naive()

        run = PipelineRun(
            pipeline_name="medallion_full_sync" if not skip_network_ingest else "medallion_recompute",
            workflow_version="3.0.0",
            symbol=symbol,
            timeframe=timeframe,
            status="RUNNING",
            trigger_type=trigger_type,
            started_at=now_utc,
            rows_read=0,
            rows_inserted=0,
            input_datasets=json.dumps(["binance_public_stream" if not skip_network_ingest else "silver_klines"]),
            output_datasets=json.dumps(["bronze_market_events", "silver_klines", "gold_analytics_marts", "gold_feature_sets"]),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        task_specs = [
            (1, "ingest_bronze", None, "binance_public_stream", "bronze_market_events"),
            (2, "validate_silver", "ingest_bronze", "bronze_market_events", "silver_klines"),
            (3, "build_gold_marts", "validate_silver", "silver_klines", "gold_analytics_marts"),
            (4, "extract_features", "build_gold_marts", "silver_klines", "gold_feature_sets"),
        ]
        tasks: Dict[str, PipelineTaskRun] = {}
        for seq, name, dep, in_ds, out_ds in task_specs:
            t = PipelineTaskRun(
                pipeline_run_id=run.id,
                task_name=name,
                sequence_order=seq,
                depends_on=dep,
                input_dataset=in_ds,
                output_dataset=out_ds,
                status="PENDING",
            )
            db.add(t)
            tasks[name] = t
        await db.commit()

        sync_service = BinanceSyncService()
        medallion = MedallionStorageManager()

        try:
            # -------------------------------------------------------------
            # Task 1: Ingest Bronze (REST sync + Bronze JSONL.zst + Silver Parquet)
            # -------------------------------------------------------------
            t_ingest = tasks["ingest_bronze"]
            t1_start = time.perf_counter()
            t_ingest.status = "RUNNING"
            t_ingest.started_at = _utc_now_naive()
            await db.commit()

            if skip_network_ingest:
                t_ingest.status = "SKIPPED"
                t_ingest.records_processed = 0
                t_ingest.completed_at = _utc_now_naive()
                t_ingest.duration_seconds = round(time.perf_counter() - t1_start, 4)
                t_ingest.logs = "Skipped external REST ingest (local Silver -> Gold recomputation mode)."
            else:
                # Retry loop for transient upstream errors
                sync_res: Dict[str, Any] = {}
                last_exc: Optional[Exception] = None
                for attempt in range(run.max_retries + 1):
                    try:
                        sync_res = await sync_service.sync_incremental(
                            db, symbol=symbol, timeframe=timeframe, lookback_days_if_empty=lookback_days
                        )
                        break
                    except Exception as exc:
                        last_exc = exc
                        t_ingest.retry_count += 1
                        if attempt < run.max_retries:
                            await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    raise RuntimeError(f"Ingestion failed after retries: {last_exc}")

                added_count = int(sync_res.get("added_candles", 0))
                read_count = int(sync_res.get("rows_read", added_count))
                t_ingest.status = "SUCCESS"
                t_ingest.records_processed = added_count
                t_ingest.completed_at = _utc_now_naive()
                t_ingest.duration_seconds = round(time.perf_counter() - t1_start, 4)
                t_ingest.logs = (
                    f"Synced {read_count} candles from Binance REST (+{added_count} new); "
                    f"archived Bronze zstd JSONL & Silver Parquet."
                )
                run.rows_inserted = added_count
                run.rows_read = read_count
                await GovernanceService.record_lineage_edge(
                    db,
                    run_id=run.id,
                    source_dataset="binance_public_stream",
                    target_dataset="bronze_market_events",
                    transformation="rest_incremental_ingest",
                    records_in=read_count,
                    records_out=added_count,
                )
            await db.commit()

            # -------------------------------------------------------------
            # Task 2: Validate Silver (DQ Gate + Silver Parquet Sync)
            # -------------------------------------------------------------
            t_val = tasks["validate_silver"]
            t2_start = time.perf_counter()
            t_val.status = "RUNNING"
            t_val.started_at = _utc_now_naive()
            await db.commit()

            dq_run = await DataQualityService.evaluate_klines(
                db, symbol=symbol, timeframe=timeframe, limit=1000, check_mode="BATCH"
            )
            gaps = await sync_service.detect_gaps(db, symbol, timeframe)
            run.gaps_detected = len(gaps)

            # Query Silver klines for Parquet sync & Gold input
            kline_rows = (
                await db.execute(
                    select(Kline)
                    .where(and_(Kline.symbol == symbol, Kline.timeframe == timeframe))
                    .order_by(Kline.open_time.asc())
                )
            ).scalars().all()

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
                        "is_closed": k.is_closed,
                        "source": "silver_sync",
                    }
                    for k in kline_rows
                ]
                await asyncio.to_thread(medallion.write_silver_klines, symbol, timeframe, silver_dicts)

            t_val.records_processed = dq_run.evaluated_row_count
            t_val.completed_at = _utc_now_naive()
            t_val.duration_seconds = round(time.perf_counter() - t2_start, 4)

            if dq_run.status == "FAILED":
                t_val.status = "FAILED"
                t_val.error_message = f"Silver DQ gate failed ({dq_run.rules_passed}/{dq_run.total_rules_evaluated} rules passed)."
                t_val.logs = t_val.error_message
                raise ValueError(t_val.error_message)

            t_val.status = "SUCCESS"
            t_val.logs = (
                f"Silver DQ: {dq_run.rules_passed}/{dq_run.total_rules_evaluated} passed ({dq_run.status}); "
                f"gaps={len(gaps)}; Silver Parquet synced ({len(kline_rows)} bars)."
            )
            await GovernanceService.record_lineage_edge(
                db,
                run_id=run.id,
                source_dataset="bronze_market_events",
                target_dataset="silver_klines",
                transformation="dq_validate_and_parquet_dedup",
                records_in=len(kline_rows),
                records_out=dq_run.evaluated_row_count,
            )
            await db.commit()

            # -------------------------------------------------------------
            # Task 3: Build Gold Marts (Real Parquet + DuckDB Materialization)
            # -------------------------------------------------------------
            t_gold = tasks["build_gold_marts"]
            t3_start = time.perf_counter()
            t_gold.status = "RUNNING"
            t_gold.started_at = _utc_now_naive()
            await db.commit()

            klines_df = pd.DataFrame([
                {
                    "open_time": k.open_time,
                    "open": k.open,
                    "high": k.high,
                    "low": k.low,
                    "close": k.close,
                    "volume": k.volume,
                }
                for k in kline_rows
            ])
            gold_res = await asyncio.to_thread(medallion.materialize_gold_marts, symbol, timeframe, klines_df)
            if gold_res["analytics_rows"] == 0:
                raise ValueError(f"Gold mart materialization produced 0 rows for {symbol} {timeframe}.")

            t_gold.status = "SUCCESS"
            t_gold.records_processed = gold_res["analytics_rows"]
            t_gold.completed_at = _utc_now_naive()
            t_gold.duration_seconds = round(time.perf_counter() - t3_start, 4)
            t_gold.logs = (
                f"Materialized Gold Parquet marts ({gold_res['analytics_rows']} rows, "
                f"VaR95={gold_res['summary'].get('var_95_pct')}, "
                f"MDD={gold_res['summary'].get('max_drawdown_pct')}%)."
            )
            await GovernanceService.record_lineage_edge(
                db,
                run_id=run.id,
                source_dataset="silver_klines",
                target_dataset="gold_analytics_marts",
                transformation="materialize_gold_analytics_parquet",
                records_in=len(klines_df),
                records_out=gold_res["analytics_rows"],
                metadata=gold_res["summary"],
            )
            await db.commit()

            # -------------------------------------------------------------
            # Task 4: Extract Features (Real Parquet Feature Set + Catalog Sync)
            # -------------------------------------------------------------
            t_feat = tasks["extract_features"]
            t4_start = time.perf_counter()
            t_feat.status = "RUNNING"
            t_feat.started_at = _utc_now_naive()
            await db.commit()

            feat_rows = gold_res["feature_rows"]
            feat_cols = gold_res["feature_columns"]
            await GovernanceService.record_lineage_edge(
                db,
                run_id=run.id,
                source_dataset="silver_klines",
                target_dataset="gold_feature_sets",
                transformation="extract_zero_leakage_features_parquet",
                records_in=len(klines_df),
                records_out=feat_rows,
            )
            await GovernanceService.sync_catalog_entries(db)

            t_feat.status = "SUCCESS"
            t_feat.records_processed = feat_rows
            t_feat.completed_at = _utc_now_naive()
            t_feat.duration_seconds = round(time.perf_counter() - t4_start, 4)
            t_feat.logs = f"Persisted {feat_rows} rows x {feat_cols} zero-lookahead features to Gold Parquet & refreshed Catalog."
            await db.commit()

            # Finalize run
            run.status = "SUCCESS"
            run.completed_at = _utc_now_naive()
            run.duration_seconds = round(time.perf_counter() - start_wall, 4)
            run.start_watermark = kline_rows[0].open_time if kline_rows else None
            run.end_watermark = kline_rows[-1].close_time if kline_rows else None
            await db.commit()

        except Exception as e:
            logger.error(f"Pipeline execution failed for {symbol} {timeframe}: {e}\n{traceback.format_exc()}")
            run.status = "FAILED"
            run.error_message = str(e)
            run.completed_at = _utc_now_naive()
            run.duration_seconds = round(time.perf_counter() - start_wall, 4)
            for t in tasks.values():
                if t.status in ("PENDING", "RUNNING"):
                    t.status = "FAILED" if t.status == "RUNNING" else "SKIPPED"
                    t.completed_at = _utc_now_naive()
                    if t.status == "FAILED" and not t.error_message:
                        t.error_message = str(e)
            await db.commit()

        return run

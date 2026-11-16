"""Data Quality Engine & Lineage Service (Batch and Streaming Validation)."""

from datetime import datetime, timezone, timedelta
import json
import math
from typing import List, Dict, Any
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.core.metrics import DQ_FAILURES
from backend.app.models.market import Kline
from backend.app.models.data_quality import DataQualityRun, DataQualityResult
from backend.app.services.governance_service import GovernanceService
from backend.app.services.sync_service import get_interval_delta

logger = get_logger("DataQualityService")


class DataQualityService:
    """Evaluates, records, and reports data quality rules on cryptocurrency records."""

    @staticmethod
    async def evaluate_klines(
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        limit: int = 1000,
        check_mode: str = "BATCH",
    ) -> DataQualityRun:
        """Run all 10 data quality rules against stored klines for a given symbol & timeframe."""
        start_time = datetime.now(timezone.utc)
        symbol = symbol.upper()

        stmt = (
            select(Kline)
            .where(and_(Kline.symbol == symbol, Kline.timeframe == timeframe))
            .order_by(Kline.open_time.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        klines = list(reversed(result.scalars().all()))
        row_count = len(klines)

        run = DataQualityRun(
            dataset_name=f"silver_klines_{symbol.lower()}_{timeframe.lower()}",
            check_mode=check_mode.upper(),
            symbol=symbol,
            timeframe=timeframe,
            run_timestamp=start_time.replace(tzinfo=None),
            evaluated_row_count=row_count,
            status="PASSED",
        )
        db.add(run)
        await db.flush()

        if row_count == 0:
            rule_empty = DataQualityResult(
                run_id=run.id,
                rule_id="DQ-VOL-00",
                rule_name="Dataset Minimum Row Count",
                category="COMPLETENESS",
                severity="ERROR",
                status="FAIL",
                failed_records_count=0,
                sample_failures=None,
                message=f"No stored klines found for {symbol} {timeframe}. Ingest market data to populate dataset.",
            )
            db.add(rule_empty)
            DQ_FAILURES.labels(rule_id="DQ-VOL-00", symbol=symbol).inc()
            run.total_rules_evaluated = 1
            run.rules_passed = 0
            run.rules_failed = 1
            run.status = "FAILED"
            run.duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000.0
            await db.commit()
            return run

        results: List[DataQualityResult] = []
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        expected_delta = get_interval_delta(timeframe)

        # 1. DQ-SCH-01
        schema_failures = 0
        for k in klines:
            if (
                not isinstance(k.open, (int, float))
                or not isinstance(k.close, (int, float))
                or not isinstance(k.high, (int, float))
                or not isinstance(k.low, (int, float))
                or not isinstance(k.volume, (int, float))
                or not isinstance(k.open_time, datetime)
            ):
                schema_failures += 1
        results.append(DataQualityResult(
            run_id=run.id,
            rule_id="DQ-SCH-01",
            rule_name="Schema & Column Type Adherence",
            category="SCHEMA",
            severity="CRITICAL",
            status="PASS" if schema_failures == 0 else "FAIL",
            failed_records_count=schema_failures,
            message=(
                f"All {row_count} records match the expected OHLCV typed schema."
                if schema_failures == 0 else f"{schema_failures} records violate data types."
            ),
        ))

        # 2. DQ-NUL-01
        null_failures = 0
        null_samples = []
        for k in klines:
            has_null = (
                k.open is None or math.isnan(k.open)
                or k.high is None or math.isnan(k.high)
                or k.low is None or math.isnan(k.low)
                or k.close is None or math.isnan(k.close)
                or k.volume is None or math.isnan(k.volume)
                or k.open_time is None or k.close_time is None
            )
            if has_null:
                null_failures += 1
                if len(null_samples) < 3:
                    null_samples.append({"open_time": k.open_time.isoformat() if k.open_time else None})
        results.append(DataQualityResult(
            run_id=run.id,
            rule_id="DQ-NUL-01",
            rule_name="Non-Null Mandatory Price & Timestamp Columns",
            category="COMPLETENESS",
            severity="CRITICAL",
            status="PASS" if null_failures == 0 else "FAIL",
            failed_records_count=null_failures,
            sample_failures=json.dumps(null_samples) if null_samples else None,
            message="Zero null or NaN values detected in mandatory OHLCV columns." if null_failures == 0 else f"{null_failures} records contain null or NaN values.",
        ))

        # 3. DQ-UNI-01
        seen_keys = set()
        duplicate_samples = []
        for k in klines:
            key = (k.symbol, k.timeframe, k.open_time)
            if key in seen_keys:
                if len(duplicate_samples) < 3:
                    duplicate_samples.append({"open_time": k.open_time.isoformat()})
            else:
                seen_keys.add(key)
        dup_count = len(klines) - len(seen_keys)
        results.append(DataQualityResult(
            run_id=run.id,
            rule_id="DQ-UNI-01",
            rule_name="Unique Key Constraint (symbol, timeframe, open_time)",
            category="INTEGRITY",
            severity="CRITICAL",
            status="PASS" if dup_count == 0 else "FAIL",
            failed_records_count=dup_count,
            sample_failures=json.dumps(duplicate_samples) if duplicate_samples else None,
            message="All records possess unique composite primary keys." if dup_count == 0 else f"{dup_count} duplicate timestamps found.",
        ))

        # 4. DQ-ORD-01
        order_violations = 0
        order_samples = []
        for i in range(1, len(klines)):
            if klines[i].open_time <= klines[i - 1].open_time:
                order_violations += 1
                if len(order_samples) < 3:
                    order_samples.append({
                        "prev": klines[i - 1].open_time.isoformat(),
                        "curr": klines[i].open_time.isoformat(),
                    })
        results.append(DataQualityResult(
            run_id=run.id,
            rule_id="DQ-ORD-01",
            rule_name="Monotonic Timestamp Sequence (t_i > t_{i-1})",
            category="CONSISTENCY",
            severity="ERROR",
            status="PASS" if order_violations == 0 else "FAIL",
            failed_records_count=order_violations,
            sample_failures=json.dumps(order_samples) if order_samples else None,
            message="Candles are chronologically ordered with strictly increasing timestamps." if order_violations == 0 else f"{order_violations} out-of-order timestamp steps detected.",
        ))

        # 5. DQ-GAP-01
        gap_count = 0
        gap_samples = []
        tolerance = expected_delta * 1.5
        for i in range(1, len(klines)):
            diff = klines[i].open_time - klines[i - 1].open_time
            if diff > tolerance:
                gap_count += 1
                if len(gap_samples) < 3:
                    gap_samples.append({
                        "from": klines[i - 1].open_time.isoformat(),
                        "to": klines[i].open_time.isoformat(),
                        "gap_hours": round(diff.total_seconds() / 3600.0, 2),
                    })
        results.append(DataQualityResult(
            run_id=run.id,
            rule_id="DQ-GAP-01",
            rule_name=f"Interval Continuity & Gap Tolerance ({timeframe})",
            category="CONSISTENCY",
            severity="WARNING",
            status="PASS" if gap_count == 0 else "FAIL",
            failed_records_count=gap_count,
            sample_failures=json.dumps(gap_samples) if gap_samples else None,
            message="No interval gaps detected across the evaluation window." if gap_count == 0 else f"{gap_count} time series continuity gaps detected (exceeding 1.5x interval).",
        ))

        # 6. DQ-REL-01
        ohlc_violations = 0
        ohlc_samples = []
        for k in klines:
            invalid = (
                k.high < k.low
                or k.high < k.open
                or k.high < k.close
                or k.low > k.open
                or k.low > k.close
            )
            if invalid:
                ohlc_violations += 1
                if len(ohlc_samples) < 3:
                    ohlc_samples.append({
                        "time": k.open_time.isoformat(),
                        "O": k.open, "H": k.high, "L": k.low, "C": k.close,
                    })
        results.append(DataQualityResult(
            run_id=run.id,
            rule_id="DQ-REL-01",
            rule_name="OHLC Price Geometry Consistency (H >= O/C/L, L <= O/C/H)",
            category="INTEGRITY",
            severity="CRITICAL",
            status="PASS" if ohlc_violations == 0 else "FAIL",
            failed_records_count=ohlc_violations,
            sample_failures=json.dumps(ohlc_samples) if ohlc_samples else None,
            message="100% of candles satisfy High >= Low and extremes bound Open/Close." if ohlc_violations == 0 else f"{ohlc_violations} candles violate basic OHLC relationship rules.",
        ))

        # 7. DQ-VOL-01
        neg_vol_count = sum(1 for k in klines if k.volume < 0)
        results.append(DataQualityResult(
            run_id=run.id,
            rule_id="DQ-VOL-01",
            rule_name="Non-Negative Trading Volume (Volume >= 0)",
            category="INTEGRITY",
            severity="ERROR",
            status="PASS" if neg_vol_count == 0 else "FAIL",
            failed_records_count=neg_vol_count,
            message="Trading volume values are non-negative." if neg_vol_count == 0 else f"{neg_vol_count} records contain negative trading volume.",
        ))

        # 8. DQ-FUT-01
        future_candles = sum(1 for k in klines if k.open_time > (now_utc + timedelta(minutes=5)))
        results.append(DataQualityResult(
            run_id=run.id,
            rule_id="DQ-FUT-01",
            rule_name="Timestamp Temporal Validity (open_time <= now_utc)",
            category="CONSISTENCY",
            severity="CRITICAL",
            status="PASS" if future_candles == 0 else "FAIL",
            failed_records_count=future_candles,
            message="Zero candles have future open timestamps relative to current UTC." if future_candles == 0 else f"{future_candles} candles have future timestamps.",
        ))

        # 9. DQ-OUT-01
        spike_count = 0
        spike_samples = []
        for i in range(1, len(klines)):
            prev_close = klines[i - 1].close
            curr_close = klines[i].close
            if prev_close > 0:
                ret = abs(curr_close - prev_close) / prev_close
                if ret > 0.35:
                    spike_count += 1
                    if len(spike_samples) < 3:
                        spike_samples.append({
                            "time": klines[i].open_time.isoformat(),
                            "change_pct": round(ret * 100.0, 2),
                            "prev": prev_close,
                            "curr": curr_close,
                        })
        results.append(DataQualityResult(
            run_id=run.id,
            rule_id="DQ-OUT-01",
            rule_name="Single-Bar Extreme Price Spike Anomaly Flag (> 35% jump)",
            category="ANOMALY",
            severity="WARNING",
            status="PASS" if spike_count == 0 else "FAIL",
            failed_records_count=spike_count,
            sample_failures=json.dumps(spike_samples) if spike_samples else None,
            message="No extreme single-bar price spikes detected in evaluation window." if spike_count == 0 else f"{spike_count} bars exhibited single-interval jumps > 35% (flagged for review).",
        ))

        # 10. DQ-FRE-01
        latest_candle = klines[-1]
        candle_age = now_utc - latest_candle.close_time
        max_acceptable_delay = max(expected_delta * 3, timedelta(hours=2))
        is_fresh = candle_age <= max_acceptable_delay
        results.append(DataQualityResult(
            run_id=run.id,
            rule_id="DQ-FRE-01",
            rule_name="Data Freshness SLA Adherence",
            category="COMPLETENESS",
            severity="WARNING",
            status="PASS" if is_fresh else "FAIL",
            failed_records_count=0 if is_fresh else 1,
            message=(
                f"Dataset is up to date. Latest candle age: {int(candle_age.total_seconds() / 60)} minutes."
                if is_fresh else f"Dataset is stale. Latest candle is {int(candle_age.total_seconds() / 3600)} hours old (exceeds SLA)."
            ),
        ))

        for r in results:
            if r.status == "FAIL":
                DQ_FAILURES.labels(rule_id=r.rule_id, symbol=symbol).inc()

        db.add_all(results)
        run.total_rules_evaluated = len(results)
        run.rules_passed = sum(1 for r in results if r.status == "PASS")
        run.rules_failed = sum(1 for r in results if r.status == "FAIL")

        critical_fails = sum(1 for r in results if r.status == "FAIL" and r.severity == "CRITICAL")
        if critical_fails > 0:
            run.status = "FAILED"
        elif run.rules_failed > 0:
            run.status = "WARNING"
        else:
            run.status = "PASSED"

        run.duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000.0
        await db.commit()

        logger.info(
            f"Evaluated data quality [{run.check_mode}] for {symbol} {timeframe}: "
            f"{run.rules_passed}/{run.total_rules_evaluated} rules passed ({run.status})."
        )
        return run

    @staticmethod
    async def get_overview_metrics(db: AsyncSession) -> Dict[str, Any]:
        """Aggregate data quality metrics from latest run per (symbol, timeframe)."""
        subq = (
            select(
                DataQualityRun.symbol,
                DataQualityRun.timeframe,
                func.max(DataQualityRun.run_timestamp).label("max_ts"),
            )
            .group_by(DataQualityRun.symbol, DataQualityRun.timeframe)
            .subquery()
        )
        stmt = (
            select(DataQualityRun)
            .join(
                subq,
                and_(
                    DataQualityRun.symbol == subq.c.symbol,
                    DataQualityRun.timeframe == subq.c.timeframe,
                    DataQualityRun.run_timestamp == subq.c.max_ts,
                ),
            )
        )
        latest_runs = (await db.execute(stmt)).scalars().all()

        total_rules = sum(r.total_rules_evaluated for r in latest_runs)
        passed_rules = sum(r.rules_passed for r in latest_runs)
        failed_rules = sum(r.rules_failed for r in latest_runs)
        pass_rate = (passed_rules / total_rules * 100.0) if total_rules > 0 else 0.0

        return {
            "total_active_suites": len(latest_runs),
            "total_rules_evaluated": total_rules,
            "passed_rules": passed_rules,
            "failed_rules": failed_rules,
            "pass_rate_pct": round(pass_rate, 1),
            "healthy_suites_count": sum(1 for r in latest_runs if r.status == "PASSED"),
            "warning_suites_count": sum(1 for r in latest_runs if r.status == "WARNING"),
            "failed_suites_count": sum(1 for r in latest_runs if r.status == "FAILED"),
        }

    @staticmethod
    async def get_lineage_graph(db: AsyncSession, dataset_filter: str | None = None) -> Dict[str, Any]:
        """Return real persisted Medallion lineage graph backed by DataCatalogEntry and DataLineageEdge."""
        return await GovernanceService.get_lineage_graph(db, dataset_filter=dataset_filter)

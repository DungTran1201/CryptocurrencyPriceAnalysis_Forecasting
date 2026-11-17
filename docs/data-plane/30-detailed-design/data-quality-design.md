# Data Quality & Completeness Detailed Design

**Scope:** `COMP-DP-10` (DataQualityService), `COMP-DP-03` (StreamProcessor DQ gate)  
**Requirements:** `REQ-DP-DEL-04`, `REQ-DP-LAKE-06`, `REQ-DP-KLN-01`, `REQ-DP-ING-01`  
**ADRs & Contracts:** `ADR-DP-002`, `ADR-DP-003`, `IFC-DP-005`  
**Phase 2 Work Items:** `WI-DP-02`, `WI-DP-04`, `WI-DP-09`

---

## 1. AS-IS Baseline & Defects `[OBSERVED]`

Audit of `backend/app/services/data_quality_service.py` and callers (`consumers.py:373`, `pipeline_service.py:286`) identified five defects:

1. **Premature Mid-Transaction `await db.commit()` (`data_quality_service.py:76, 331`)**:
   - `DataQualityService.evaluate_klines` calls `await db.commit()` directly before returning.
   - When invoked inside `MedallionStreamConsumer.flush_microbatch` (`consumers.py:373`), it commits `Kline` rows **before** `record_lineage_edge` (`consumers.py:376`) and `StreamCheckpoint` updates (`consumers.py:385-418`) execute. If checkpoint write subsequently fails, messages are NAKed while `klines` are already committed, corrupting checkpoint/processed counters on redelivery.
   - Inside `PipelineService` Task 2 (`pipeline_service.py:286`), it commits `t_val.status = "RUNNING"` early.
2. **SQL-Only Blindness & 1,000-Row Horizon Cap (`data_quality_service.py:35-43`)**:
   - `evaluate_klines` queries only the newest `limit` (default `1000`) rows from SQL `Kline`. For `ETHUSDT 15m` (9,600 rows on disk), the older 8,600 rows are never evaluated by `PipelineService`.
   - `DQ-UNI-01` (`lines 138-158`) checks `(symbol, timeframe, open_time)` uniqueness on SQL `klines` (already enforced by DB `UniqueConstraint`) while **never checking Silver Parquet or Gold Parquet** where duplicates can actually occur.
3. **Zero `agg_trades` Quality or Completeness Rules**:
   - `silver_agg_trades` has zero DQ runs, zero `agg_trade_id` continuity checks, and zero price/quantity/timestamp SLA checks.
4. **Cross-Layer Parity Blindness**:
   - Nothing detects or alerts on SQL vs Silver Parquet row count, `is_closed`, or OHLCV divergence (which allowed the `2026-11-17 05:43:00` BTC/ETH open-bar divergence on disk to go completely unreported).
5. **Overview Metric Shadowing (`data_quality_service.py:340-362`)**:
   - `get_overview_metrics` groups by `(symbol, timeframe)` using `max(run_timestamp)` across both `BATCH` and `STREAM` modes. A `STREAM` run on `1m` (200 rows) shadows the latest `BATCH` run on `1m`.

---

## 2. TO-BE Data Quality & Completeness Architecture `[PROPOSED]`

### 2.1 Transaction-Safe Service Contract (`REQ-DP-DEL-04`)

Add `commit: bool = True` to `DataQualityService.evaluate_klines(...)` (and all new `evaluate_*` methods):
- When invoked from standalone API routes (`POST /api/v1/data-quality/evaluate`) or standalone `WorkflowWorker` tasks, `commit=True` persists the `DataQualityRun` and `DataQualityResult` rows cleanly.
- When invoked inside `MedallionStreamConsumer.flush_microbatch` or a multi-step `PipelineService`/`WorkflowService` transaction, callers pass **`commit=False`**, using `await db.flush()` so the entire batch (klines + manifest + DQ + lineage + checkpoint) commits or rolls back atomically.

### 2.2 Expanded Data Quality Rule Suite

#### A. Silver Klines (10 Core SLA Rules + Empty-Dataset Sentinel — SQL & Active Silver Parquet Manifest)
Retain all 10 core SLA rule IDs (`DQ-SCH-01`, `DQ-NUL-01`, `DQ-UNI-01`, `DQ-ORD-01`, `DQ-GAP-01`, `DQ-REL-01`, `DQ-VOL-01`, `DQ-FUT-01`, `DQ-OUT-01`, `DQ-FRE-01`) plus the `DQ-VOL-00` empty-dataset sentinel (11 rule IDs total) with three upgrades:
1. **`DQ-GAP-01` Boundary Awareness**: Detect leading gaps (if requested window), interior gaps (`> 1.5 * delta`), **and** trailing staleness (`now_utc - max(close_time) > tolerance`) rather than interior gaps alone.
2. **Active Silver Parquet Evaluation (`evaluate_silver_parquet_klines`)**: Run schema, null, uniqueness (`(symbol, timeframe, open_time)`), OHLC geometry, and timestamp monotonicity directly against the `ACTIVE` `lake_snapshots` Parquet files (via bounded DuckDB snapshot/Parquet scan) before Warehouse build.
3. **Full-Window Batch Mode**: When invoked by `WorkflowWorker` (`check_mode="BATCH"`), evaluate either the full active window or bounded chunked partitions (up to `max_dq_eval_rows`), instead of hard-truncating at `1000` rows.

#### B. Silver Aggregate Trades Rules (`silver_agg_trades`)
Add `DataQualityService.evaluate_agg_trades(storage, snapshot, symbol, ...)`:
- **`DQ-TRD-SCH-01` (CRITICAL)**: Matches `SILVER_TRADE_SCHEMA` (`agg_trade_id: int64`, `price > 0`, `quantity >= 0`, non-null UTC timestamps).
- **`DQ-TRD-UNI-01` (CRITICAL)**: Zero duplicate `(symbol, agg_trade_id)` within the active Silver `agg_trades` manifest for the evaluated date partition.
- **`DQ-TRD-GAP-01` (WARNING/ERROR)**: Sequence continuity check (`curr_agg_id - prev_agg_id == 1` across sorted trades in partition). Any gap `> 0` records exact missing `(from_id, to_id)` ranges in `sample_failures` and enqueues a `WORKFLOW_AGGTRADE_BACKFILL` repair job.
- **`DQ-TRD-FUT-01` (CRITICAL)**: `trade_time <= now_utc + 5m`.

#### C. Cross-Layer Reconciliation Rules (`DQ-PARITY-01`, `DQ-PARITY-02`)
Scheduled via `WorkflowWorker` (`DATA_RECONCILE` job):
- **`DQ-PARITY-01` (SQL vs Silver Parquet `klines`)**: Compare row counts, `MAX(open_time)`, closed-bar counts (`is_closed=True`), and latest `close` values between SQL `klines` and the `ACTIVE` `silver_klines` snapshot manifest per `(symbol, timeframe)`. Any mismatch triggers `STATUS = FAILED` and schedules a deterministic SQL<->Silver reconcile pass.
- **`DQ-PARITY-02` (Silver vs Gold/Warehouse)**: Verify `fact_kline_bar` and `gold_analytics_marts` row counts match `ACTIVE` `silver_klines` (catching any multi-day Gold duplication or dropped rows).

### 2.3 Dataset Completeness State Machine `[PROPOSED]`

Track per-`(dataset_id, symbol, timeframe, partition_dt)` completeness in `SyncCheckpoint` / `mart_data_completeness` using explicit non-zero states (never masking missing history as `0` or `"PASSED"`):

```text
UNPOPULATED -> INCOMPLETE -> REPAIRING -> VERIFIED
                   ^            |             |
                   |            v             v
                   +--------- FAILED <--------+ (on new gap / parity drift)
```

- **`COMPLETE` / `VERIFIED`**: `observed_bars >= expected_bars` (for closed partitions), `gap_count == 0`, and `DQ-PARITY-01 == PASS`.
- **`INCOMPLETE`**: `observed_bars < expected_bars` or `gap_count > 0` or trailing lag > SLA; surfaces `completeness_pct` and missing `[start, end]` intervals.
- **`REPAIRING`**: Active `WorkflowWorker` backfill/heal job leased for this slice.
- **`FAILED`**: Repair exhausted retries or critical schema/OHLC/parity violation detected.

### 2.4 Overview Aggregation & Observability Fixes
- Update `get_overview_metrics(db, check_mode: Optional[str] = None)` to aggregate latest runs per `(symbol, timeframe, check_mode)` cleanly (preventing `STREAM` 200-row checks from hiding `BATCH` runs) and break timestamp ties deterministically by `(run_timestamp DESC, created_at DESC, id DESC)`.
- Export `DQ_FAILURES` and new `DATA_COMPLETENESS_RATIO` / `DATA_PARITY_MISMATCH` gauges (`IFC-DP-010`) on every batch/stream DQ evaluation.

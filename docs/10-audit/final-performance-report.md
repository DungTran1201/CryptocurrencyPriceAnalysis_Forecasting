# Final Performance & Throughput Report

**Project:** Resource-Efficient Real-Time Financial Data Intelligence Platform (`v3.0.0`)  
**Branch:** `feat/realtime-data-platform`  
**Host Environment:** Windows 10 Pro (`x86_64`), Intel Core i5-12400F (6 Cores / 12 Threads), 8,035.1 MB Physical RAM, Python `3.12.9`, NATS Server `v2.15.3`, Node `v24.18.0`.

---

## 1. Synthetic Microbenchmarks (`scripts/benchmark_platform.py`)

Command executed cleanly from repo root:
```powershell
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe scripts\benchmark_platform.py
```

### Benchmark Results Summary

| Metric | `LITE` Profile (`1,000 trades + 300 bars`) | `STANDARD` Profile (`2,500 trades + 500 bars`) | Notes |
|---|---:|---:|---|
| **Process RSS Start / End (MB)** | `201.62` / `226.43` | `225.61` / `232.53` | Stayed well below `450 MB` (`LITE`) / `950 MB` (`STANDARD`) soft limits |
| **Incremental State Throughput** | `30,365.7 events/sec` | `37,673.1 events/sec` | Single-process O(1)/rolling throughput across all 15 indicators & risk metrics |
| **Bronze `zstd` JSONL Write** | `9.11 ms` (`25.44x` ratio) | `16.44 ms` (`20.38x` ratio) | Atomic write + `zstandard` frame compression |
| **Silver Partitioned Parquet Write** | `9.98 ms` | `8.44 ms` | PyArrow Snappy columnar write |
| **DuckDB Lazy Silver Query** | `47.71 ms` | `37.53 ms` | Predicate-pushed SQL scan bounded to `128MB` (`LITE`) / `256MB` (`STANDARD`) DuckDB memory |
| **Gold Marts + ML Features Materialization** | `30.09 ms` | `29.39 ms` | DuckDB analytics + Parquet export |
| **Batch Reference Analytics (`15 metrics`)** | `4.64 ms` | `4.91 ms` | Vectorized NumPy/Pandas computation |
| **NATS JetStream Single-Publish Latency** | `0.137 ms/msg` | `0.133 ms/msg` | Measured concurrently against live `nats-server.exe` via auto-sizing fallback (`MARKET_EVENTS_BENCH`, cleaned up post-run) |

---

## 2. Live Single-Node End-to-End Performance (`LITE` Profile)

Measured against the running live platform (`nats-server.exe` + `uvicorn.exe` + embedded `StreamPlatformRuntime` connected to live Binance public WebSocket & REST API):

| Operation | Measured Latency / Throughput | Result & Evidence |
|---|---|---|
| **Pipeline DAG: `BTCUSDT 1h` (720 bars, full Bronze->Silver->DQ->Gold->Features)** | `1.7801 s` | `SUCCESS`, +720 rows persisted across layers |
| **Pipeline DAG: `ETHUSDT 1h` (720 bars, full Bronze->Silver->DQ->Gold->Features)** | `1.6559 s` | `SUCCESS`, +720 rows persisted across layers |
| **Binance WebSocket Live Stream (`BTCUSDT`, `ETHUSDT`)** | `> 2,168` events ingested cleanly | Zero malformed events (`malformed_count: 0`), zero DLQ events (`dlq_count: 0`), `0` publish errors |
| **Manual Micro-Batch Flush (`POST /api/v1/streaming/flush`)** | Immediate drain of `54` buffered events | `bronze_records: 54`, `silver_trades: 50`; `total_consumer_lag` dropped immediately from `54` to **`0`** |
| **WebSocket Reconnect & Recovery (`simulate-disconnect`)** | Sub-second reconnect | `reconnect_count` incremented `0 -> 1`, `ws_connected` restored `True`, continuous ingestion resumed |
| **Coalesced WebSocket Gateway (`/api/v1/ws/market`)** | `500 ms` coalesce interval (`LITE`) | Delivered initial `snapshot` frame and `tick_batch` JSON updates cleanly |
| **Production Frontend Bundle (`npm run build`)** | `1.63 s` build time | Single static asset tree (`286.76 kB` main bundle `dist/assets/index-S9u3m-1q.js`) |
| **Backend Automated Regression Suite (`pytest tests/ -v`)** | `7.10 s` | `42 passed`, `0 failed`, `0 skipped` (unit, contract, financial parity & live JetStream integration) |

---

## 3. Computational Efficiency Outcomes vs Baseline

1. **Incremental vs Full Recompute**: Online indicators and risk state run in O(1)/bounded-window (`ONLINE_WINDOW_MAX_BARS = 300`) at **>30,000 events/sec**, eliminating full-history scans per incoming tick.
2. **Storage Efficiency**: `zstd` Bronze compression reduced raw event payload volume by **20x–25x**, and Silver Parquet + DuckDB columnar queries kept analytical scans under **~50–69 ms** within a `128 MB` memory ceiling.
3. **Database Transaction Reduction**: Micro-batching (`50–250` records / `5.0 s`) eliminated per-tick SQL commits while maintaining exact idempotency (`(symbol, timeframe, open_time)` / `(symbol, agg_trade_id)`).

# ADR-004: Micro-Batching, Bounded Queues & Incremental Stream Analytics

- **Status:** Accepted
- **Date:** 2026-11-16
- **Context:** Recalculating historical pandas DataFrames or writing Parquet files on every `aggTrade` tick wastes CPU/disk I/O and risks unbounded memory growth during bursts.
- **Decision:**
  - Use bounded `asyncio.Queue(maxsize=STREAM_QUEUE_MAXSIZE)` with 80% high-watermark backpressure signaling (never silently dropping events).
  - Micro-batch Bronze and Silver Parquet writes on configurable `(max_records, max_age_sec, max_bytes)` thresholds.
  - Maintain O(1)-per-event incremental state per symbol (`IncrementalSymbolState`) for EMA, Wilder RSI, MACD, Bollinger Welford variance, ATR, VWAP, rolling return moments, and drawdown peak, persisting periodic JSON state checkpoints.
  - Coalesce WebSocket UI updates at `WS_COALESCE_INTERVAL_MS` (250-500 ms) so browser rendering stays smooth.
- **Consequences:** Stream latency stays low and memory remains flat; exact mathematical parity with batch reference calculations is enforced via automated tests.


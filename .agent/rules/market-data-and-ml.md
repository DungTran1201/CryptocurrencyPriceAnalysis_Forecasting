# Market Data and ML Reliability Rules

- Exchange data is external and may be delayed, incomplete, rate-limited, or unavailable.
- Store and compare timestamps in a consistent UTC representation. Distinguish candle open time, close time, and ingestion time.
- Do not duplicate candles; use a stable unique key `(symbol, timeframe, open_time)` where supported.
- Do not treat missing historical candles as zero price/volume. Record or surface the gap.
- When no data exists, return an explicit empty result with a valid count and status metadata where the contract defines it.
- Clearly distinguish a market ticker from the close of the most recently stored candle. Never label DB history as live without evidence of freshness.
- Ensure 24h statistics are based on a valid 24-hour window and sufficient data, not an arbitrary incomplete set silently represented as complete.
- Indicators must align in length/index with their candle series or document the different alignment. Preserve `null` for unavailable warm-up periods instead of fake values.
- Forecast outputs must include horizon, model/version, generated time, and data cutoff when available.
- Do not invent predictive accuracy, confidence intervals, probabilities, or trading returns. Compare models with baseline using chronological/walk-forward evaluation.
- No look-ahead leakage: fit transformations on training data and only use information available at prediction time.

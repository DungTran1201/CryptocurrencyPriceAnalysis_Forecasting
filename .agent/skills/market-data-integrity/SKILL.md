---
name: market-data-integrity
description: Check Binance ingestion, candle validity, ticker summaries, timestamps, and the difference between unknown and zero.
---

# Market Data Integrity Skill

1. Identify whether a value is sourced from exchange ticker, stored candles, or calculated indicators.
2. Verify that timestamps, units, interval names, candle closure, and freshness are explicit.
3. Check behavior for unregistered symbol, registered symbol with no candles, stale candles, API outage, and partially populated history.
4. Never infer that a missing record means the market price is zero.
5. If a symbol has no stored candles, return a typed unavailable state or optional nullable statistics with status/freshness metadata. Coordinate schema changes with frontend types and tests.
6. Verify 24h statistics against the intended source/window. Avoid N+1 queries when loading many symbol cards.
7. Enforce idempotent sync and proper handling of upstream errors/rate limits.
8. Test the exchange adapter with fixtures so CI works without the network.
9. Preserve a visible status distinction: Live, Delayed/Stale, Not synced, Error.
10. Document assumptions and avoid presenting market-analysis output as financial advice.

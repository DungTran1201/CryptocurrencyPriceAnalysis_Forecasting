# Codebase Audit & Remediation Verification — Binance Predict Value & Trend

> Verified and remediated audit report covering API contract conformance, data truthfulness, security/error boundaries, and frontend redesign.

## Summary of Completed Remediation

| Issue ID | Severity | Description | Status | Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **P0-KLINES-EMPTY** | P0 | Missing `count: 0` in empty klines response caused `ResponseValidationError` | **Fixed + Verified** | `test_market_klines_empty_regression` passes; live HTTP 200 returned with valid `count: 0` |
| **P1-FALSE-ZEROS** | P1 | Empty market data rendered as valid `$0.00` and `0.0%` | **Fixed + Verified** | Backend returns nullable metrics + `data_status`; frontend renders `—` / `No data` |
| **P1-N-PLUS-ONE** | P1 | Per-symbol N+1 database queries in `get_symbols` | **Fixed + Verified** | Refactored to single window query (`ROW_NUMBER() OVER PARTITION BY symbol`); verified in `test_symbol_summaries_truthfulness_and_states` |
| **P1-SYNC-PARAM** | P1 | Unused `BackgroundTasks` parameter and raw exception leakage | **Fixed + Verified** | Removed unused parameter; sanitized client error responses; structured server logging added |
| **P1-NUMERIC-LOCALE**| P1 | Inconsistent locale rendering (e.g. `$81.819,31` in English UI) | **Fixed + Verified** | Centralized `formatters.ts` using explicit `en-US` locale; unit tested in `src/utils/formatters.test.ts` |
| **P2-VIEWPORT-UI** | P2 | Prototype dashboard lacked visual density, responsive controls, and honest states | **Fixed + Verified** | Redesigned with responsive canvas, empty state views, truthful status pill, and mobile navigation |
| **P2-UTC-DEPRECATION**| P2 | Python 3.12 `datetime.utcnow()` deprecation warnings | **Fixed + Verified** | Replaced with `datetime.now(timezone.utc).replace(tzinfo=None)`; 0 warnings in test run |

---

## Detailed Findings and Resolutions

### P0 — Empty klines response violates required response schema
- **Root Cause:** `backend/app/schemas/market.py` requires `count: int` in `MarketDataResponseSchema`. In `backend/app/services/market_service.py::get_klines_with_indicators`, the empty-candles branch returned `{"symbol": symbol, "timeframe": timeframe, "candles": [], "indicators": {}}`, omitting `count`.
- **Fix:** Added `"count": 0` to the empty branch return dictionary. Kept `response_model=MarketDataResponseSchema` and Pydantic validation active.
- **Verification:**
  - Automated test: `tests/test_api_contract.py::test_market_klines_empty_regression`.
  - Live API validation: Querying `GET /api/v1/market/klines?symbol=ETHUSDT&timeframe=1h` returns HTTP 200:
    ```json
    {"symbol": "ETHUSDT", "timeframe": "1h", "count": 0, "candles": [], "indicators": {}}
    ```

### P1 — Missing stored data rendered as valid zero-valued market data
- **Root Cause:** `MarketService.get_symbols` defaulted empty symbol statistics to `current_price = 0.0`, `change_24h = 0.0`, `volume_24h = 0.0`. In the frontend, this displayed as active trading at `$0.00` and `Vol: 0.0`.
- **Fix:**
  - Updated `SymbolInfoSchema` in `backend/app/schemas/market.py` to allow nullable metric fields (`current_price: Optional[float] = None`, etc.) and added `candle_count_24h`, `has_full_24h`, and `data_status` (`"SYNCHRONIZED"`, `"PARTIAL"`, `"UNAVAILABLE"`, `"STALE"`).
  - Updated `MarketService.get_symbols` to return `None` metrics and `"UNAVAILABLE"` when no candles are stored.
  - Updated frontend types and views to format unavailable metrics as `—` with a concise status pill (`No data`), never as `$0.00`.
- **Verification:**
  - Automated test: `tests/test_api_contract.py::test_symbol_summaries_truthfulness_and_states`.
  - Browser inspection: ETHUSDT, SOLUSDT, BNBUSDT cards display `—` / `No data` without false zeroes.

### P1 — Per-symbol N+1 database access for market summaries
- **Root Cause:** `MarketService.get_symbols` queried active symbols and then executed a separate `Kline` query inside a `for` loop for each symbol.
- **Fix:** Replaced loop queries with a single batched SQL subquery using `func.row_number().over(partition_by=Kline.symbol, order_by=Kline.open_time.desc())` filtered to `rn <= 24`.
- **Verification:**
  - Verified across multiple symbol states in SQLite and PostgreSQL-compatible syntax.
  - Tested in `tests/test_api_contract.py::test_symbol_summaries_truthfulness_and_states`.

### P1 — Sync endpoint accepts BackgroundTasks but executes sync inline
- **Root Cause:** `trigger_sync` in `backend/app/api/v1/market.py` included `background_tasks: BackgroundTasks` in its signature while awaiting synchronization inline, and re-exposed raw exception strings `str(e)`.
- **Fix:**
  - Removed the unused `BackgroundTasks` argument to clarify the synchronous API contract.
  - Added strict parameter validation for `symbol` and `timeframe`.
  - Added structured server-side logging with tracebacks and sanitized HTTP 500 error messages.
- **Verification:**
  - Automated test: `tests/test_api_contract.py::test_sync_parameter_validation_and_safe_errors`.

### P1 — UI numeric formatting and status truthfulness
- **Root Cause:** Inconsistent browser locales caused currency formatting like `$81.819,31` (European decimal style in an English interface). Navbar hardcoded `BINANCE LIVE` regardless of connectivity or database freshness.
- **Fix:**
  - Created `frontend/src/utils/formatters.ts` using explicit `en-US` formatting for all currency, numbers, percentages, volumes, and dates.
  - Navbar queries `/api/v1/system/status` and displays `ENGINE ONLINE` (green) only when database is connected and candles are stored, `NO STORED CANDLES` (amber) when empty, or `DISCONNECTED` (red) on failure.
- **Verification:**
  - Frontend unit tests: `frontend/src/utils/formatters.test.ts` (5 passed).
  - Browser subagent verified live display: `$81,819.31`, `-2.39%`, volume `22.7K`, `ENGINE ONLINE`.

### P2 — Dashboard layout, empty states, and responsive behavior
- **Root Cause:** Main chart canvas was fixed size and lacked container resize handling; empty symbols caused blank/unresponsive UI states.
- **Fix:**
  - Integrated `ResizeObserver` inside `CandlestickChart.tsx` for fluid redraws on window resize.
  - Added high-quality empty state card when selecting unsynced symbols (e.g. ETHUSDT) with a direct "Sync from Binance" button.
  - Added mobile navigation hamburger and responsive breakpoints for tablets and phones.
- **Verification:**
  - Tested and captured via browser subagent across desktop (1600px, 1200px) and mobile viewport sizes.

---

## Residual Risks & Production Caveats

1. **Binance Rate Limits**: Incremental sync handles exponential backoff and jitter, but bulk historical backfilling over long windows (e.g. 365 days across many pairs) should be executed with appropriate rate-limit pacing.
2. **Database Engine**: In production deployments with high concurrent load, PostgreSQL with pgvector / TimescaleDB is recommended over SQLite.
3. **Clock Skew**: Candle closure timestamps rely on UTC synchronization; NTP synchronization should be active in production containers.

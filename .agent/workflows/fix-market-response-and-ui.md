# Workflow: Fix `/market/klines` Response Validation and Upgrade UI

## Goal
Fix the missing `count` response field, inspect related API/data/UI contract weaknesses, install/maintain the agent instruction pack, and improve the entire frontend experience using the supplied screenshot as design guidance.

## Order of execution

### Step 1 — Safe baseline
- Read root `AGENTS.md`, `.agent/rules`, and skills relevant to the task.
- Run `git status --short` and inspect the current branch. Preserve all existing work.
- Inspect all routes, schemas, services, models, migrations, frontend views, CSS, API clients, package manifests, and tests. Do not assume GitHub's visible code is identical to the current local workspace.
- Identify exact setup/test commands from existing manifests and docs.

### Step 2 — Fix the known backend bug
- `backend/app/schemas/market.py::MarketDataResponseSchema` requires `count: int`.
- `backend/app/services/market_service.py::MarketService.get_klines_with_indicators` currently omits `count` in its empty result branch.
- Return `count: 0` in that branch while preserving the complete response shape.
- Keep `response_model=MarketDataResponseSchema` enabled.
- Add regression tests for empty data (`count=0`, empty candles, empty indicators) and populated data (`count == len(candles)`).
- Check indicator output length and Pydantic validation for both paths.

### Step 3 — Audit sibling defects and data meaning
- Search all route/service return branches against their response schemas.
- Fix related missing-field contract bugs instead of stopping at the reported traceback.
- Inspect `MarketService.get_symbols`: it derives ticker cards from stored 1h candles and returns numeric zeros when no candles exist. Design a consistent unavailable/stale state; do not misrepresent zero as a valid market price.
- Review whether 24h summary calculations actually have sufficient data for the claimed window and whether the latest close is being mislabeled as a live ticker.
- Optimize N+1 queries if the revised symbol list still performs per-symbol queries.
- Inspect `/market/sync`: `BackgroundTasks` is accepted but currently sync is awaited inline. Either remove the unused parameter and document the synchronous contract, or implement a real observable background job using a new/session-factory-owned DB session. Never use a request-scoped AsyncSession after the request ends.
- Replace raw exception leakage (`str(e)` in public HTTP details) with safe error responses and structured server logging.
- Audit symbol/timeframe/date/limit validation, upstream rate limiting/timeouts, stale data, and unknown symbols.
- Treat other possible defects as unconfirmed until proven by source inspection or tests.

### Step 4 — Establish UI baseline and redesign
Use the uploaded screenshot as a direction: dark navy/black analytics canvas, compact top navigation, cyan active navigation, green/red semantic price movement, clean cards, professional candle chart with indicator toggles, clear live/stale status, and a compact footer.

Improve the design beyond the screenshot where appropriate:
- Use shared design tokens for color, spacing, typography, borders, radii, and focus rings.
- Use available page width efficiently; remove unexplained whitespace without overcrowding.
- Improve the hierarchy across Market Overview, Prediction Studio, Forecast History, Model Lab, and System Status.
- Standardize currency, decimal/grouping, percent, volume, and timestamps; default to `en-US` for English UI consistently unless app locale configuration says otherwise.
- Replace false `$0.00` and `0.0` fallbacks with `—`, `Unavailable`, or an equivalent state, together with a brief reason and last-updated time.
- Display data status accurately: Live only with evidence of recent successful synchronization; otherwise Stale, Not synced, or Error.
- Ensure chart resizes with its container and handles empty/error data.
- Keep symbol, timeframe, indicator, sync, forecast, history filter, and navigation controls functional.
- Ensure all pages have loading, empty, stale, and error states.
- Support responsive desktop, tablet, and mobile sizes; avoid clipped controls, overflow, and inaccessible tiny text.
- Use semantic HTML, keyboard focus, accessible labels, contrast, and meaningful tooltips.
- Do not add a large UI framework unless there is a clear reason.

### Step 5 — Keep API and frontend contracts aligned
- Update TypeScript types and API client only when the backend contract changes.
- Make the frontend handle `candles: []` as a normal empty state, not a fatal exception or fake chart.
- Keep numeric zero meaningful when it is actual data; do not treat every zero as unavailable. Prefer nullable values plus status/freshness metadata when changing ticker contracts.
- Ensure UI does not silently swallow schema/network failures.

### Step 6 — Test and verify
Run the repository's actual commands. At minimum where tooling supports them:
- Backend unit/API tests for empty and non-empty klines.
- Additional tests for unavailable market data, symbol summaries, safe sync errors, and job lifecycle if changed.
- Frontend TypeScript check and production build.
- Frontend tests and end-to-end smoke path if available.
- Inspect browser console/network failures if browser tooling is available.
- Review diff, package changes, accessibility, and responsive layouts.

### Step 7 — Report and document
Update `docs/audit/codebase-audit.md` with evidence, status, and residual risks. Update README only where commands/behavior actually changed.

Final report must state:
- Root cause and changed files.
- Adjacent defects found and fixed.
- UI improvements by page.
- Exact verification commands and outcomes.
- Checks not run and why.
- Remaining risks, including any assumptions about Binance data freshness.

## Stop conditions
Do not stop after a plan or after fixing only the first traceback. Continue through the UI update and verification. Stop only if a real blocker prevents editing/testing, and then complete all safe work and clearly state the blocker.

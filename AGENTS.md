# AGENTS.md — Binance Predict Value & Trend

## Mission
Maintain this repository as a reliable cryptocurrency market analytics and experimental forecasting web application. Fix root causes, preserve working capabilities, improve data correctness, and deliver a polished, responsive UI that uses real API data.

## Required reading
Before making changes, read:
- `.agent/README.md`
- Applicable `.agent/rules/*.md`
- Relevant `.agent/skills/*/SKILL.md`
- Relevant role briefs under `.agent/agents/`
- `.agent/workflows/fix-market-response-and-ui.md` for the current task

If the active coding agent does not automatically load `.agent/`, read these files explicitly. This `AGENTS.md` is the repository-wide source of truth.

## Current stack (verify before changing)
- Backend: Python, FastAPI, Pydantic, SQLAlchemy async.
- Frontend: React + TypeScript + Vite.
- Market/ML code exists in backend and `ml/` packages; inspect actual paths before moving files.
- Existing route/schema/service contracts must be traced before refactoring.

## Non-negotiable rules
1. Inspect the current working tree and preserve the user's uncommitted changes. Never run destructive Git commands or reset history.
2. Reproduce reported failures before changing code when feasible. Do not claim verification without executing the command.
3. Fix response-contract defects at the source and add regression tests. Do not remove response models or suppress Pydantic validation to make an error disappear.
4. Empty, unavailable, stale, and failed data are different states. Never represent unknown market values as valid numeric zeroes.
5. Production views must not use fabricated values or mock responses. Test fixtures must be isolated from production code paths.
6. Keep API schemas, service return values, frontend TypeScript types, and rendered states aligned.
7. Do not compute heavy model training in a request-response path. Any background task must own its database session and have observable status/error state.
8. Do not return raw exception strings, stack traces, secrets, filesystem paths, or environment values to public clients.
9. Preserve ML validity: chronological validation, no look-ahead, no leakage, and no invented performance metrics.
10. Prefer focused changes, minimal dependencies, typed interfaces, small modules, reusable components, and clear error handling.
11. Run relevant backend tests, frontend type checks/build, and end-to-end checks where supported. Report unrun checks as NOT RUN.
12. Every visible navigation item, button, and control must work or be visibly disabled with an explanation.

## Mandatory response contract for market klines
`MarketDataResponseSchema` requires `symbol`, `timeframe`, `count`, `candles`, and `indicators`. Every successful branch in `MarketService.get_klines_with_indicators` must return all required fields. For no stored candles, return `count: 0`, `candles: []`, and `indicators: {}`. Do not hide the issue by removing `response_model` or making `count` optional solely to avoid validation errors.

## UI direction
Use the provided Market Overview screenshot as a direction, not as a pixel-perfect constraint: dark, compact financial analytics UI; high information density; professional typography; restrained cyan/blue accents; green/red semantic market colors; consistent spacing; clearly labeled timestamps and data freshness; responsive cards/charts/tables. Fix false zero values and locale formatting before visual polish. Remove unexplained blank space, but do not overcrowd the dashboard.

## Definition of done
- Root cause is fixed and covered by a regression test for empty candle data.
- Non-empty klines and indicators still validate.
- Missing/stale symbol data is rendered as unavailable, not as `$0.00` or `0.0%` without context.
- API, frontend, and schemas agree on the payload shapes.
- Major pages have coherent loading/empty/stale/error states.
- Frontend build/type check and relevant backend tests are executed.
- Security findings and unresolved limitations are documented in `docs/audit/codebase-audit.md`.
- README run commands reflect the actual implementation.

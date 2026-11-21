# Test Strategy and Execution Plan

**Document ID:** `DP-SPEC-701`  
**Status:** `PROPOSED_PHASE_1_SPEC`  
**Owner:** `@sre-qa` (`WI-DP-01` / `WI-DP-12`)  
**Satisfies:** `REQ-DP-SEC-03`, `TEST-ISO`, all `REQ-DP-*` verification gates

---

## 1. Core Testing Principles

1. **Workspace Data Safety (`TEST-ISO` / `REQ-DP-SEC-03`):** Automated tests MUST NEVER read, modify, or delete live repository `./data/` files or interact with a live user `nats-server` on port `4222`.
2. **External Isolation:** Default test runs MUST NOT depend on Binance REST/WS uptime, Docker, Redis, PostgreSQL, or internet connectivity (`.agent/rules/testing-security.md`).
3. **Regression-First Defect Fixes:** Every defect `D1–D25` identified in Phase 1 MUST have an automated test that fails against AS-IS code and passes once the owning Work Item (`WI-DP-*`) lands.
4. **No Fake Passes:** Conditional skips (`pytest.skip`) MUST NOT mask CI gaps; skipped environment-specific tests (e.g., PostgreSQL) must be reported explicitly as `NOT RUN / SKIPPED`.

---

## 2. Pytest Marker Taxonomy (`pytest.ini`)

Phase 2 (`WI-DP-12`) MUST register the following explicit markers in `pytest.ini`:

| Marker | Scope & Dependencies | Runtime Budget | Included in Default Local/CI Run? |
|---|---|---|---|
| `unit` | Pure Python/NumPy/Pandas/schema validation, dedup cache, error sanitizers, gap math; zero disk/network/broker. | `< 5s` total | **Yes** |
| `integration` | SQLite temp-file / `:memory:` + `InMemoryBroker` + FastAPI `ASGITransport` + mocked Binance REST/WS. | `< 20s` total | **Yes** |
| `pipeline` | Bronze/Silver/Gold Parquet roundtrips, SQL Snapshot Manifests, DuckDB Star Schema snapshot swaps, Workflow DAG transitions in `tmp_path`. | `< 30s` total | **Yes** |
| `system` | Multi-process / live `.bin/nats-server.exe` on an **ephemeral free port + `tmp_path` `store_dir`**; fault injection (`S1–S14`), `ServingGatewayBridge`, worker lease reaping. | `< 60s` total | **Opt-in / Phase 2-3 Gate** (`-m "not system and not performance and not live"` for fast inner loop; full `system` run before acceptance) |
| `fault_injection` | Adversarial failure tests (crash/kill, SQL error, NATS bounce, corrupt Parquet/JSON, disk-full `OSError` simulation). | `< 45s` total | Combined with `integration` or `system` |
| `performance` | Host throughput, RSS peak, DuckDB snapshot latency, `/metrics` under `>= 5,000` files. | `1–5 min` | **Manual / Scheduled Phase 2-3 Gate** |
| `live` | Real Binance REST/WS connectivity smoke checks (`GET /api/v3/ping`, single WS frame). | `< 15s` | **Manual Opt-In Only (`-m live`), NEVER in CI** |

**Default Fast Verification Command:**
```powershell
.venv\Scripts\python.exe -m pytest -v -m "not system and not performance and not live"
```
**Full Local Platform Verification Command (with ephemeral NATS):**
```powershell
.venv\Scripts\python.exe -m pytest -v -m "not live"
```

---

## 3. Four-Stage Verification Architecture

1. **Stage 1 — Static & Contract Gate:**
   - Python syntax/import sanity + Pydantic schema validation (`MarketDataResponseSchema`, `CanonicalKlineEvent`, `CanonicalAggTradeEvent`).
   - Frontend TypeScript type-check & bundle build (`npm test` + `npm run build` via `C:\Program Files\nodejs\npm.cmd`).
   - Alembic migration check (`alembic upgrade head` against isolated temp SQLite DB, plus downgrade/upgrade roundtrip test).
2. **Stage 2 — Unit & Integration Gate (`unit` + `integration` + `pipeline`):**
   - Covers `D1–D25` (excluding host-absent PostgreSQL `D25`), financial stream-vs-batch parity, Lake manifest integrity, DuckDB snapshot swap, API security headers & `X-Admin-Token`, and error sanitization.
3. **Stage 3 — System & Fault-Injection Gate (`system` + `fault_injection`):**
   - Spawns isolated `nats-server.exe` on a random available localhost port (`socket` port `0`) with `-sd <tmp_path>/nats` and isolated `tmp_path` SQLite + Lake + Warehouse dirs.
   - Exercises real multi-process `LITE` and `STANDARD` topologies (`api`, `stream_worker`, `workflow_worker`) across scenarios `S1–S14`.
4. **Stage 4 — Performance & Production Simulation (`performance`):**
   - Populates `TARGET_TO_BE_ESTABLISHED` entries in `DP-SPEC-102` with `>= 3` measured repetitions on this host (`n=3` RSS, E2E latency, flush duration, consumer recovery drain rate, `/metrics` latency with 5k files).

---

## 4. Mandatory `TEST-ISO` Fixture Design (`WI-DP-12`)

`tests/conftest.py` MUST enforce the following safeguards before any Phase 2 code runs:

1. **Session/Function `tmp_path` Override (`autouse=True`):**
   - Monkeypatch `settings.storage.data_dir`, `settings.ml.model_storage_dir`, `settings.streaming.nats_url` (to a closed or test-isolated port unless explicitly testing ephemeral NATS), and `stream_runtime` internal `medallion` / `analytics_engine.checkpoint_dir` / `warehouse` paths to test-scoped `tmp_path`.
   - Ensure `tests/conftest.py` explicitly imports **all** SQLAlchemy model modules (`market`, `forecast`, `ml_model`, `pipeline`, `data_quality`, `governance`, plus new `workflow` / `lake` / `warehouse` models from `WI-DP-05`).
2. **Database Import Side-Effect Removal (`WI-DP-05`):**
   - `backend/app/core/database.py:21-24` MUST NOT run `db_path.mkdir(...)` at module import time when `APP_ENV == "testing"` or when using `:memory:`.
3. **Canary Assertion (`TEST-ISO` Guard):**
   - Capture `(file_count, total_bytes, max_mtime)` snapshot of repository `./data/` before and after the pytest session (in a session-scoped verification test or conftest check) and fail if any file in `./data/` was modified or deleted.
4. **Ephemeral NATS Fixture (`nats_ephemeral_server`):**
   - Allocates free TCP ports (`client_port`, `http_port`) via `socket`, writes temporary `nats.conf` in `tmp_path`, launches `.bin/nats-server.exe`, polls `127.0.0.1:<http_port>/healthz`, yields `nats://127.0.0.1:<client_port>`, and gracefully terminates on teardown (`nats-server --signal quit` or `proc.terminate()`).

---

## 5. CI/CD Strategy (`.github/workflows/ci.yml` Upgrades in `WI-DP-11`)

- **Branch Triggers:** Expand triggers from `[main, master]` to include feature/PR branches (`feat/**`, `pull_request`).
- **Python Version Alignment:** Test on `3.12` (and optionally `3.14` matrix if supported by pinned dependencies) using pinned requirements (`requirements.txt` / lockfile).
- **NATS in CI:** Download pinned `nats-server` Linux tarball (with SHA256 verification) in CI `backend-tests` job so `system` JetStream & KV tests execute rather than silently skipping.
- **Test Execution in CI:**
  - `alembic upgrade head` on temp DB (`$RUNNER_TEMP/ci_test.db`).
  - `APP_ENV=testing pytest -v -m "not performance and not live"`
  - `cd frontend && npm ci && npm test && npm run build`
- **PostgreSQL CI Gap Note:** If CI runs without a PostgreSQL service container, `D25` (`test_postgres_alembic_upgrade`) remains explicitly skipped/marked `NOT RUN` unless a `postgres:16` CI service container is added.

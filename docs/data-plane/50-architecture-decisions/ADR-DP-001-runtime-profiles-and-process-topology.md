# ADR-DP-001: Runtime Profiles & Decoupled Process Topology

- **Status:** Accepted (Phase 1 Baseline)
- **Date:** 2026-11-17
- **Supersedes:** Process-coupling assumptions in `docs/40-adr/ADR-001-runtime-profiles-and-single-node-budget.md` (preserved untouched)
- **Linked Requirements:** `REQ-DP-CFG-01`, `REQ-DP-SRV-01`, `REQ-DP-OBS-01..03`
- **Linked Components:** `COMP-DP-08`, `COMP-DP-09`, `COMP-DP-11`, `COMP-DP-12`

---

## 1. Context & Observed Evidence
- **Host Baseline (`MEASURED` `#6`):** Windows 10 Enterprise, `i5-10600KF` (6C/12T), `31.89 GB` total RAM with **`2.64 GB` currently available** (91.7% utilized by external desktop processes), `78.19 GB` free on `C:` SSD. Docker Desktop, WSL2, Redis, and PostgreSQL are absent on host. `.bin/nats-server.exe v2.15.3` runs natively at `40–63 MB` WS.
- **AS-IS Split-Brain Defect (`OBSERVED` `#7`, `#8`):** `backend/app/streaming/runtime.py:260` creates a process-local singleton `stream_runtime`. In `LITE` (`embedded_in_api=True`, `config.py:285`), uvicorn runs the entire Data Plane in-process. In `STANDARD`/`EXTENDED` (`embedded_in_api=False`, `docker/docker-compose.yml:91,113`), `workers/stream_worker.py` runs in a second process with zero IPC bridge to FastAPI, breaking `WS /ws/market`, `/streaming/*`, `/analytics/incremental`, `/system/resources`, and `/metrics`. Moreover, `run.bat standard` (`run.bat:29-42,160`) never starts `stream_worker.py`.
- **Config & Dependency Drift (`OBSERVED` `#6`, `#7`, `#9`):** `Settings.load()` (`config.py:328-383`) ignores `config.yaml` `data.streams`, `data.api.*`, `ml.*`, and `.env.example` `BINANCE_API_URL`/`BINANCE_FALLBACK_URL`; `requirements.txt` lacks a sync PostgreSQL driver (`psycopg[binary]`) and uses unpinned `>=` ranges (`Python 3.14.10` locally vs `3.12` in `.github/workflows/ci.yml`).

## 2. Options Considered
1. **Option A — Keep `LITE` strictly monolithic in-process & drop decoupled `STANDARD`:** Rejected; violates component decoupling, couples API restarts to WS drops, and leaves `docker-compose.yml` / `stream_worker.py` broken.
2. **Option B — Mandate multi-container Docker Compose (`API + Worker + Postgres + Redis`):** Rejected; Docker/WSL2/Postgres/Redis are absent on host (`#6`), and multi-container overhead threatens the `2.64 GB` free host RAM ceiling.
3. **Option C — Canonical Component Contracts Deployed as Adaptive Native Profiles (`PROPOSED`):** Keep 4 logically decoupled roles (`Ingestor`, `StreamProcessor`, `WorkflowWorker`, `API Gateway`) communicating strictly via NATS Core/KV (`ServingGatewayBridge`) and SQL (`WorkflowEngine`) + immutable snapshots.

## 3. Decision
Adopt **Option C**:
- **Profile `LITE` (Default Local, `<= 450 MB` RSS budget):** Runs `1` `.bin/nats-server.exe` process + `1` Python `uvicorn` process (`STREAM_EMBEDDED_IN_API=true`) composing the **exact same** `ServingGatewayBridge`, `HotStateCache`, and `WorkflowEngine` async tasks over localhost NATS loopback—preserving low RSS (`~290–341 MB` measured baseline `#6`/`docs/10-audit/final-resource-usage-report.md`) with zero split-brain code paths.
- **Profile `STANDARD` (Native Multi-Process, `<= 950 MB` RSS budget):** Runs `.bin/nats-server.exe` + `3` decoupled Python processes (`uvicorn` API/Bridge, `backend.app.workers.stream_worker`, `backend.app.workers.workflow_worker`) sharing SQLite WAL (or optional Postgres when provisioned) and immutable Lake/Warehouse snapshots. `run.bat standard` launches and supervises all worker processes cleanly.
- **Profile `EXTENDED` (Optional):** Retains optional Docker Compose (`MinIO`, `Prometheus`, `Grafana`, `Postgres`) cleanly marked `UNVERIFIED` on host until external services exist, with fixed `docker/nats/nats.conf` profile sizing and `psycopg[binary]>=3.2.0,<4.0` + `postgresql+psycopg://` URI normalization in `requirements.txt`.
- Unify `Settings.load()` (`IFC-DP-011`) across `config.yaml`, `.env`, and env vars, and pin reproducible package bounds in `requirements.txt`.

## 4. Consequences
- **Positive:** Identical API, WS, and telemetry semantics in `LITE` and `STANDARD`; zero mandatory Docker/WSL2/Redis footprint on Windows; strict single-node RAM compliance.
- **Negative / Mitigation:** Multi-process `STANDARD` adds ~200–250 MB Python runtime RSS across 3 processes (`TARGET_TO_BE_ESTABLISHED`), so `LITE` remains the recommended default when host free RAM is tight (`2.64 GB`). Per-process metrics aggregation (`WI-DP-10`) is required so `/metrics` covers all processes.

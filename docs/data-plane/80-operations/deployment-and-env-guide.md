# Deployment and Environment Guide

**Document ID:** `DP-SPEC-801`  
**Status:** `PROPOSED_PHASE_1_SPEC`  
**Owner:** `@sre-qa` (`WI-DP-01` / `WI-DP-11`)  
**Applies To:** Single-node Windows native (`LITE`, `STANDARD`) & containerized Linux (`STANDARD`, `EXTENDED`)

---

## 1. Host Toolchain Realities (`DP-SPEC-001` Verified)

On the authoritative Windows workstation (`i5-10600KF`, `31.89 GB` RAM / **`2.64 GB` currently free**, `78.19 GB` free on `C:`):

| Dependency | Host Reality (`MEASURED`) | Operational Guidance |
|---|---|---|
| **Python `.venv`** | `.venv\Scripts\python.exe` (`3.14.10`) | Always invoke `.venv\Scripts\python.exe` / `.venv\Scripts\uvicorn.exe` / `.venv\Scripts\alembic.exe` directly; set `PYTHONPATH=.`. |
| **NATS JetStream** | `.bin\nats-server.exe` (`v2.15.3`) | Native binary; **no Docker or WSL2 needed**. |
| **Node.js / npm** | `C:\Program Files\nodejs\node.exe` (`v26.13.1`) / `npm.cmd` (`11.20.0`) | Not on default shell `PATH`; prepend `C:\Program Files\nodejs` before running `setup.bat` or `npm run build`. |
| **Git** | `C:\Program Files\Git\cmd\git.exe` (`2.56.1`) | Not on default shell `PATH`; invoke by full path or add to `PATH`. |
| **Docker / WSL2 / Redis / PostgreSQL** | **NOT AVAILABLE** on this host | Native Windows execution uses **SQLite WAL + NATS JetStream (`FILE` streams + `MEMORY` KV) + Local Lake + DuckDB Snapshots**. Docker Compose (`STANDARD`/`EXTENDED` with PostgreSQL/MinIO/Prometheus) applies only to Docker-capable hosts and requires adding `psycopg[binary]>=3.2.0,<4.0` (with `postgresql+psycopg://` sync URL normalization) to `requirements.txt` (`WI-DP-05` / `WI-DP-11`). |

---

## 2. Deployment Profile Topologies (`ADR-DP-001`)

### Profile A: `LITE` (Recommended for Current Host)
- **Processes:** `nats-server.exe` (`1` native process, ~`43–64 MB` RSS) + `uvicorn backend.app.main:app` (`1` Python process running API + embedded `StreamRuntime` + optional in-process workflow worker loop or companion `workflow_worker`).
- **Storage & State:** SQLite WAL (`./data/crypto_market.db`), Local FS Medallion (`./data/{bronze,silver,gold}`), DuckDB Staging -> `dw-v{N}.duckdb` snapshots (`./data/warehouse/`), NATS JetStream `FILE` streams (`64 MB` mem / `128 MB` file) + `MEMORY` KV (`8 MB` `hot_state` + `1 MB` `worker_heartbeats`).
- **Binding:** `127.0.0.1:8000` (HTTP/WS), `127.0.0.1:4222` (NATS), `127.0.0.1:8222` (NATS HTTP monitor).

### Profile B: `STANDARD` (3-Process Decoupled Single-Node)
- **Processes (`WI-DP-11` fixes `run.bat standard`):**
  1. `nats-server.exe` (`128 MB` mem / `512 MB` file; `16 MB` `hot_state` KV)
  2. `backend.app.workers.stream_worker` (`StreamProcessor` + `BinanceWebSocketIngestor` + `BoundedEventProducer` -> `ServingGatewayBridge`)
  3. `backend.app.workers.workflow_worker` (Durable SQL DAG executor + sole `WarehouseService` DuckDB writer + gap-heal + ML training + retention)
  4. `uvicorn backend.app.main:app --host 127.0.0.1 --port 8000` (`STREAM_EMBEDDED_IN_API=false`, stateless API & WS gateway)
- **Note on AS-IS `run.bat standard`:** Currently launches **only** `uvicorn` without `stream_worker` or `workflow_worker` (`run.bat:29-34,160`); Phase 2 (`WI-DP-11`) must add multi-process supervisor scripts or a dedicated launcher (`scripts/start_standard.ps1`).
- **Database:** SQLite WAL (native Windows) or PostgreSQL 16 (Docker/Linux once `psycopg` sync driver lands in `WI-DP-05`).

### Profile C: `EXTENDED` (High-Memory / Container Host Only)
- Intended for hosts with `>= 4 GB` free RAM (`total_memory_mb = 2048 MB`, MinIO/S3, Prometheus, Grafana). **Not recommended** on the current host while external apps leave `2.64 GB` free RAM.

---

## 3. Preflight and Startup Sequence (Windows Native)

1. **Check Environment & Dependencies:**
   ```powershell
   $env:PYTHONPATH = "."
   $env:PATH = "C:\Program Files\nodejs;C:\Program Files\Git\cmd;$env:PATH"
   .\.venv\Scripts\python.exe --version
   .\.bin\nats-server.exe --version
   ```
2. **Verify `.env` Configuration (without overwriting existing `.env`):**
   - Ensure `PLATFORM_PROFILE=lite` (or `standard`), `BROKER_BACKEND=nats`, `NATS_URL=nats://127.0.0.1:4222`, `DATA_DIR=./data`.
   - Set `ADMIN_API_TOKEN` whenever exposing HTTP beyond localhost or running non-dev security checks.
   - Set `LOG_FORMAT=json` for machine-parseable operational logs.
3. **Run Database Migrations Before Starting App or Workers:**
   ```powershell
   $env:PYTHONPATH = "."
   .\.venv\Scripts\alembic.exe upgrade head
   ```
4. **Start NATS JetStream (`LITE` or `STANDARD`):**
   - Check if port `4222` is already listening (`Get-NetTCPConnection -LocalPort 4222 -State Listen`), and verify JetStream `max_memory_store` / `max_file_store` via `http://127.0.0.1:8222/jsz` match the selected profile (`scripts/start_nats.ps1` must be upgraded in `WI-DP-11` to verify JetStream config rather than blindly exiting `0`).
5. **Start Runtime Processes:**
   - **LITE:** `.\run.bat lite --no-pause` (or `.\scripts\start_lite.ps1`).
   - **STANDARD (Phase 2 target):** Start `stream_worker`, `workflow_worker`, and `uvicorn` (with `STREAM_EMBEDDED_IN_API=false`), confirming `worker_heartbeats` in `/api/v1/streaming/status` and `/api/v1/system/resources`.
6. **Verify Live Endpoints:**
   - `GET http://127.0.0.1:8000/api/v1/health` -> HTTP `200`, `status: "healthy"`
   - `GET http://127.0.0.1:8000/metrics` -> Prometheus payload containing `platform_disk_free_bytes`, `platform_host_ram_available_bytes`
   - `GET http://127.0.0.1:8222/jsz` -> `MARKET_EVENTS` & `MARKET_DLQ` active, `hot_state` & `worker_heartbeats` KV buckets initialized.

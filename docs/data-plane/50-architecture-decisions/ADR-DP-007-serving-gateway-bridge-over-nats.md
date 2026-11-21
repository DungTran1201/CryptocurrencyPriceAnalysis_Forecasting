# ADR-DP-007: Canonical Cross-Process `ServingGatewayBridge` Over NATS Core & JetStream KV

- **Status:** Accepted (Phase 1 Baseline)
- **Date:** 2026-11-17
- **Realizes:** `ServingGatewayBridge` (`C3`) referenced in `docs/30-architecture/system-architecture.md:79,88`
- **Linked Requirements:** `REQ-DP-SRV-01`, `REQ-DP-SEC-01..02`, `REQ-DP-OBS-01`
- **Linked Components:** `COMP-DP-08`, `COMP-DP-11`, `COMP-DP-12`

---

## 1. Context & Observed Evidence (`OBSERVED` / `MEASURED` `#7`, `#8`, `#16`)
1. **Docs-Only Component & Process Split-Brain (`OBSERVED` `#7`, `#8`):** `docs/30-architecture/system-architecture.md:79,88` draws `C3["ServingGatewayBridge"]` feeding FastAPI, yet no such module exists. Instead, `MedallionStreamConsumer` directly invokes in-process `ws_hub.publish_symbol_update(...)` (`consumers.py:272, 298`). When `STREAM_EMBEDDED_IN_API=false` (`STANDARD`/`EXTENDED`), `stream_worker.py` runs in a separate OS process while FastAPI endpoints (`/streaming/status`, `/streaming/flush`, `/streaming/simulate-disconnect`, `/ws/market`, `/analytics/incremental`, `/system/resources`) read/control FastAPI's unstarted `stream_runtime` singleton (`runtime.py:260`), yielding empty snapshots, dead WebSockets, and no-op control endpoints.
2. **NATS Core Performance (`MEASURED` `#16`):** NATS Core pub/sub roundtrip on host measured **`0.243 ms` avg (`p95 0.421 ms`)**, making cross-process tick fan-out and control request-reply virtually zero-overhead.
3. **Security & Error Boundary Gaps (`OBSERVED` `#6`, `#8`):** `POST /forecasts/generate`, `POST /forecasts/reconcile`, and `POST /data-quality/evaluate` omit `require_admin_if_configured`; `PipelineRun.error_message` (`pipelines.py:87`), `broker.py:360`, and HTTP 400 handlers leak raw `str(e)`.

## 2. Options Considered
1. **Option A — Expose Direct HTTP Control Endpoints Inside `stream_worker` + Reverse Proxy from FastAPI:** Rejected; requires assigning/managing a second HTTP port on Windows, extra HTTP server dependencies in `stream_worker`, and custom discovery.
2. **Option B — Have FastAPI Open Its Own Separate JetStream Durable Pull Consumer (`C3`) on `MARKET_EVENTS`:** Rejected for high-frequency `aggTrade` ticks; duplicates JSON parsing and `IncrementalAnalyticsEngine` computation in two processes, risking CPU/RAM spikes under `LITE` (`450 MB`) and divergence between consumer state and UI state.
3. **Option C — Canonical `ServingGatewayBridge` Over NATS Core + JetStream KV (`PROPOSED`):** `StreamWorker` publishes already-computed coalesced snapshots, closed-bar events, and control responders over NATS Core/KV (`IFC-DP-002`, `IFC-DP-004`), consumed identically by FastAPI in both `LITE` and `STANDARD`.

## 3. Decision
Adopt **Option C** (`backend/app/streaming/serving_bridge.py`):
1. **Worker Publish Side (`StreamWorker` / `WorkflowWorker`):**
   - Publishes coalesced symbol/analytics snapshots to NATS Core `serving.market.<SYMBOL>` (`0.24 ms` latency) and updates `hot_state` KV (`market.snapshot.<SYMBOL>`, `forecast.latest.<SYMBOL>`).
   - Publishes `serving.events.closed_bar` strictly **after** `SQL_COMMITTED`, triggering cache invalidation and bounded inference.
   - Publishes worker health/metrics/lag heartbeats every `2s` to `worker_heartbeats` KV (`TTL=15s`, auto-expiring on crash) and `serving.system.status`.
   - Subscribes to NATS Core request-reply subjects `serving.control.flush` and `serving.control.simulate_disconnect` to execute actions inside the active `StreamWorker`.
2. **API Gateway Subscribe Side (FastAPI `lifespan`):**
   - Always runs `ServingGatewayBridge` subscriber feeding `WSBroadcastHub` (`/api/v1/ws/market`) and updating local bounded `TTLCache`.
   - When `embedded_in_api=False`, FastAPI does **NOT** instantiate `BinanceWebSocketIngestor`, `BoundedEventProducer`, `MedallionStreamConsumer`, or duplicate `enforce_retention()` loops (`main.py`, `runtime.py`).
   - `POST /streaming/flush` and `POST /streaming/simulate-disconnect` issue NATS `nc.request("serving.control.*", timeout=5.0)` (returning HTTP `503` if no worker responds); `GET /streaming/status`, `GET /analytics/incremental`, and `GET /system/resources` read `hot_state` + `worker_heartbeats` KV.
3. **API Hardening Alignment:** Enforce `require_admin_if_configured` on all remaining mutating endpoints and sanitize all error responses (`error_code` + safe summary, zero `str(e)` leakage).

## 4. Consequences
- **Positive:** Eliminates `STANDARD` split-brain completely, prevents duplicate tick parsing/analytics compute, preserves identical behavior between `LITE` (loopback) and `STANDARD` (multi-process), and auto-detects dead workers in `<= 15s` via NATS KV TTL.
- **Negative / Mitigation:** Requires live NATS server for bridge fan-out; if NATS is momentarily disconnected, `GET /system/resources` & `/streaming/status` truthfully report `DEGRADED / DISCONNECTED` and REST data routes fall back cleanly to SQLite WAL / `dw-v{N}.duckdb`.

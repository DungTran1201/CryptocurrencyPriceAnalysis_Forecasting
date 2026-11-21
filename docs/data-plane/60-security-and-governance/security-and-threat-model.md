# Security and Threat Model

**Document ID:** `DP-SPEC-601`  
**Status:** `PROPOSED_PHASE_1_SPEC`  
**Owner:** `@sre-qa` (`WI-DP-01` / `WI-DP-13` / `WI-DP-12`)  
**Satisfies:** `REQ-DP-SEC-01`, `REQ-DP-SEC-02`, `REQ-DP-SEC-03`

---

## 1. Trust Boundaries and Assets

| Zone / Boundary | Components | Trust Level | Key Assets & Threats |
|---|---|---|---|
| **Zone 0: External Public Internet** | Binance REST (`data-api.binance.vision`, `api.binance.com`), Binance WS (`data-stream.binance.vision:9443`), GitHub Releases (`install_nats.ps1`) | **Untrusted** | Spoofed/malformed JSON payloads, extreme numeric outliers, upstream disconnect floods, unverified binary downloads (`install_nats.ps1`). |
| **Zone 1: Local / Container Network** | `nats-server` (`127.0.0.1:4222`, `:8222`), optional PostgreSQL / MinIO | **Semi-Trusted (Local)** | Unauthenticated NATS TCP/HTTP ports if bound to `0.0.0.0`; JetStream resource exhaustion. |
| **Zone 2: Data Plane Storage & DB** | `./data/{bronze,silver,gold,warehouse,checkpoints,dlq}`, `crypto_market.db` | **Trusted Internal** | Path traversal on storage keys, SQL injection in DuckDB SQL templates, test-induced deletion (`TEST-ISO`). |
| **Zone 3: FastAPI HTTP / WS Gateway** | `uvicorn` (`127.0.0.1:8000`), `/api/v1/*`, `/metrics`, `/docs` | **Boundary Edge** | Unauthenticated mutation endpoints, DoS via heavy inline `POST` training/sync or `rglob`, raw exception/path leakage, unrestricted CORS credentials. |

---

## 2. AS-IS Security Defects (`OBSERVED`)

| Defect ID | Severity | Observed File & Line | Description & Impact |
|---|---|---|---|
| **SEC-GAP-01** | **HIGH** | `backend/app/api/v1/forecast.py:25,102`<br>`backend/app/api/v1/data_quality.py:122` | `POST /api/v1/forecasts/generate`, `POST /api/v1/forecasts/reconcile`, and `POST /api/v1/data-quality/evaluate` **omit** `Depends(require_admin_if_configured)`. Even when `ADMIN_API_TOKEN` is set, anyone can mutate forecast/DQ tables or trigger compute. |
| **SEC-GAP-02** | **HIGH** | `backend/app/services/pipeline_service.py:433`<br>`backend/app/api/v1/pipelines.py:87`<br>`backend/app/streaming/broker.py:360`<br>`backend/app/api/v1/market.py:95`<br>`backend/app/api/v1/forecast.py:41`<br>`backend/app/api/v1/models.py:123` | Raw exception strings (`str(e)`, `str(exc)`, `str(ve)`) are persisted and exposed to HTTP/WS clients via `PipelineRun.error_message`, `/api/v1/streaming/status`, `WS /ws/market`, and HTTP `400` `detail` strings — risking disclosure of filesystem paths, SQL snippets, or NATS internals. |
| **SEC-GAP-03** | **HIGH** | `tests/test_api_and_security.py:68-73` | `POST /api/v1/governance/retention/run` executes against live `./data/` without `tmp_path` isolation (`TEST-ISO`), risking deletion of real Bronze files older than 3 days. |
| **SEC-GAP-04** | **MEDIUM** | `scripts/recover_platform.ps1:22-33` | Unescaped PowerShell `$Symbol` / `$Timeframe` interpolation inside `python -c "..."` allows command injection if script parameters come from untrusted automation. |
| **SEC-GAP-05** | **MEDIUM** | `scripts/install_nats.ps1:13-22` | Downloads `nats-server` ZIP from GitHub latest release **without SHA256 checksum verification** or version pinning. |
| **SEC-GAP-06** | **MEDIUM** | `backend/app/api/v1/data_explorer.py:145,284`<br>`backend/app/api/v1/data_quality.py:122`<br>`backend/app/api/v1/market.py:45-53` | `data_explorer` and `data_quality` omit `validate_symbol()` / `validate_timeframe()`. `market.py` duplicates inline symbol/timeframe checks (`len >= 1`) that diverge from `core/security.py:16` (`len >= 3`). |
| **SEC-GAP-07** | **MEDIUM** | `backend/app/main.py:78-84`<br>`backend/app/api/v1/streaming.py:31-55` | No rate-limiting middleware exists on mutation or heavy read routes (`/models/train`, `/pipelines/trigger`, `/data-explorer/export`). `/streaming/dlq` exposes raw failed payload prefixes (`payload_preview` / `error_reason`) and `/metrics` / `/system/resources` are unauthenticated. |
| **SEC-GAP-08** | **LOW** | `backend/app/core/config.py:220` | `ADMIN_API_TOKEN` defaults to `None`; `require_admin_if_configured` (`core/security.py:35-37`) silently allows all mutations when unset even if `APP_ENV=production`. |

---

## 3. Target Security Controls

### 3.1 Authentication & Privilege Boundaries (`REQ-DP-SEC-01`)
1. **Complete Mutation Route Coverage:** Apply `Depends(require_admin_if_configured)` to **every** mutating/compute endpoint:
   - Existing: `POST /market/sync`, `POST /models/train`, `POST /pipelines/trigger`, `POST /streaming/flush`, `POST /streaming/replay`, `POST /streaming/simulate-disconnect`, `POST /governance/retention/run`.
   - **Add (`WI-DP-13` / `WI-DP-09`):** `POST /api/v1/forecasts/generate`, `POST /api/v1/forecasts/reconcile`, `POST /api/v1/data-quality/evaluate`.
   - **Add (`WI-DP-07`):** New workflow mutation routes `POST /api/v1/pipelines/runs/{run_id}/cancel` and `POST /api/v1/pipelines/schedules*`.
2. **Constant-Time Token Comparison:** Retain `secrets.compare_digest(x_admin_token, expected)` (`backend/app/core/security.py:38`).
3. **Production Startup Warning / Fail-Closed Mode:** When `APP_ENV == "production"` and `ADMIN_API_TOKEN` is empty/unset, log an explicit `CRITICAL` security warning (or fail closed when `REQUIRE_AUTH_IN_PRODUCTION=true` per `IFC-DP-011`).
4. **Network Binding Defaults:** Local launchers (`run.bat`, `start_lite.ps1`, `start_nats.ps1`) MUST bind FastAPI and `nats-server` to `127.0.0.1` by default, never `0.0.0.0`, unless explicitly configured for containerized reverse-proxy deployment.

### 3.2 Error Sanitization (`REQ-DP-SEC-02`)
1. **API & Persistent Error Fields:**
   - Replace raw `str(e)` stored in `PipelineRun.error_message`, `WorkflowRun`, `SyncCheckpoint.last_error`, and `NatsJetStreamBroker.get_stream_info()["error"]` with a bounded canonical `error_code` (e.g., `UPSTREAM_TIMEOUT`, `DQ_GATE_FAILED`, `BROKER_DISCONNECTED`, `STORAGE_IO_ERROR`, `INTERNAL_ERROR`) plus a human-safe summary stripped of filesystem paths (`C:\...`, `/app/...`), SQL statements, hostnames, and stack traces.
   - Keep full exception details and tracebacks exclusively in structured server logs (`core/logging.py`), never in HTTP responses or WS broadcasts.
2. **Validation Errors (`400` / `422`):** Return deterministic messages from `validate_symbol` / `validate_timeframe` / Pydantic field validators; wrap unexpected `ValueError` in `market.py`, `forecast.py`, and `models.py` with sanitized messages rather than arbitrary `str(ve)`.

### 3.3 Input Validation, Storage & Supply-Chain Hardening
1. **Unified Boundary Validators:** Enforce `validate_symbol` (`3..20` alphanumeric uppercase) and `validate_timeframe` allowlist across `market.py`, `analytics.py`, `forecast.py`, `models.py`, `pipelines.py`, `data_quality.py`, and `data_explorer.py`. Enforce `open_time <= close_time` and timeframe allowlist in `CanonicalKlineEvent` (`schemas/events.py`, `IFC-DP-001`).
2. **Storage & SQL Injection Safety:**
   - Preserve `LocalStorageBackend._safe_path()` containment check (`local.py:18-23`) and add identical key normalization/containment checks before passing `read_parquet(...)` glob paths into DuckDB (`duckdb_engine.py`, `medallion.py`).
   - Use parameterized DuckDB queries (`?` bindings) for all filter values (`symbol`, `timeframe`, timestamps).
3. **PowerShell & Binary Supply Chain (`WI-DP-11`):**
   - Refactor `scripts/recover_platform.ps1` to pass arguments via `sys.argv` (avoiding inline string interpolation into `python -c`).
   - Pin `nats-server` release version and verify SHA256 checksum in `scripts/install_nats.ps1` (`v2.15.3`).
4. **Rate Limiting & Payload Bounds:**
   - Add lightweight in-memory token-bucket rate limiting middleware (per client IP + route group) for expensive `POST` triggers (`/models/train`, `/pipelines/trigger`, `/market/sync`, `/data-explorer/export`) with `429 Too Many Requests` (`Retry-After` header).
   - Keep `max_payload: 1MB` on NATS JetStream, `limit <= 5000` on CSV exports, and `page_size <= 100` on Explorer previews.
5. **CORS & Security Headers:** Maintain `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` (`main.py:88-94`); keep `cors_origins` explicit (never wildcard `*` with `allow_credentials=True`).

### 3.4 Test & Workspace Data Isolation (`REQ-DP-SEC-03` / `TEST-ISO`)
1. `tests/conftest.py` MUST provide an `autouse` fixture redirecting `settings.storage.data_dir`, `settings.ml.model_storage_dir`, `stream_runtime` checkpoint paths, and SQLite DB URLs to `tmp_path`.
2. Any test invoking `GovernanceService.enforce_retention()`, `MedallionStorageManager`, `WarehouseService`, or `StreamPlatformRuntime` MUST be verified never to create, modify, or delete files inside repository `./data/`.

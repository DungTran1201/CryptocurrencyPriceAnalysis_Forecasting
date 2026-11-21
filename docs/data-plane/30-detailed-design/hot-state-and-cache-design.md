# Hot State and Cache Detailed Design

- **Document ID:** `DD-DP-HOT-001`
- **Status:** `PROPOSED` (Specification Baseline v1.0)
- **Owner:** `@stream-orch` (Phase 1 Step 2)
- **Traceability:**
  - Requirements: `REQ-DP-HOT-01`, `REQ-DP-SRV-01`, `REQ-DP-OBS-01`
  - Components: `COMP-DP-07` (HotStateCache), `COMP-DP-08` (ServingGatewayBridge), `COMP-DP-11` (API Gateway)
  - ADRs: `ADR-DP-005`, `ADR-DP-007`
  - Interfaces: `IFC-DP-002`, `IFC-DP-004`, `IFC-DP-009`, `IFC-DP-011`
  - Phase 2 Work Items: `WI-DP-08`, `WI-DP-11`

---

## 1. Purpose and Architectural Rationale

In `STANDARD` and `EXTENDED` modes (`embedded_in_api=False`), ingestion and stream processing run in `StreamWorker`, batch DAGs/ML run in `WorkflowWorker`, and HTTP/WebSocket serving runs in the FastAPI API process. AS-IS `stream_runtime` is a process-local singleton (`runtime.py:260`), causing split-brain empty responses (`streaming.py:26`, `analytics.py:72`, `system.py:71`, `WS /ws/market`).

Per host measurements (`#6`: `0` Redis binary, `0` Docker/WSL2, `2.64 GB` free host RAM) and empirical NATS KV probes (`#16`), this platform adopts **NATS JetStream KeyValue (`StorageType.MEMORY`) + Bounded In-Process `TTLCache`** behind a clean `HotStateCache` protocol (`IFC-DP-009`), rather than deploying Redis on the single-node Windows host.

---

## 2. Empirical Probe Evidence Driving StorageType Selection (`[MEASURED]` #16)

- **Why `StorageType.FILE` Cannot Be Used for Hot State KV**:
  - Under LITE (`max_file_store = 128 MB`), `MARKET_EVENTS` (75%) + `MARKET_DLQ` (20%) reserve `127,506,841 B` (`121.6 MB`), leaving only `6.40 MB` unreserved file storage.
  - Creating a `StorageType.FILE` KV bucket of `8 MB` **failed** with `nats: ServerError: code=500 err_code=10047 description='insufficient storage resources available'`.
- **Why `StorageType.MEMORY` Succeeds**:
  - `max_memory_store = 64 MB` had `0 B` reserved (`64 MB` free).
  - Measured `StorageType.MEMORY` (`4 MB` bucket, `ttl=1.5s`, `history=1`): `create = 0.858 ms`, `put = 0.231 ms avg (0.423 ms p95)`, `get = 0.362 ms avg (0.644 ms p95)`, `watch = 1.306 ms e2e`, server-side TTL expiry verified, `/varz` process memory overhead negligible (`0 B` RSS jump during puts).
  - NATS Core pub/sub roundtrip: `0.243 ms avg (0.421 ms p95)`.

---

## 3. `HotStateCache` Protocol (`COMP-DP-07`, `IFC-DP-009`)

Defined in `backend/app/streaming/hot_state.py`:

```python
class HotStateCache(Protocol):
    async def get_json(self, namespace: str, key: str) -> Optional[Dict[str, Any]]: ...
    async def put_json(
        self,
        namespace: str,
        key: str,
        value: Dict[str, Any],
        ttl_sec: Optional[float] = None,
    ) -> None: ...
    async def delete(self, namespace: str, key: str) -> None: ...
    async def list_prefix(self, namespace: str, prefix: str = "") -> Dict[str, Dict[str, Any]]: ...
    async def invalidate_local(self, namespace: str, key_prefix: str = "") -> int: ...
    def stats(self) -> Dict[str, Any]: ...
    async def close(self) -> None: ...
```

### 3.1 Tiered Implementation (`TieredHotStateCache`)

1. **L1 — Bounded In-Process `TTLCache`** (`OrderedDict` LRU, default `maxsize=512`, `ttl=2.0s` for snapshots, `30.0s` for slow-changing summaries):
   - Prevents repeated NATS network/IPC roundtrips during API burst polls.
   - Evicts oldest keys strictly at `maxsize` (`<= ~2 MB` heap cap).
   - Actively invalidated in FastAPI upon receiving `serving.events.closed_bar` over NATS Core (`ServingGatewayBridge`).
2. **L2 — NATS JetStream KeyValue (`NatsKVHotStateBackend`)**:
   - Reads/writes JSON payloads via `js.key_value(bucket)`.
   - Maps `(namespace="hot_state", key)` -> bucket `hot_state` and `(namespace="worker_heartbeats", key)` -> bucket `worker_heartbeats`.
3. **Future Multi-Node Extension (`RedisHotStateBackend`, Deferred)**:
   - Implementing `HotStateCache` against `redis.asyncio` remains pluggable for multi-host horizontal scaling in `EXTENDED` cluster deployments without modifying callers, but is NOT enabled or claimed active on the single-node Windows host.

---

## 4. Bucket, Key Taxonomy, TTLs, and Eviction Policy (`IFC-DP-004`)

Because NATS JetStream KV enforces `ttl` at the **bucket level** (`KeyValueConfig.ttl`, verified in `nats-py 2.16.0`), keys with distinct freshness lifetimes are separated into two `StorageType.MEMORY` buckets:

| Bucket | Storage | `history` | Bucket `ttl` | `max_bytes` (LITE / STD / EXT) | Keys & Producers |
|---|---|---|---|---|---|
| `hot_state` | `StorageType.MEMORY` | `1` | `300.0s` (5 min) | `8 MB` / `16 MB` / `32 MB` | `market.snapshot.{SYMBOL}`, `analytics.inc.{SYMBOL}.{TF}`, `forecast.latest.{SYMBOL}`, `stream.status.latest` |
| `worker_heartbeats` | `StorageType.MEMORY` | `1` | `15.0s` | `1 MB` / `2 MB` / `4 MB` | `worker.stream.{worker_id}`, `worker.workflow.{worker_id}` |

### 4.1 Key Design & Payloads

1. **`hot_state` / `market.snapshot.{SYMBOL}`**:
   - Written by `StreamProcessor` (`MedallionStreamConsumer`) on coalesced interval (`ws_coalesce_interval_ms`) and immediately post-commit on closed candles.
   - Payload: `{symbol, live_price, live_trade_qty, live_trade_time, live_trades_count, live_vwap, kline_1m, analytics, source, committed_seq, updated_at}`.
2. **`hot_state` / `forecast.latest.{SYMBOL}`**:
   - Written ONLY after `SQL_COMMITTED` closed-candle forecast insertion (`REQ-DP-DEL-05`).
   - Payload: `{forecast_id, symbol, timeframe, horizon_steps, predicted_price, predicted_direction, model_id, data_cutoff_time, triggered_at}`.
3. **`hot_state` / `stream.status.latest`**:
   - Published every `2.0s` by `StreamWorker` containing `{profile, ingestor, producer, consumer, pipeline_flow, updated_at}`.
4. **`worker_heartbeats` / `worker.{role}.{worker_id}`**:
   - Published every `3.0s` by `StreamWorker` and `WorkflowWorker`.
   - Auto-expires after `15.0s` if a worker crashes (`KeyNotFoundError`), giving `/api/v1/system/resources` and `/api/v1/health` deterministic liveness detection (`DEAD`/`STALE` vs `ALIVE`).

### 4.2 Eviction & Bounded Memory Guarantees

- Setting `history=1` ensures NATS KV keeps only the latest revision per key (plus compact delete markers), avoiding history bloat.
- Setting `max_bytes` per bucket bounds JetStream memory strictly inside `streaming.nats_max_mem_mb` (`64 MB` LITE -> max `9 MB` for KV = `14%` of memory budget, leaving `55 MB` headroom).
- Server-side `DiscardPolicy` on KV streams discards oldest entries if `max_bytes` is ever approached; `max_value_size` is capped at `262144` (256 KB) to reject oversized payloads.

---

## 5. Cache Invalidation, Cold Rebuild, and Degraded Mode

### 5.1 Event-Driven Invalidation (`serving.events.closed_bar`)
- Upon `SQL_COMMITTED` of a closed candle in `MedallionStreamConsumer`, `ServingGatewayBridge` publishes `serving.events.closed_bar` (`{symbol, timeframe, open_time, close_time, snapshot_id}`) onto NATS Core.
- FastAPI's `ServingGatewayBridge` subscriber receives the message (`~0.24 ms`) and:
  1. Evicts L1 `TTLCache` entries for `(symbol, timeframe)` (market summaries, analytics snapshots, warehouse query cache).
  2. Pushes the updated bar/forecast snapshot into `WSBroadcastHub` for browser clients.

### 5.2 Rebuild from SQL & Data Lake on Cold Start / Eviction
- Because `hot_state` is strictly an **ephemeral serving optimization** (never a source of truth):
  - If NATS restarts (`StorageType.MEMORY` clears) or a key expires after `300s`:
    - `IncrementalAnalyticsEngine` restores rolling indicator buffers from atomic `data/checkpoints/analytics_{SYM}_{TF}.json` (or falls back to reconstructing the last `online_window_max_bars` closed bars from Silver Parquet / SQL `klines`), then repopulates `hot_state`.
    - API `GET /analytics/incremental` and `GET /streaming/status` inspect `hot_state` KV first; on cache miss, fall back cleanly to persisted SQL checkpoints / DuckDB Warehouse snapshot with explicit `state_freshness = "COLD_CACHE_RECOVERED"` or `"STALE"` rather than returning fake zeros.

### 5.3 Degraded Mode When NATS Broker Is Unavailable
- If NATS is temporarily disconnected (`not broker.is_connected()`):
  - L2 KV calls fail fast (bounded timeout `<= 0.5s`) without blocking HTTP handlers.
  - `TieredHotStateCache` falls back to serving any unexpired L1 `TTLCache` entry flagged with `"degraded": true, "cache_source": "l1_stale"`, or returns HTTP `503` / explicit `"DEGRADED"` status on control commands (`POST /streaming/flush`, `POST /streaming/simulate-disconnect`) and status probes (`REQ-DP-SRV-01`).
  - Browser WebSocket clients (`WS /ws/market`) continue receiving heartbeat frames plus a `"status": "BROKER_DEGRADED"` notice instead of silently pretending data is live.

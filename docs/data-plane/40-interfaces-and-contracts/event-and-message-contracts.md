# Event and Message Contracts

- **Document ID:** `IFC-DP-001` / `002` / `003` / `004` / `009`
- **Status:** `PROPOSED` (Specification Baseline v1.0)
- **Owner:** `@stream-orch` (Phase 1 Step 2)
- **Traceability:**
  - Requirements: `REQ-DP-ING-01..04`, `REQ-DP-DEL-01..06`, `REQ-DP-HOT-01`, `REQ-DP-SRV-01`
  - Components: `COMP-DP-01`, `COMP-DP-02`, `COMP-DP-03`, `COMP-DP-07`, `COMP-DP-08`
  - ADRs: `ADR-DP-002`, `ADR-DP-005`, `ADR-DP-007`
  - Phase 2 Work Items: `WI-DP-02`, `WI-DP-03`, `WI-DP-08`

---

## 1. `IFC-DP-001` — Canonical Market Event Schemas (v1.1.0)

Defined in `backend/app/schemas/events.py` (`CANONICAL_EVENT_SCHEMA_VERSION = "1.1.0"`). Backward compatible with v1.0.0 consumers (`schema_version` accepts `"1.0.0"` and `"1.1.0"`).

### 1.1 `CanonicalAggTradeEvent`

| Field | Type | Constraints / Validation | Notes |
|---|---|---|---|
| `schema_version` | `str` | Default `"1.1.0"` | Semver string |
| `event_id` | `str` | Non-empty (`aggTrade:{SYMBOL}:{agg_trade_id}`) | Used as `Nats-Msg-Id` & post-commit dedup key |
| `event_type` | `Literal["aggTrade"]` | `"aggTrade"` | Discriminator |
| `source` | `str` | `"binance_ws"` or `"binance_rest_backfill"` | Provenance tracking |
| `symbol` | `str` | Alphanumeric uppercase (`3..20` chars) | Normalized `.upper()` |
| `agg_trade_id` | `int` | `ge=0` | Monotonic Binance trade ID |
| `price` | `float` | `gt=0.0` AND `math.isfinite` | Rejects `NaN`/`Inf`/`<=0` |
| `quantity` | `float` | `ge=0.0` AND `math.isfinite` | Base asset qty |
| `quote_quantity` | `float` | `ge=0.0` AND `math.isfinite` | `round(price * quantity, 8)` |
| `is_buyer_maker` | `bool` | Required | Maker side flag |
| `event_time` | `datetime` | Normalized via `ensure_utc_naive()` | Exchange event time |
| `trade_time` | `datetime` | Normalized via `ensure_utc_naive()` | Trade execution time |
| `ingestion_time` | `datetime` | Normalized via `ensure_utc_naive()` | Connector receipt UTC |

### 1.2 `CanonicalKlineEvent` (v1.1.0 Fixes)

| Field | Type | Constraints / Validation | Notes |
|---|---|---|---|
| `schema_version` | `str` | Default `"1.1.0"` | Semver string |
| `event_id` | `str` | `kline:{SYMBOL}:{tf}:{open_ms}:{closed \| tick:{event_ms}}` | Closed vs forming key separation |
| `event_type` | `Literal["kline"]` | `"kline"` | Discriminator |
| `source` | `str` | `"binance_ws"` or `"binance_rest"` | Provenance |
| `symbol` | `str` | Alphanumeric uppercase (`3..20` chars) | Normalized `.upper()` |
| `timeframe` | `str` | **v1.1.0:** Must be in `VALID_STREAM_TIMEFRAMES` | Fixes `normalizer.py:58` missing allowlist |
| `open_time` | `datetime` | `ensure_utc_naive()`, **v1.1.0:** `open_time <= close_time` | Fixes `events.py:66-77` missing temporal check |
| `close_time` | `datetime` | `ensure_utc_naive()` | Bar close timestamp |
| `open, high, low, close` | `float` | `gt=0.0`, `math.isfinite`, `high >= max(open, close, low)`, `low <= min(open, close)` | OHLC geometry gate |
| `volume` | `float` | `ge=0.0`, `math.isfinite` | Base volume |
| `quote_asset_volume`, `taker_buy_*` | `Optional[float]` | `ge=0.0`, `math.isfinite` when set | Optional Binance metrics |
| `number_of_trades` | `Optional[int]` | `ge=0` | Trade count |
| `is_closed` | `bool` | Required | Closed bar promotion signal |
| `event_time`, `ingestion_time` | `datetime` | `ensure_utc_naive()` | Event & receipt UTC |

---

## 2. `IFC-DP-002` — NATS Subject Taxonomy

| Subject Pattern | Plane / Transport | Publisher | Subscriber(s) | Purpose |
|---|---|---|---|---|
| `market.aggtrade.<SYMBOL>` | JetStream (`MARKET_EVENTS`) | `BoundedEventProducer` (`COMP-DP-01`) | `MedallionStreamConsumer` (`COMP-DP-03`) | Durable canonical aggregate trades |
| `market.kline.<TF>.<SYMBOL>` | JetStream (`MARKET_EVENTS`) | `BoundedEventProducer` (`COMP-DP-01`) | `MedallionStreamConsumer` (`COMP-DP-03`) | Durable canonical candlestick bars |
| `market.dlq.<STREAM>.<SYMBOL>` | JetStream (`MARKET_DLQ`) | Ingestor quarantine / Consumer DLQ | DLQ Inspector / Replay | Quarantined malformed or max-delivery failures |
| `serving.market.<SYMBOL>` | NATS Core (ephemeral) | `StreamProcessor` (post-coalesce / post-commit) | API `ServingGatewayBridge` -> `WSBroadcastHub` | Low-latency (`~0.24 ms` measured) tick & analytics fan-out |
| `serving.events.closed_bar` | NATS Core (ephemeral) | `StreamProcessor` (post-SQL commit) | API `ServingGatewayBridge`, `WorkflowWorker` | Cache invalidation & post-commit closed-candle inference trigger |
| `serving.system.status` | NATS Core (ephemeral) | `StreamWorker` (every `2s`) | API `ServingGatewayBridge` -> `WSBroadcastHub` | Live pipeline flow & telemetry broadcast |
| `serving.control.<cmd>` | NATS Core Request-Reply | FastAPI Control Endpoints (`COMP-DP-11`) | `StreamWorker` (`ServingGatewayBridge`) | Commands: `flush`, `simulate_disconnect` (`timeout=5.0s`) |
| `serving.worker.heartbeat.<worker>` | NATS Core + KV (`worker_heartbeats`) | `StreamWorker`, `WorkflowWorker` | API `/health`, `/system/resources`, `/streaming/status` | Worker liveness & per-process RSS/CPU telemetry |
| `workflow.wakeup` | NATS Core (ephemeral nudge) | API `/pipelines/trigger`, `/models/train` | `WorkflowWorker` (`COMP-DP-09`) | Low-latency trigger wake-up (SQL `workflow_runs` stays authoritative) |

---

## 3. `IFC-DP-003` — JetStream Stream & Consumer Configuration

### 3.1 Stream Configurations (`NatsJetStreamBroker._ensure_streams`)

Note: Verified in installed `nats-py 2.16.0` (`nats.js.api.StreamConfig.as_dict`), `max_age` and `duplicate_window` take **seconds** as floats/ints (`_to_nanoseconds` converts internally).

| Stream | Subjects | Retention / Storage / Discard | `max_bytes` Split | `max_age` | `duplicate_window` |
|---|---|---|---|---|---|
| `MARKET_EVENTS` | `market.aggtrade.*`, `market.kline.>` | `LIMITS` / `FILE` / `OLD` | `70%` of `nats_max_file_mb` | `retention_bronze_days * 86400` (`3d`/`7d`/`30d`) | `nats_dedup_window_sec` (`120s`) |
| `MARKET_DLQ` | `market.dlq.>` | `LIMITS` / `FILE` / `OLD` | `max(4MB, 20% of nats_max_file_mb)` | `retention_silver_days * 86400` (`14d`/`30d`/`90d`) | `0` (disabled) |

- **Storage Allocation & Fallback Ladder Fix**: Reserving `70% + 20% = 90%` leaves `10%` server file headroom (`12.8 MB` free on LITE `128 MB`). On `"insufficient storage"` during `add_stream`, degrade proportionally `[1.0, 0.85, 0.70, 0.50, 0.25]` of target `max_b` (minimum `4 MB`) instead of dropping straight to `32 MB` (`broker.py:233`).

### 3.2 Durable Pull Consumer & Migration Policy

| Parameter | Value | Notes |
|---|---|---|
| `durable_name` | `medallion_<profile>_consumer` | Profile-scoped (`medallion_lite_consumer`, etc.) |
| `ack_policy` | `AckPolicy.EXPLICIT` | Post-commit ACK only (`ADR-DP-002`) |
| `ack_wait` | `streaming.nats_ack_wait_sec` (`30s`) | Exceeds `microbatch_flush_max_age_sec` (`5–10s`) + typical flush (`<1s`) |
| `max_deliver` | `streaming.nats_max_deliver` (`5`) | Bounds poison-pill retry loops before `QUARANTINED_DLQ` |
| `max_ack_pending` | `max(bronze_flush_max_records * 2, consumer_batch_size * 4, 500)` | Prevents broker redelivery starvation during micro-batching |
| **Migration Rule** | Pre-check `js.consumer_info(...)` before `pull_subscribe(..., config=cfg)` | Reuses matching consumer; if immutable fields (`ack_wait`, `max_deliver`) changed intentionally across release, logs warning and applies explicit controlled recreate (`delete_consumer` + `pull_subscribe`) rather than crashing startup |

---

## 4. `IFC-DP-004` — JetStream KeyValue Buckets (`StorageType.MEMORY`)

Empirical probe (`#16`) proved `StorageType.FILE` buckets `>= 8 MB` fail under LITE's `128 MB` cap (`err_code=10047`). Therefore both KV buckets MUST use `StorageType.MEMORY`:

| Bucket Name | `storage` | `history` | `ttl` (seconds) | `max_value_size` | `max_bytes` (LITE / STD / EXT) |
|---|---|---|---|---|---|
| `hot_state` | `StorageType.MEMORY` | `1` | `300.0` | `262144` (256 KB) | `8 MB` / `16 MB` / `32 MB` |
| `worker_heartbeats` | `StorageType.MEMORY` | `1` | `15.0` | `65536` (64 KB) | `1 MB` / `2 MB` / `4 MB` |

---

## 5. `IFC-DP-009` — `HotStateCache` Protocol Contract

```python
from typing import Any, Dict, Optional, Protocol

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

- **Degraded Behavior**: When L2 (`NatsKVHotStateBackend`) is unreachable or times out (`> 500ms`), `get_json` degrades safely to L1 (`TTLCache`) if present (or returns `None`), while `put_json` logs a rate-limited warning without raising into critical ingestion or SQL commit paths.

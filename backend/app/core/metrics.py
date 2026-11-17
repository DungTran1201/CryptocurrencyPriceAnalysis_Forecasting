"""Lightweight Prometheus-compatible metrics and host resource telemetry (IFC-DP-010)."""

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, Optional, Tuple
import psutil
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    CONTENT_TYPE_LATEST,
    generate_latest,
)

REGISTRY = CollectorRegistry(auto_describe=True)

EVENTS_RECEIVED = Counter(
    "platform_events_received_total",
    "Total market events received from external connectors",
    ["stream", "symbol"],
    registry=REGISTRY,
)
EVENTS_PUBLISHED = Counter(
    "platform_events_published_total",
    "Total canonical events published to broker",
    ["stream", "symbol"],
    registry=REGISTRY,
)
EVENTS_CONSUMED = Counter(
    "platform_events_consumed_total",
    "Total events consumed by stream consumers",
    ["consumer", "symbol"],
    registry=REGISTRY,
)
EVENTS_PERSISTED = Counter(
    "platform_events_persisted_total",
    "Total records persisted to Medallion layers",
    ["layer", "symbol"],
    registry=REGISTRY,
)
DLQ_EVENTS = Counter(
    "platform_dlq_events_total",
    "Total events routed to dead-letter storage",
    ["stream", "symbol", "reason"],
    registry=REGISTRY,
)
BACKPRESSURE_EVENTS = Counter(
    "platform_backpressure_events_total",
    "Count of bounded queue backpressure pauses",
    ["stage"],
    registry=REGISTRY,
)
PROCESSING_FAILURES = Counter(
    "platform_processing_failures_total",
    "Total stream or pipeline processing failures",
    ["stage"],
    registry=REGISTRY,
)
STAGE_FAILURES_TOTAL = Counter(
    "platform_stage_failures_total",
    "Total failures categorized by process role and execution stage",
    ["process", "stage"],
    registry=REGISTRY,
)
DQ_FAILURES = Counter(
    "platform_dq_failures_total",
    "Total data quality check failures",
    ["rule_id", "symbol"],
    registry=REGISTRY,
)
DATA_GAPS_DETECTED_TOTAL = Counter(
    "platform_data_gaps_detected_total",
    "Total market time-series gaps detected",
    ["symbol", "timeframe"],
    registry=REGISTRY,
)
WORKFLOW_RUNS_TOTAL = Counter(
    "platform_workflow_runs_total",
    "Total durable workflow runs completed by workflow type and terminal status",
    ["workflow_type", "status"],
    registry=REGISTRY,
)
WORKFLOW_LEASE_RECLAIMED_TOTAL = Counter(
    "platform_workflow_lease_reclaimed_total",
    "Total expired workflow task leases reclaimed by stale-lease reaper",
    registry=REGISTRY,
)
CACHE_HITS_TOTAL = Counter(
    "platform_cache_hits_total",
    "Total hot-state cache lookup hits",
    ["cache"],
    registry=REGISTRY,
)
CACHE_MISSES_TOTAL = Counter(
    "platform_cache_misses_total",
    "Total hot-state cache lookup misses",
    ["cache"],
    registry=REGISTRY,
)
QUEUE_DEPTH = Gauge(
    "platform_queue_depth",
    "Current occupancy of bounded in-memory queues",
    ["queue"],
    registry=REGISTRY,
)
CONSUMER_LAG = Gauge(
    "platform_consumer_lag_msgs",
    "Pending messages lag on NATS JetStream consumers",
    ["stream", "consumer"],
    registry=REGISTRY,
)
DATA_FRESHNESS_SECONDS = Gauge(
    "platform_data_freshness_seconds",
    "Age in seconds since latest closed event/candle",
    ["symbol", "stream"],
    registry=REGISTRY,
)
ACTIVE_DATA_FRESHNESS_SECONDS = Gauge(
    "platform_active_data_freshness_seconds",
    "Actively computed staleness in seconds since latest persisted close_time",
    ["symbol", "timeframe"],
    registry=REGISTRY,
)
PROCESSING_LATENCY = Histogram(
    "platform_processing_latency_seconds",
    "End-to-end processing latency in seconds",
    ["stage"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)
BATCH_WRITE_LATENCY = Histogram(
    "platform_batch_write_latency_seconds",
    "Micro-batch persistence latency in seconds",
    ["layer"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)
WAREHOUSE_QUERY_LATENCY = Histogram(
    "platform_warehouse_query_latency_seconds",
    "DuckDB warehouse analytical query execution latency in seconds",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)
PROCESS_RSS_BYTES = Gauge(
    "platform_process_rss_bytes",
    "Current process resident set size in bytes",
    registry=REGISTRY,
)
PROCESS_CPU_PERCENT = Gauge(
    "platform_process_cpu_percent",
    "Current process CPU utilization percentage",
    registry=REGISTRY,
)
HOST_RAM_AVAILABLE_BYTES = Gauge(
    "platform_host_ram_available_bytes",
    "Host available physical memory in bytes",
    registry=REGISTRY,
)
HOST_RAM_USED_PERCENT = Gauge(
    "platform_host_ram_used_percent",
    "Host physical memory utilization percentage",
    registry=REGISTRY,
)
HOST_DISK_FREE_BYTES = Gauge(
    "platform_host_disk_free_bytes",
    "Free disk bytes on workspace/data filesystem",
    registry=REGISTRY,
)
HOST_DISK_USED_PERCENT = Gauge(
    "platform_host_disk_used_percent",
    "Disk utilization percentage on workspace/data filesystem",
    registry=REGISTRY,
)
STORAGE_USAGE_BYTES = Gauge(
    "platform_storage_bytes",
    "Disk usage bytes by storage layer",
    ["layer"],
    registry=REGISTRY,
)

_PROCESS = psutil.Process(os.getpid())
# Prime cpu_percent measurement
_PROCESS.cpu_percent(interval=None)

_STORAGE_CACHE_LOCK = threading.Lock()
_STORAGE_CACHE: Dict[str, Tuple[float, Dict[str, int]]] = {}
_FRESHNESS_LOCK = threading.Lock()
_LAST_KNOWN_CLOSE_TIMES: Dict[Tuple[str, str], datetime] = {}


def dir_size_bytes(path: Path) -> int:
    """Compute directory size in bytes safely without loading files."""
    if not path.exists():
        return 0
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    return total


def _file_size_bytes(path: Path) -> int:
    try:
        return path.stat().st_size if path.exists() and path.is_file() else 0
    except OSError:
        return 0


def _scan_storage_layers(base: Path) -> Dict[str, int]:
    """Scan all Medallion, operational DB, WAL, warehouse, and runtime dirs."""
    return {
        "bronze": dir_size_bytes(base / "bronze"),
        "silver": dir_size_bytes(base / "silver"),
        "gold": dir_size_bytes(base / "gold"),
        "nats": dir_size_bytes(base / "nats"),
        "dlq": dir_size_bytes(base / "dlq"),
        "models": dir_size_bytes(base / "models"),
        "checkpoints": dir_size_bytes(base / "checkpoints"),
        "warehouse": dir_size_bytes(base / "warehouse"),
        "metadata_db": _file_size_bytes(base / "crypto_market.db"),
        "metadata_wal": _file_size_bytes(base / "crypto_market.db-wal"),
    }


def _get_cached_storage_layers(base: Path, ttl_sec: float = 5.0, force: bool = False) -> Dict[str, int]:
    cache_key = str(base.resolve())
    now = time.monotonic()
    with _STORAGE_CACHE_LOCK:
        cached = _STORAGE_CACHE.get(cache_key)
        if not force and cached is not None and (now - cached[0]) < ttl_sec:
            return dict(cached[1])
    scanned = _scan_storage_layers(base)
    with _STORAGE_CACHE_LOCK:
        _STORAGE_CACHE[cache_key] = (time.monotonic(), scanned)
    return dict(scanned)


def _build_resource_snapshot(
    base: Path,
    memory_budget_mb: int,
    layer_bytes: Dict[str, int],
) -> Dict[str, Any]:
    mem_info = _PROCESS.memory_info()
    rss_mb = mem_info.rss / (1024 * 1024)
    cpu_pct = _PROCESS.cpu_percent(interval=None)
    vm = psutil.virtual_memory()
    disk_target = base.resolve() if base.exists() else Path(".").resolve()
    disk_usage = psutil.disk_usage(str(disk_target))

    PROCESS_RSS_BYTES.set(mem_info.rss)
    PROCESS_CPU_PERCENT.set(cpu_pct)
    HOST_RAM_AVAILABLE_BYTES.set(vm.available)
    HOST_RAM_USED_PERCENT.set(vm.percent)
    HOST_DISK_FREE_BYTES.set(disk_usage.free)
    HOST_DISK_USED_PERCENT.set(disk_usage.percent)

    for layer_name, b_val in layer_bytes.items():
        STORAGE_USAGE_BYTES.labels(layer=layer_name).set(b_val)

    refresh_active_freshness()

    return {
        "process_pid": os.getpid(),
        "process_rss_mb": round(rss_mb, 2),
        "memory_budget_mb": memory_budget_mb,
        "budget_utilization_pct": round((rss_mb / memory_budget_mb) * 100.0, 1) if memory_budget_mb > 0 else 0.0,
        "process_cpu_percent": round(cpu_pct, 2),
        "host_ram_total_mb": round(vm.total / (1024 * 1024), 1),
        "host_ram_available_mb": round(vm.available / (1024 * 1024), 1),
        "host_ram_used_pct": round(vm.percent, 1),
        "disk_free_gb": round(disk_usage.free / (1024 ** 3), 2),
        "disk_used_pct": round(disk_usage.percent, 1),
        "storage_mb": {
            k: round(v / (1024 * 1024), 3)
            for k, v in layer_bytes.items()
        },
    }


def collect_resource_snapshot(
    data_dir: str,
    memory_budget_mb: int,
    ttl_sec: float = 5.0,
    force: bool = False,
) -> Dict[str, Any]:
    """Measure live process RSS, CPU, host memory, and cached per-layer disk usage."""
    base = Path(data_dir)
    layer_bytes = _get_cached_storage_layers(base, ttl_sec=ttl_sec, force=force)
    return _build_resource_snapshot(base, memory_budget_mb, layer_bytes)


async def collect_resource_snapshot_async(
    data_dir: str,
    memory_budget_mb: int,
    ttl_sec: float = 5.0,
    force: bool = False,
) -> Dict[str, Any]:
    """Non-blocking async resource measurement offloading rglob directory scans off the event loop."""
    base = Path(data_dir)
    layer_bytes = await asyncio.to_thread(_get_cached_storage_layers, base, ttl_sec, force)
    return _build_resource_snapshot(base, memory_budget_mb, layer_bytes)


def record_latest_close_time(symbol: str, timeframe: str, close_time: datetime) -> None:
    """Update tracked latest close timestamp for active staleness calculation."""
    naive_ct = close_time.astimezone(timezone.utc).replace(tzinfo=None) if close_time.tzinfo else close_time
    key = (symbol.upper(), timeframe.lower())
    with _FRESHNESS_LOCK:
        prev = _LAST_KNOWN_CLOSE_TIMES.get(key)
        if prev is None or naive_ct > prev:
            _LAST_KNOWN_CLOSE_TIMES[key] = naive_ct


def refresh_active_freshness(now_utc: Optional[datetime] = None) -> Dict[Tuple[str, str], float]:
    """Recompute active_data_freshness_seconds from tracked close timestamps so stalls never freeze."""
    now = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    ages: Dict[Tuple[str, str], float] = {}
    with _FRESHNESS_LOCK:
        items = list(_LAST_KNOWN_CLOSE_TIMES.items())
    for (sym, tf), ct in items:
        age_sec = max(0.0, (now - ct).total_seconds())
        ACTIVE_DATA_FRESHNESS_SECONDS.labels(symbol=sym, timeframe=tf).set(age_sec)
        ages[(sym, tf)] = age_sec
    return ages


async def update_active_freshness_from_db(db: Any, now_utc: Optional[datetime] = None) -> Dict[Tuple[str, str], float]:
    """Query latest Kline.close_time (or SyncCheckpoint) to actively update freshness gauges."""
    from sqlalchemy import func, select
    from backend.app.models.market import Kline, SyncCheckpoint

    stmt = select(Kline.symbol, Kline.timeframe, func.max(Kline.close_time)).group_by(Kline.symbol, Kline.timeframe)
    rows = (await db.execute(stmt)).all()
    for sym, tf, max_ct in rows:
        if max_ct is not None:
            record_latest_close_time(sym, tf, max_ct)

    if not rows:
        cp_rows = (await db.execute(select(SyncCheckpoint.symbol, SyncCheckpoint.timeframe, SyncCheckpoint.last_close_time))).all()
        for sym, tf, ct in cp_rows:
            if ct is not None:
                record_latest_close_time(sym, tf, ct)

    return refresh_active_freshness(now_utc=now_utc)


def clear_observability_caches() -> None:
    """Reset memoized storage scan cache and tracked close times (for deterministic tests)."""
    with _STORAGE_CACHE_LOCK:
        _STORAGE_CACHE.clear()
    with _FRESHNESS_LOCK:
        _LAST_KNOWN_CLOSE_TIMES.clear()


def render_prometheus_metrics() -> tuple[bytes, str]:
    """Return latest Prometheus text payload and content type."""
    refresh_active_freshness()
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


"""Lightweight Prometheus-compatible metrics and host resource telemetry."""

from pathlib import Path
from typing import Dict, Any
import os
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
DQ_FAILURES = Counter(
    "platform_dq_failures_total",
    "Total data quality check failures",
    ["rule_id", "symbol"],
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
STORAGE_USAGE_BYTES = Gauge(
    "platform_storage_bytes",
    "Disk usage bytes by storage layer",
    ["layer"],
    registry=REGISTRY,
)

_PROCESS = psutil.Process(os.getpid())
# Prime cpu_percent measurement
_PROCESS.cpu_percent(interval=None)


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


def collect_resource_snapshot(data_dir: str, memory_budget_mb: int) -> Dict[str, Any]:
    """Measure live process RSS, CPU, host memory, and per-layer disk usage."""
    mem_info = _PROCESS.memory_info()
    rss_mb = mem_info.rss / (1024 * 1024)
    cpu_pct = _PROCESS.cpu_percent(interval=None)
    vm = psutil.virtual_memory()

    base = Path(data_dir)
    bronze_bytes = dir_size_bytes(base / "bronze")
    silver_bytes = dir_size_bytes(base / "silver")
    gold_bytes = dir_size_bytes(base / "gold")
    nats_bytes = dir_size_bytes(base / "nats")
    db_file = base / "crypto_market.db"
    db_bytes = db_file.stat().st_size if db_file.exists() else 0

    PROCESS_RSS_BYTES.set(mem_info.rss)
    PROCESS_CPU_PERCENT.set(cpu_pct)
    STORAGE_USAGE_BYTES.labels(layer="bronze").set(bronze_bytes)
    STORAGE_USAGE_BYTES.labels(layer="silver").set(silver_bytes)
    STORAGE_USAGE_BYTES.labels(layer="gold").set(gold_bytes)
    STORAGE_USAGE_BYTES.labels(layer="nats").set(nats_bytes)
    STORAGE_USAGE_BYTES.labels(layer="metadata_db").set(db_bytes)

    disk_usage = psutil.disk_usage(str(base.resolve()) if base.exists() else str(Path(".").resolve()))

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
        "storage_mb": {
            "bronze": round(bronze_bytes / (1024 * 1024), 3),
            "silver": round(silver_bytes / (1024 * 1024), 3),
            "gold": round(gold_bytes / (1024 * 1024), 3),
            "nats": round(nats_bytes / (1024 * 1024), 3),
            "metadata_db": round(db_bytes / (1024 * 1024), 3),
        },
    }


def render_prometheus_metrics() -> tuple[bytes, str]:
    """Return latest Prometheus text payload and content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


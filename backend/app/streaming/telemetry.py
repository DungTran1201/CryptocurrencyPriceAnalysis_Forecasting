"""Bounded per-node and end-to-end latency telemetry for the real-time streaming pipeline."""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Deque, Dict, List, Optional


NODE_DEFINITIONS: List[Dict[str, str]] = [
    {
        "node_id": "ws_ingest",
        "step": "1",
        "name": "Binance WS Ingest",
        "layer": "INGEST",
        "execution_mode": "inline",
        "description": "WebSocket frame receipt & JSON payload decode",
    },
    {
        "node_id": "normalize",
        "step": "2",
        "name": "Normalizer & Validator",
        "layer": "NORMALIZE",
        "execution_mode": "inline",
        "description": "Canonical schema enforcement & NATS subject routing",
    },
    {
        "node_id": "bounded_queue",
        "step": "3",
        "name": "Bounded Queue",
        "layer": "BUFFER",
        "execution_mode": "inline",
        "description": "Async flow-control queue dwell time before broker publish",
    },
    {
        "node_id": "nats_broker",
        "step": "4",
        "name": "NATS JetStream",
        "layer": "BROKER",
        "execution_mode": "inline",
        "description": "Durable JetStream publish & server acknowledgment RTT",
    },
    {
        "node_id": "consumer_handle",
        "step": "5",
        "name": "Durable Consumer",
        "layer": "CONSUME",
        "execution_mode": "inline",
        "description": "Pull fetch decode, canonical check & LRU deduplication",
    },
    {
        "node_id": "incremental_analytics",
        "step": "6",
        "name": "Incremental Analytics",
        "layer": "INTELLIGENCE",
        "execution_mode": "inline",
        "description": "O(1) online VWAP, EMA, RSI, ATR, VaR/CVaR & MDD update",
    },
    {
        "node_id": "ws_gateway",
        "step": "7",
        "name": "WS Coalesced Hub",
        "layer": "SERVING",
        "execution_mode": "inline",
        "description": "Coalesced JSON serialization & bounded UI WebSocket fan-out",
    },
    {
        "node_id": "medallion_flush",
        "step": "8",
        "name": "Bronze & Silver Flush",
        "layer": "STORAGE",
        "execution_mode": "async_batch",
        "description": "Periodic micro-batch Bronze zstd JSONL, Silver Parquet & SQL WAL commit",
    },
]


def _round_ms(val: Optional[float]) -> Optional[float]:
    if val is None or not math.isfinite(val):
        return None
    return round(max(0.0, val), 3)


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * pct
    lo = math.floor(idx)
    hi = min(len(sorted_vals) - 1, math.ceil(idx))
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


@dataclass
class NodeTimingWindow:
    """Fixed-size O(1)-memory rolling sample window for one pipeline stage."""

    window_size: int = 64
    samples_ms: Deque[float] = field(init=False)
    processed_count: int = 0
    error_count: int = 0
    last_ms: Optional[float] = None
    max_ms: Optional[float] = None
    last_active_at: Optional[str] = None

    def __post_init__(self) -> None:
        self.samples_ms = deque(maxlen=self.window_size)

    def record(self, duration_ms: float, increment_count: int = 1) -> None:
        ms = max(0.0, float(duration_ms))
        self.samples_ms.append(ms)
        self.last_ms = ms
        self.processed_count += increment_count
        self.max_ms = ms if self.max_ms is None else max(self.max_ms, ms)
        self.last_active_at = datetime.now(timezone.utc).isoformat()

    def record_error(self) -> None:
        self.error_count += 1
        self.last_active_at = datetime.now(timezone.utc).isoformat()

    def summary(self) -> Dict[str, Any]:
        n = len(self.samples_ms)
        if n == 0:
            return {
                "processed_count": self.processed_count,
                "error_count": self.error_count,
                "sample_count": 0,
                "last_ms": None,
                "avg_ms": None,
                "p95_ms": None,
                "max_ms": None,
                "last_active_at": self.last_active_at,
            }
        ordered = sorted(self.samples_ms)
        avg_val = sum(ordered) / n
        p95_val = _percentile(ordered, 0.95)
        return {
            "processed_count": self.processed_count,
            "error_count": self.error_count,
            "sample_count": n,
            "last_ms": _round_ms(self.last_ms),
            "avg_ms": _round_ms(avg_val),
            "p95_ms": _round_ms(p95_val),
            "max_ms": _round_ms(self.max_ms),
            "last_active_at": self.last_active_at,
        }


class PipelineTelemetryTracker:
    """Aggregates per-node and total end-to-end processing times across all stages."""

    def __init__(self, window_size: int = 64):
        self._nodes: Dict[str, NodeTimingWindow] = {
            defn["node_id"]: NodeTimingWindow(window_size=window_size)
            for defn in NODE_DEFINITIONS
        }
        self._e2e_wall: NodeTimingWindow = NodeTimingWindow(window_size=window_size)

    def record_stage(self, node_id: str, duration_ms: float, count: int = 1) -> None:
        win = self._nodes.get(node_id)
        if win is not None:
            win.record(duration_ms, increment_count=count)

    def record_stage_error(self, node_id: str) -> None:
        win = self._nodes.get(node_id)
        if win is not None:
            win.record_error()

    def record_e2e_wall(self, duration_ms: float) -> None:
        # Ignore negative clock drift or historical JetStream replays > 60s old
        if 0.0 <= duration_ms <= 60_000.0:
            self._e2e_wall.record(duration_ms, increment_count=1)

    def build_snapshot(
        self,
        *,
        ws_connected: bool,
        broker_connected: bool,
        backpressure_active: bool,
        streaming_enabled: bool,
        node_meta: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Build complete pipeline DAG snapshot with per-node metrics and summed totals."""
        meta_map = node_meta or {}
        nodes_out: List[Dict[str, Any]] = []

        inline_avg_sum = 0.0
        inline_last_sum = 0.0
        inline_has_samples = False

        flush_avg_ms: Optional[float] = None
        flush_last_ms: Optional[float] = None

        bottleneck_id: Optional[str] = None
        bottleneck_name: Optional[str] = None
        bottleneck_avg: Optional[float] = None

        for defn in NODE_DEFINITIONS:
            nid = defn["node_id"]
            stats = self._nodes[nid].summary()
            avg_ms = stats["avg_ms"]
            last_ms = stats["last_ms"]

            if defn["execution_mode"] == "inline" and avg_ms is not None:
                inline_has_samples = True
                inline_avg_sum += avg_ms
                if last_ms is not None:
                    inline_last_sum += last_ms
                if bottleneck_avg is None or avg_ms > bottleneck_avg:
                    bottleneck_avg = avg_ms
                    bottleneck_id = nid
                    bottleneck_name = defn["name"]
            elif nid == "medallion_flush":
                flush_avg_ms = avg_ms
                flush_last_ms = last_ms

            status = self._resolve_node_status(
                node_id=nid,
                sample_count=stats["sample_count"],
                error_count=stats["error_count"],
                ws_connected=ws_connected,
                broker_connected=broker_connected,
                backpressure_active=backpressure_active,
                streaming_enabled=streaming_enabled,
            )

            nodes_out.append({
                **defn,
                "status": status,
                **stats,
                "share_of_inline_pct": None,
                "meta": meta_map.get(nid, {}),
            })

        # Compute exact % contribution of each inline node to total inline time
        for node in nodes_out:
            if node["execution_mode"] == "inline" and node["avg_ms"] is not None and inline_avg_sum > 0:
                node["share_of_inline_pct"] = round((node["avg_ms"] / inline_avg_sum) * 100.0, 1)

        e2e_summary = self._e2e_wall.summary()
        total_inline_avg = _round_ms(inline_avg_sum) if inline_has_samples else None
        total_inline_last = _round_ms(inline_last_sum) if inline_has_samples else None

        total_with_flush_avg = (
            _round_ms((total_inline_avg or 0.0) + flush_avg_ms)
            if (total_inline_avg is not None and flush_avg_ms is not None)
            else total_inline_avg
        )
        total_with_flush_last = (
            _round_ms((total_inline_last or 0.0) + flush_last_ms)
            if (total_inline_last is not None and flush_last_ms is not None)
            else total_inline_last
        )

        return {
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "nodes": nodes_out,
            "totals": {
                "inline_nodes_count": sum(1 for n in nodes_out if n["execution_mode"] == "inline"),
                "active_inline_nodes": sum(
                    1 for n in nodes_out if n["execution_mode"] == "inline" and n["sample_count"] > 0
                ),
                "total_inline_last_ms": total_inline_last,
                "total_inline_avg_ms": total_inline_avg,
                "medallion_flush_last_ms": flush_last_ms,
                "medallion_flush_avg_ms": flush_avg_ms,
                "total_with_flush_last_ms": total_with_flush_last,
                "total_with_flush_avg_ms": total_with_flush_avg,
                "e2e_wall_last_ms": e2e_summary["last_ms"],
                "e2e_wall_avg_ms": e2e_summary["avg_ms"],
                "e2e_wall_p95_ms": e2e_summary["p95_ms"],
                "bottleneck_node_id": bottleneck_id,
                "bottleneck_node_name": bottleneck_name,
                "bottleneck_avg_ms": bottleneck_avg,
            },
        }

    @staticmethod
    def _resolve_node_status(
        *,
        node_id: str,
        sample_count: int,
        error_count: int,
        ws_connected: bool,
        broker_connected: bool,
        backpressure_active: bool,
        streaming_enabled: bool,
    ) -> str:
        if not streaming_enabled:
            return "IDLE"
        if node_id == "bounded_queue" and backpressure_active:
            return "BACKPRESSURE"
        if node_id == "ws_ingest" and not ws_connected:
            return "DEGRADED" if error_count > 0 else "IDLE"
        if node_id == "nats_broker" and not broker_connected:
            return "DEGRADED"
        if sample_count > 0:
            return "ACTIVE"
        return "IDLE"


"""Real resource & throughput benchmark script for LITE and STANDARD profiles."""

import asyncio
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import time
import numpy as np
import psutil

from backend.app.core.config import PlatformProfile, settings
from backend.app.storage.local import LocalStorageBackend
from backend.app.storage.medallion import MedallionStorageManager
from backend.app.streaming.broker import NatsJetStreamBroker
from ml.incremental_analytics import IncrementalSymbolState, compute_batch_reference_metrics


def _rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


async def benchmark_profile(profile: PlatformProfile) -> dict:
    settings.apply_profile_defaults(profile)
    proc = psutil.Process(os.getpid())
    proc.cpu_percent(interval=None)
    rss_start = _rss_mb()

    # 1. Generate synthetic realistic workload (1000 aggTrade + 300 kline events for LITE)
    n_trades = 1000 if profile == PlatformProfile.LITE else 2500
    n_bars = 300 if profile == PlatformProfile.LITE else 500

    # Benchmark Incremental Stream Processing throughput
    state = IncrementalSymbolState("BTCUSDT", "1m", max_bars=settings.resources.online_window_max_bars)
    base_dt = datetime(2026, 3, 1, 0, 0, 0)
    rng = np.random.default_rng(42)
    closes = 65000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.002, n_bars)))

    t_inc0 = time.perf_counter()
    for i in range(n_trades):
        state.update_trade(float(closes[i % n_bars]), 0.12, base_dt + timedelta(seconds=i))
    for i in range(n_bars):
        c = float(closes[i])
        state.update_closed_bar(base_dt + timedelta(minutes=i), c * 0.999, c * 1.002, c * 0.998, c, 25.0 + i * 0.1)
    inc_elapsed = time.perf_counter() - t_inc0
    total_events = n_trades + n_bars
    events_per_sec = total_events / inc_elapsed if inc_elapsed > 0 else 0.0

    # 2. Benchmark Medallion Bronze zstd + Silver Parquet + Gold DuckDB write/query latency
    with tempfile.TemporaryDirectory() as tmp:
        med = MedallionStorageManager(LocalStorageBackend(Path(tmp)))
        raw_trades = [
            {
                "schema_version": "1.0.0",
                "event_id": f"aggTrade:BTCUSDT:{i}",
                "event_type": "aggTrade",
                "symbol": "BTCUSDT",
                "agg_trade_id": i,
                "price": float(closes[i % n_bars]),
                "quantity": 0.1,
                "quote_quantity": float(closes[i % n_bars]) * 0.1,
                "is_buyer_maker": False,
                "trade_time": (base_dt + timedelta(seconds=i)).isoformat(),
                "event_time": (base_dt + timedelta(seconds=i)).isoformat(),
                "ingestion_time": (base_dt + timedelta(seconds=i)).isoformat(),
            }
            for i in range(n_trades)
        ]
        t_b0 = time.perf_counter()
        b_res = med.write_bronze_batch("aggTrade", "BTCUSDT", raw_trades)
        bronze_ms = (time.perf_counter() - t_b0) * 1000.0

        kline_rows = [
            {
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "open_time": base_dt + timedelta(minutes=i),
                "close_time": base_dt + timedelta(minutes=i + 1) - timedelta(seconds=1),
                "open": float(closes[i]) * 0.999,
                "high": float(closes[i]) * 1.002,
                "low": float(closes[i]) * 0.998,
                "close": float(closes[i]),
                "volume": 30.0 + i * 0.1,
                "is_closed": True,
            }
            for i in range(n_bars)
        ]
        t_s0 = time.perf_counter()
        med.write_silver_klines("BTCUSDT", "1m", kline_rows)
        silver_ms = (time.perf_counter() - t_s0) * 1000.0

        t_d0 = time.perf_counter()
        silver_df = med.read_silver_klines_df("BTCUSDT", "1m", limit=n_bars)
        duck_read_ms = (time.perf_counter() - t_d0) * 1000.0

        t_g0 = time.perf_counter()
        med.materialize_gold_marts("BTCUSDT", "1m", silver_df)
        gold_ms = (time.perf_counter() - t_g0) * 1000.0

        t_a0 = time.perf_counter()
        compute_batch_reference_metrics(silver_df, timeframe="1m")
        batch_analytics_ms = (time.perf_counter() - t_a0) * 1000.0

    # 3. Live NATS JetStream publish + Memory KV benchmark (isolated temp stream/bucket)
    nats_pub_ms = None
    nats_kv_put_ms = None
    try:
        from nats.js.api import KeyValueConfig, StorageType

        broker = NatsJetStreamBroker(
            "nats://127.0.0.1:4222",
            stream_name="MARKET_EVENTS_BENCH",
            dlq_stream_name="MARKET_DLQ_BENCH",
        )
        broker._subject_prefix = "benchmkt"
        await broker.connect()
        t_n0 = time.perf_counter()
        for _ in range(100):
            await broker.publish("benchmkt.aggtrade.BENCH", b'{"bench":1}')
        nats_pub_ms = round(((time.perf_counter() - t_n0) * 1000.0) / 100.0, 3)

        kv = await broker._js.create_key_value(
            KeyValueConfig(
                bucket="bench_hot_kv",
                history=1,
                ttl=10.0,
                max_bytes=2 * 1024 * 1024,
                storage=StorageType.MEMORY,
            )
        )
        t_kv0 = time.perf_counter()
        for i in range(50):
            await kv.put(f"bench.{i}", b'{"price":65000.0}')
        nats_kv_put_ms = round(((time.perf_counter() - t_kv0) * 1000.0) / 50.0, 3)
        await broker._js.delete_key_value("bench_hot_kv")

        for stream_name in ("MARKET_EVENTS_BENCH", "MARKET_DLQ_BENCH"):
            try:
                await broker._js.delete_stream(stream_name)
            except Exception:
                pass
        await broker.close()
    except Exception:
        nats_pub_ms = None
        nats_kv_put_ms = None

    rss_end = _rss_mb()
    cpu_pct = proc.cpu_percent(interval=None)
    comp_ratio = round(b_res["raw_bytes"] / max(1, b_res["bytes"]), 2)

    return {
        "profile": profile.value,
        "budget_total_mb": settings.resources.total_memory_mb,
        "rss_start_mb": round(rss_start, 2),
        "rss_end_mb": round(rss_end, 2),
        "cpu_percent": round(cpu_pct, 2),
        "workload": {"trades": n_trades, "bars": n_bars},
        "incremental_events_per_sec": round(events_per_sec, 1),
        "bronze_zstd_write_ms": round(bronze_ms, 2),
        "bronze_compression_ratio": comp_ratio,
        "silver_parquet_write_ms": round(silver_ms, 2),
        "duckdb_silver_query_ms": round(duck_read_ms, 2),
        "gold_materialize_ms": round(gold_ms, 2),
        "batch_analytics_ms": round(batch_analytics_ms, 2),
        "nats_avg_publish_ms": nats_pub_ms,
        "nats_kv_mem_avg_put_ms": nats_kv_put_ms,
    }


async def main():
    results = []
    for p in (PlatformProfile.LITE, PlatformProfile.STANDARD):
        results.append(await benchmark_profile(p))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

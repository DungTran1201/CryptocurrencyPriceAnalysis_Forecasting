"""Streaming, Broker (InMemory + Live NATS JetStream), Backpressure, DLQ, & WS Hub tests."""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from backend.app.core.database import Base
from backend.app.schemas.events import CanonicalKlineEvent
from backend.app.storage.local import LocalStorageBackend
from backend.app.storage.medallion import MedallionStorageManager
from backend.app.streaming.broker import InMemoryBroker, NatsJetStreamBroker
from backend.app.streaming.consumers import MedallionStreamConsumer
from backend.app.streaming.normalizer import (
    NormalizationError,
    normalize_binance_ws_payload,
    subject_for_event,
)
from backend.app.streaming.producer import BoundedEventProducer
from backend.app.streaming.runtime import StreamPlatformRuntime
from backend.app.streaming.telemetry import PipelineTelemetryTracker
from backend.app.streaming.ws_hub import WSBroadcastHub
from backend.app.models.governance import DeadLetterEvent, StreamCheckpoint
from backend.app.models.market import Kline, Symbol
from ml.incremental_analytics import IncrementalAnalyticsEngine


def _nats_listening(host: str = "127.0.0.1", port: int = 4222) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def test_canonical_ws_normalization_and_validation():
    """Verify aggTrade & kline WS payload normalization and malformed payload rejection."""
    agg_raw = {
        "stream": "btcusdt@aggTrade",
        "data": {"e": "aggTrade", "E": 1719792000100, "s": "BTCUSDT", "a": 991, "p": "65000.5", "q": "0.25", "T": 1719792000050, "m": False},
    }
    evt = normalize_binance_ws_payload(agg_raw)
    assert evt.symbol == "BTCUSDT"
    assert evt.agg_trade_id == 991
    assert evt.price == 65000.5
    assert subject_for_event(evt) == "market.aggtrade.BTCUSDT"

    kline_raw = {
        "stream": "btcusdt@kline_1m",
        "data": {
            "e": "kline",
            "E": 1719792060000,
            "s": "BTCUSDT",
            "k": {
                "t": 1719792000000, "T": 1719792059999, "s": "BTCUSDT", "i": "1m",
                "o": "65000", "c": "65100", "h": "65200", "l": "64950", "v": "12.5", "x": True,
                "q": "813750", "n": 42,
            },
        },
    }
    kevt = normalize_binance_ws_payload(kline_raw)
    assert isinstance(kevt, CanonicalKlineEvent)
    assert kevt.is_closed is True
    assert subject_for_event(kevt) == "market.kline.1m.BTCUSDT"

    # Malformed OHLC geometry (high < low)
    bad_kline = {
        "e": "kline", "E": 1719792060000, "s": "BTCUSDT",
        "k": {"t": 1719792000000, "T": 1719792059999, "i": "1m", "o": "100", "c": "100", "h": "90", "l": "110", "v": "1", "x": True},
    }
    with pytest.raises(NormalizationError):
        normalize_binance_ws_payload(bad_kline)


@pytest.mark.asyncio
async def test_bounded_producer_backpressure_and_broker_replay():
    """Verify bounded queue applies backpressure (no silent drops) and broker replays messages."""
    broker = InMemoryBroker(max_messages=500)
    await broker.connect()
    producer = BoundedEventProducer(broker=broker, maxsize=4, high_watermark_ratio=0.5)

    # Enqueue 4 items BEFORE starting drain loop -> hits high watermark without dropping any
    for i in range(4):
        await producer.enqueue("market.aggtrade.BTCUSDT", f'{{"seq":{i}}}'.encode(), f"id-{i}", "BTCUSDT", "aggTrade")

    assert producer.backpressure_active is True
    assert producer.backpressure_count >= 1
    assert producer.stats()["queue_depth"] == 4

    await producer.start()
    await asyncio.sleep(0.15)
    await producer.stop()

    assert producer.published_count == 4
    replayed = await broker.replay_messages("market.>", start_seq=2, max_msgs=10)
    assert len(replayed) == 3
    await broker.close()


@pytest.mark.asyncio
async def test_consumer_medallion_microbatch_dedup_and_dlq(tmp_path: Path):
    """Verify durable consumer processes micro-batches to Bronze/Silver/SQL, deduplicates, and quarantines DLQ."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        db.add(Symbol(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT", is_active=True))
        await db.commit()

    broker = InMemoryBroker()
    await broker.connect()

    storage = LocalStorageBackend(tmp_path / "lake")
    medallion = MedallionStorageManager(storage)
    analytics_eng = IncrementalAnalyticsEngine(checkpoint_dir=tmp_path / "ckpt", max_bars=100)

    consumer = MedallionStreamConsumer(
        broker=broker,
        durable_name="test_medallion",
        medallion=medallion,
        analytics_engine=analytics_eng,
        session_factory=session_factory,
    )

    kline_raw = {
        "e": "kline",
        "E": 1719792060000,
        "s": "BTCUSDT",
        "k": {
            "t": 1719792000000, "T": 1719792059999, "s": "BTCUSDT", "i": "1m",
            "o": "65000", "c": "65150", "h": "65200", "l": "64950", "v": "15.0", "x": True,
        },
    }
    evt = normalize_binance_ws_payload(kline_raw)
    payload = evt.model_dump_json().encode("utf-8")

    # Publish valid message + duplicate payload without msg_id (tests consumer-side dedup) + malformed message
    await broker.publish("market.kline.1m.BTCUSDT", payload)
    await broker.publish("market.kline.1m.BTCUSDT", payload)
    await broker.publish("market.aggtrade.BTCUSDT", b"{not-valid-json")

    await consumer.process_single_batch(batch_size=10, timeout=0.2)
    await consumer.flush_microbatch()

    assert consumer.consumed_count == 1
    assert consumer.dedup_skipped_count == 1
    assert consumer.dlq_count == 1

    # Verify Bronze zstd & Silver Parquet created
    assert len(storage.list_keys("bronze", ".jsonl.zst")) == 1
    assert len(storage.list_keys("silver", ".parquet")) == 1

    # Verify SQL Kline, StreamCheckpoint, & DeadLetterEvent persisted
    async with session_factory() as db:
        klines = (await db.execute(select(Kline))).scalars().all()
        assert len(klines) == 1
        assert klines[0].close == 65150.0

        dlq_rows = (await db.execute(select(DeadLetterEvent))).scalars().all()
        assert len(dlq_rows) == 1
        assert dlq_rows[0].status == "QUARANTINED"

        ckpts = (await db.execute(select(StreamCheckpoint))).scalars().all()
        assert len(ckpts) == 1
        assert ckpts[0].processed_count == 1

    await consumer.stop()
    await broker.close()
    await engine.dispose()


@pytest.mark.system
@pytest.mark.asyncio
async def test_live_nats_jetstream_publish_consume_nak_replay():
    """Live Integration Test against running NATS JetStream on 127.0.0.1:4222."""
    if not _nats_listening():
        pytest.skip("NATS JetStream not running on 127.0.0.1:4222")

    broker = NatsJetStreamBroker(
        nats_url="nats://127.0.0.1:4222",
        stream_name="MARKET_EVENTS_TEST",
        dlq_stream_name="MARKET_DLQ_TEST",
    )
    broker._subject_prefix = "testmkt"
    await broker.connect()
    try:
        assert broker.is_connected()

        unique_id = f"test-msg-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        durable_name = f"test_durable_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        subj = "testmkt.aggtrade.TESTPAIR"
        sub = await broker.pull_subscribe(subject=subj, durable=durable_name, stream="MARKET_EVENTS_TEST")

        payload = json.dumps({"probe": unique_id}).encode("utf-8")
        seq = await broker.publish(subj, payload, msg_id=unique_id)
        assert seq >= 1

        # 1. Pull message and NAK to verify redelivery
        msgs = await sub.fetch(batch=5, timeout=2.0)
        target = [m for m in msgs if json.loads(m.payload).get("probe") == unique_id]
        assert len(target) == 1
        assert target[0].delivery_count == 1
        await target[0].nak(delay=0.1)

        # 2. Fetch redelivered message and ACK
        await asyncio.sleep(0.2)
        msgs2 = await sub.fetch(batch=5, timeout=2.0)
        target2 = [m for m in msgs2 if json.loads(m.payload).get("probe") == unique_id]
        assert len(target2) == 1
        assert target2[0].redelivered is True
        assert target2[0].delivery_count >= 2
        await target2[0].ack()
        await sub.unsubscribe()

        # 3. Replay from exact sequence
        replayed = await broker.replay_messages(subj, start_seq=seq, max_msgs=5)
        assert any(json.loads(r["payload"]).get("probe") == unique_id for r in replayed)

        info = await broker.get_stream_info()
        assert info["connected"] is True
        assert info["messages"] >= 1
    finally:
        for stream_name in ("MARKET_EVENTS_TEST", "MARKET_DLQ_TEST"):
            try:
                await broker._js.delete_stream(stream_name)
            except Exception:
                pass
        await broker.close()


@pytest.mark.asyncio
async def test_ws_hub_coalescing_bounded_buffer():
    """Verify WSBroadcastHub coalesces rapid updates into bounded client queue."""
    hub = WSBroadcastHub(coalesce_interval_ms=50)
    await hub.start()

    class _FakeWS:
        def __init__(self):
            self.accepted = False
            self.closed = False
        async def accept(self):
            self.accepted = True
        async def close(self):
            self.closed = True

    ws = _FakeWS()
    q = await hub.register(ws)  # type: ignore[arg-type]
    for i in range(100):
        hub.publish_symbol_update("BTCUSDT", {"live_price": 60000.0 + i})

    await asyncio.sleep(0.12)
    assert not q.empty()
    assert q.qsize() <= 16
    latest = json.loads(q.get_nowait())
    assert latest["symbols"]["BTCUSDT"]["live_price"] == 60099.0
    await hub.stop()


@pytest.mark.asyncio
async def test_pipeline_telemetry_per_node_and_totals_calculation():
    """Verify per-node latency tracking, empty nullability, inline totals sum, and runtime snapshot."""
    tracker = PipelineTelemetryTracker(window_size=16)

    # Empty state: must return None (never fake zeroes) for unmeasured latencies
    empty_snap = tracker.build_snapshot(
        ws_connected=False,
        broker_connected=False,
        backpressure_active=False,
        streaming_enabled=True,
    )
    assert len(empty_snap["nodes"]) == 8
    assert empty_snap["totals"]["total_inline_avg_ms"] is None
    assert empty_snap["totals"]["medallion_flush_avg_ms"] is None
    assert empty_snap["totals"]["bottleneck_node_id"] is None

    # Record deterministic stage durations
    tracker.record_stage("ws_ingest", 0.4)
    tracker.record_stage("normalize", 0.6)
    tracker.record_stage("bounded_queue", 0.2)
    tracker.record_stage("nats_broker", 2.5)
    tracker.record_stage("consumer_handle", 0.8)
    tracker.record_stage("incremental_analytics", 0.3)
    tracker.record_stage("ws_gateway", 0.2)
    tracker.record_stage("medallion_flush", 12.0)
    tracker.record_e2e_wall(5.4)

    snap = tracker.build_snapshot(
        ws_connected=True,
        broker_connected=True,
        backpressure_active=False,
        streaming_enabled=True,
        node_meta={"nats_broker": {"messages": 1}},
    )
    totals = snap["totals"]
    assert totals["active_inline_nodes"] == 7
    assert totals["total_inline_avg_ms"] == pytest.approx(5.0, rel=1e-3)
    assert totals["medallion_flush_avg_ms"] == pytest.approx(12.0, rel=1e-3)
    assert totals["total_with_flush_avg_ms"] == pytest.approx(17.0, rel=1e-3)
    assert totals["e2e_wall_avg_ms"] == pytest.approx(5.4, rel=1e-3)
    assert totals["bottleneck_node_id"] == "nats_broker"

    inline_shares = [
        n["share_of_inline_pct"]
        for n in snap["nodes"]
        if n["execution_mode"] == "inline" and n["share_of_inline_pct"] is not None
    ]
    assert sum(inline_shares) == pytest.approx(100.0, abs=0.5)

    # Runtime status_snapshot always exposes valid pipeline_flow contract
    rt = StreamPlatformRuntime(broker=InMemoryBroker())
    status = await rt.status_snapshot()
    assert "pipeline_flow" in status
    assert len(status["pipeline_flow"]["nodes"]) == 8
    assert "totals" in status["pipeline_flow"]


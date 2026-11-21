"""Streaming Runtime Coordinator managing Broker, Producer, WS Ingestor, Consumers, & WS Hub."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.app.core.config import settings
from backend.app.core.database import AsyncSessionLocal
from backend.app.core.logging import get_logger
from backend.app.schemas.events import CanonicalKlineEvent
from backend.app.services.forecast_service import ForecastService
from backend.app.services.governance_service import GovernanceService
from backend.app.services.sync_service import BinanceSyncService
from backend.app.storage import get_data_root
from backend.app.storage.medallion import MedallionStorageManager
from backend.app.streaming.binance_ws import BinanceWebSocketIngestor
from backend.app.streaming.broker import MessageBroker, create_broker
from backend.app.streaming.consumers import MedallionStreamConsumer
from backend.app.streaming.producer import BoundedEventProducer
from backend.app.streaming.telemetry import PipelineTelemetryTracker
from backend.app.streaming.ws_hub import WSBroadcastHub
from ml.incremental_analytics import IncrementalAnalyticsEngine

logger = get_logger("StreamRuntime")


class StreamPlatformRuntime:
    """Single-node lifecycle manager for realtime streaming, Medallion consumers, and UI WS hub."""

    def __init__(self, broker: Optional[MessageBroker] = None):
        self.telemetry = PipelineTelemetryTracker()
        self.broker = broker or create_broker()
        self.ws_hub = WSBroadcastHub(telemetry=self.telemetry)
        self.medallion = MedallionStorageManager()
        self.analytics_engine = IncrementalAnalyticsEngine(
            checkpoint_dir=get_data_root() / settings.storage.checkpoint_subdir,
            max_bars=settings.resources.online_window_max_bars,
        )
        self.producer = BoundedEventProducer(self.broker, telemetry=self.telemetry)
        self.ingestor = BinanceWebSocketIngestor(
            producer=self.producer,
            symbols=settings.streaming.symbols,
            streams=settings.streaming.streams,
            on_reconnect_gap_heal=self._gap_heal_all,
            telemetry=self.telemetry,
        )
        self.consumer = MedallionStreamConsumer(
            broker=self.broker,
            durable_name=f"medallion_{settings.profile.value}_consumer",
            medallion=self.medallion,
            analytics_engine=self.analytics_engine,
            ws_hub=self.ws_hub,
            on_closed_kline=self._handle_closed_kline_trigger,
            telemetry=self.telemetry,
        )
        self._forecast_service = ForecastService()
        self._sync_service = BinanceSyncService()
        self._maintenance_task: Optional[asyncio.Task] = None
        self._started = False
        self._last_triggered_inference: Optional[Dict[str, Any]] = None

    async def start(self, start_ingestor: bool = True, start_consumer: bool = True) -> None:
        if self._started:
            return
        self._started = True
        await self.ws_hub.start()

        if settings.app_env == "testing" or not settings.streaming.enabled:
            logger.info("Streaming pipeline disabled for current environment.")
            return

        # Connect broker with non-blocking retry guard so API still boots if NATS is starting
        try:
            await self.broker.connect()
        except Exception as exc:
            logger.warning(f"Initial broker connection pending ({exc}); runtime will retry asynchronously.")

        await self.producer.start()
        if start_consumer:
            try:
                await self.consumer.start()
            except Exception as exc:
                logger.warning(f"Consumer start deferred until broker ready: {exc}")
        if start_ingestor:
            await self.ingestor.start()

        self._maintenance_task = asyncio.create_task(self._maintenance_loop(), name="stream_maintenance")
        logger.info(
            f"StreamPlatformRuntime started [profile={settings.profile.value}, "
            f"symbols={settings.streaming.symbols}, embedded={settings.streaming.embedded_in_api}]"
        )

    async def stop(self) -> None:
        self._started = False
        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
            self._maintenance_task = None
        await self.ingestor.stop()
        await self.producer.stop()
        await self.consumer.stop()
        await self.ws_hub.stop()
        await self.broker.close()
        logger.info("StreamPlatformRuntime stopped cleanly.")

    async def _gap_heal_all(self) -> None:
        """Backfill missing recent candles after a WebSocket reconnection."""
        logger.info("Running post-reconnect REST gap healing...")
        async with AsyncSessionLocal() as db:
            for sym in settings.streaming.symbols:
                try:
                    await self._sync_service.sync_incremental(db, sym, "1m", lookback_days_if_empty=1)
                    await self._sync_service.fill_gaps(db, sym, "1m")
                except Exception as exc:
                    logger.warning(f"Gap heal failed for {sym}: {exc}")

    async def _handle_closed_kline_trigger(self, evt: CanonicalKlineEvent) -> None:
        """Execute controlled ML inference and reconciliation only when a candle closes."""
        if settings.streaming.ml_inference_trigger != "closed_candle":
            return
        try:
            async with AsyncSessionLocal() as db:
                reconciled = await self._forecast_service.reconcile_pending_forecasts(db)
                fc = await self._forecast_service.try_triggered_forecast(
                    db=db,
                    symbol=evt.symbol,
                    timeframe=evt.timeframe,
                    horizon_steps=3,
                )
                if fc is not None:
                    self._last_triggered_inference = {
                        "forecast_id": fc.id,
                        "symbol": fc.symbol,
                        "timeframe": fc.timeframe,
                        "predicted_price": fc.predicted_price,
                        "predicted_direction": fc.predicted_direction,
                        "model_id": fc.model_id,
                        "triggered_at": fc.forecast_timestamp.isoformat(),
                    }
                    self.ws_hub.publish_symbol_update(evt.symbol, {
                        "latest_forecast": self._last_triggered_inference,
                    })
                if reconciled > 0:
                    logger.info(f"Closed-candle trigger reconciled {reconciled} pending forecasts.")
        except Exception as exc:
            logger.warning(f"Closed-candle inference trigger skipped for {evt.symbol}: {exc}")

    async def _maintenance_loop(self) -> None:
        """Periodic lightweight broker/hub status push and retention check."""
        cycle = 0
        while self._started:
            try:
                if not self.broker.is_connected():
                    try:
                        await self.broker.connect()
                        if not self.consumer._running and (
                            settings.streaming.embedded_in_api or not settings.streaming.enabled
                        ):
                            await self.consumer.start()
                    except Exception:
                        pass

                has_ws_clients = self.ws_hub.client_count > 0
                if has_ws_clients or cycle % 5 == 0:
                    stream_info = await self.broker.get_stream_info()
                    pipeline_flow = self.build_pipeline_flow(stream_info)
                    self.ws_hub.publish_system_status({
                        "profile": settings.profile.value,
                        "broker": stream_info,
                        "ingestor": self.ingestor.stats(),
                        "producer": self.producer.stats(),
                        "consumer": self.consumer.stats(),
                        "pipeline_flow": pipeline_flow,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })

                # Every ~10 minutes (600 x 1s), run retention enforcement off event loop
                if cycle > 0 and cycle % 600 == 0:
                    await asyncio.to_thread(GovernanceService.enforce_retention)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Maintenance loop error: {exc}")
            cycle += 1
            await asyncio.sleep(1.0)

    def build_pipeline_flow(self, broker_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Compute current per-node & total real-time pipeline timing telemetry."""
        b_info = broker_info or {}
        p_stats = self.producer.stats()
        i_stats = self.ingestor.stats()
        c_stats = self.consumer.stats()
        return self.telemetry.build_snapshot(
            ws_connected=bool(i_stats.get("connected")),
            broker_connected=bool(b_info.get("connected", self.broker.is_connected())),
            backpressure_active=bool(p_stats.get("backpressure_active")),
            streaming_enabled=settings.streaming.enabled,
            node_meta={
                "ws_ingest": {
                    "connected": i_stats.get("connected"),
                    "symbols": len(i_stats.get("symbols", [])),
                    "reconnects": i_stats.get("reconnect_count", 0),
                },
                "normalize": {
                    "malformed_count": i_stats.get("malformed_count", 0),
                    "streams": i_stats.get("streams", []),
                },
                "bounded_queue": {
                    "queue_depth": p_stats.get("queue_depth", 0),
                    "queue_maxsize": p_stats.get("queue_maxsize", 0),
                    "occupancy_pct": p_stats.get("occupancy_pct", 0.0),
                    "backpressure_events": p_stats.get("backpressure_events", 0),
                },
                "nats_broker": {
                    "stream": b_info.get("stream"),
                    "messages": b_info.get("messages"),
                    "lag": b_info.get("total_consumer_lag"),
                },
                "consumer_handle": {
                    "dedup_skipped": c_stats.get("dedup_skipped_count", 0),
                    "dlq_count": c_stats.get("dlq_count", 0),
                    "last_seq": c_stats.get("last_seq", 0),
                },
                "incremental_analytics": {
                    "symbols_tracked": len(self.analytics_engine.all_snapshots()),
                },
                "ws_gateway": {
                    "ws_clients": self.ws_hub.client_count,
                    "coalesce_ms": settings.resources.ws_coalesce_interval_ms,
                },
                "medallion_flush": {
                    "flushed_batches": c_stats.get("flushed_batches_count", 0),
                    "pending_buffer": c_stats.get("pending_buffer_records", 0),
                    "last_flush_at": c_stats.get("last_flush_at"),
                },
            },
        )

    async def status_snapshot(self) -> Dict[str, Any]:
        """Return comprehensive live streaming, broker, queue, and incremental state telemetry."""
        broker_info = await self.broker.get_stream_info()
        return {
            "profile": settings.profile.value,
            "streaming_enabled": settings.streaming.enabled,
            "embedded_in_api": settings.streaming.embedded_in_api,
            "broker": broker_info,
            "ingestor": self.ingestor.stats(),
            "producer": self.producer.stats(),
            "consumer": self.consumer.stats(),
            "ws_clients": self.ws_hub.client_count,
            "last_triggered_inference": self._last_triggered_inference,
            "incremental_symbols": self.analytics_engine.all_snapshots(),
            "pipeline_flow": self.build_pipeline_flow(broker_info),
        }


stream_runtime = StreamPlatformRuntime()


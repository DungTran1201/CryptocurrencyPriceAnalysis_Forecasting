"""Dedicated Background Synchronization and Reconciliation Worker.

Periodically syncs new Binance candles, runs gap detection/healing,
and reconciles mature forecasts against actual realized prices.
"""

import asyncio
import sys
from datetime import datetime
from backend.app.core.config import settings
from backend.app.core.database import AsyncSessionLocal, init_db
from backend.app.core.logging import get_logger
from backend.app.services.sync_service import BinanceSyncService
from backend.app.services.forecast_service import ForecastService

logger = get_logger("SyncWorker")


async def run_worker_cycle():
    """Execute a single sync and reconciliation cycle."""
    sync_service = BinanceSyncService()
    forecast_service = ForecastService()

    logger.info("Executing background sync cycle...")
    async with AsyncSessionLocal() as db:
        # 1. Sync candles for default symbols
        for symbol in settings.sync.symbols:
            for tf in [settings.sync.default_timeframe, "1d"]:
                try:
                    res = await sync_service.sync_incremental(db, symbol, tf, lookback_days_if_empty=30)
                    logger.info(f"Worker synced {symbol} {tf}: +{res['added_candles']} candles.")
                except Exception as e:
                    logger.error(f"Worker sync failed for {symbol} {tf}: {e}")

        # 2. Reconcile mature forecasts
        try:
            reconciled = await forecast_service.reconcile_pending_forecasts(db)
            if reconciled > 0:
                logger.info(f"Worker reconciled {reconciled} forecasts.")
        except Exception as e:
            logger.error(f"Worker reconciliation failed: {e}")


async def main_loop(poll_interval_seconds: int = 300):
    """Run worker daemon continuously."""
    logger.info(f"Starting Background Worker Daemon (Poll interval: {poll_interval_seconds}s)")
    await init_db()
    while True:
        try:
            await run_worker_cycle()
        except Exception as e:
            logger.error(f"Unexpected error in worker loop: {e}", exc_info=True)
        await asyncio.sleep(poll_interval_seconds)


if __name__ == "__main__":
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    try:
        asyncio.run(main_loop(interval))
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")

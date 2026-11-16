"""Binance Market Data Synchronization Engine.

Features:
- Primary and fallback Binance REST endpoints with exponential backoff & jitter
- Timestamp normalization (milliseconds to UTC datetime)
- Closed-candle handling (distinguish forming vs closed candles)
- Checkpoint-based incremental synchronization + Symbol.last_synced_at updates
- Dual persistence: Bronze raw archival (zstd JSONL) + Silver Parquet + SQL klines
- Deterministic gap detection and automated backfilling
"""

import asyncio
from datetime import datetime, timezone, timedelta
import random
from typing import List, Dict, Any, Optional, Tuple
import httpx
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.logging import get_logger, PerformanceLogger
from backend.app.models.market import Symbol, Kline, SyncCheckpoint
from backend.app.storage.medallion import MedallionStorageManager

logger = get_logger("SyncService")
perf_logger = PerformanceLogger("SyncService")

TIMEFRAME_DELTAS = {
    "1m": timedelta(minutes=1),
    "3m": timedelta(minutes=3),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "4h": timedelta(hours=4),
    "6h": timedelta(hours=6),
    "8h": timedelta(hours=8),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "3d": timedelta(days=3),
    "1w": timedelta(weeks=1),
}


def ms_to_datetime(ms: int) -> datetime:
    """Convert millisecond timestamp to UTC naive datetime."""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)


def datetime_to_ms(dt: datetime) -> int:
    """Convert datetime to millisecond timestamp."""
    if dt.tzinfo is not None:
        return int(dt.timestamp() * 1000)
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def get_interval_delta(timeframe: str) -> timedelta:
    """Retrieve timedelta corresponding to a Kline interval."""
    tf_clean = timeframe.lower().replace("min", "m")
    if tf_clean in TIMEFRAME_DELTAS:
        return TIMEFRAME_DELTAS[tf_clean]
    return timedelta(hours=1)


class BinanceSyncService:
    """Service for fetching, validating, and persisting market candlestick data."""

    def __init__(
        self,
        primary_url: Optional[str] = None,
        fallback_url: Optional[str] = None,
        timeout: float = 15.0,
        max_retries: int = 5,
        medallion: Optional[MedallionStorageManager] = None,
    ):
        self.primary_url = primary_url or settings.sync.binance_api_url
        self.fallback_url = fallback_url or settings.sync.binance_fallback_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.medallion = medallion or MedallionStorageManager()

    async def fetch_klines_raw(
        self,
        symbol: str,
        interval: str,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        limit: int = 1000,
    ) -> List[List[Any]]:
        """Fetch raw kline arrays from Binance with exponential backoff & fallback."""
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": min(limit, 1000),
        }
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        urls = [self.primary_url, self.fallback_url]
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            url = urls[0] if attempt % 2 != 0 else urls[1]
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        return resp.json()
                    elif resp.status_code == 429:
                        sleep_time = (2 ** attempt) + random.uniform(1.0, 3.0)
                        logger.warning(f"Rate limited by Binance (429). Backing off for {sleep_time:.2f}s")
                        await asyncio.sleep(sleep_time)
                    else:
                        resp.raise_for_status()
            except Exception as e:
                last_error = e
                sleep_time = (settings.sync.retry_backoff_base ** attempt) + random.uniform(0.1, 0.5)
                logger.warning(
                    f"Fetch error on attempt {attempt}/{self.max_retries} for {symbol} ({url}): {e}. "
                    f"Retrying in {sleep_time:.2f}s..."
                )
                await asyncio.sleep(sleep_time)

        logger.error(f"Exhausted retries fetching klines for {symbol} {interval}: {last_error}")
        raise RuntimeError(f"Failed to fetch klines from Binance: {last_error}")

    def parse_kline_payload(
        self,
        symbol: str,
        timeframe: str,
        raw_klines: List[List[Any]],
    ) -> List[Dict[str, Any]]:
        """Parse raw Binance Kline arrays into validated dictionaries."""
        parsed = []
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        for k in raw_klines:
            open_dt = ms_to_datetime(int(k[0]))
            close_dt = ms_to_datetime(int(k[6]))
            is_closed = close_dt <= now_utc

            parsed.append({
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "open_time": open_dt,
                "close_time": close_dt,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "quote_asset_volume": float(k[7]),
                "number_of_trades": int(k[8]),
                "taker_buy_base_asset_volume": float(k[9]),
                "taker_buy_quote_asset_volume": float(k[10]),
                "is_closed": is_closed,
            })
        return parsed

    async def save_klines_idempotent(
        self,
        db: AsyncSession,
        klines_data: List[Dict[str, Any]],
    ) -> int:
        """Insert klines idempotently, preventing duplicates on (symbol, timeframe, open_time)."""
        if not klines_data:
            return 0

        symbol = klines_data[0]["symbol"]
        timeframe = klines_data[0]["timeframe"]
        open_times = [k["open_time"] for k in klines_data]

        stmt = select(Kline.open_time).where(
            and_(
                Kline.symbol == symbol,
                Kline.timeframe == timeframe,
                Kline.open_time.in_(open_times),
            )
        )
        result = await db.execute(stmt)
        existing_times = set(result.scalars().all())

        new_records = []
        seen_in_batch = set()
        for item in klines_data:
            ot = item["open_time"]
            if ot not in existing_times and ot not in seen_in_batch:
                seen_in_batch.add(ot)
                new_records.append(Kline(**item))

        if new_records:
            db.add_all(new_records)
            await db.flush()

        return len(new_records)

    async def update_checkpoint(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        status: str = "SUCCESS",
        error_msg: Optional[str] = None,
        gaps_count: Optional[int] = None,
    ) -> SyncCheckpoint:
        """Update or create synchronization checkpoint and refresh Symbol.last_synced_at."""
        symbol = symbol.upper()
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        stmt = select(SyncCheckpoint).where(
            and_(
                SyncCheckpoint.symbol == symbol,
                SyncCheckpoint.timeframe == timeframe,
            )
        )
        result = await db.execute(stmt)
        checkpoint = result.scalar_one_or_none()

        stats_stmt = select(
            func.count(Kline.id),
            func.min(Kline.open_time),
            func.max(Kline.close_time),
        ).where(
            and_(
                Kline.symbol == symbol,
                Kline.timeframe == timeframe,
            )
        )
        stats_res = await db.execute(stats_stmt)
        total, min_open, max_close = stats_res.one()

        if gaps_count is None:
            gaps = await self.detect_gaps(db, symbol, timeframe)
            gaps_count = len(gaps)

        if not checkpoint:
            checkpoint = SyncCheckpoint(
                symbol=symbol,
                timeframe=timeframe,
                last_open_time=min_open,
                last_close_time=max_close,
                total_candles=total or 0,
                last_sync_status=status,
                last_error=error_msg,
                detected_gaps_count=gaps_count,
                updated_at=now_utc,
            )
            db.add(checkpoint)
        else:
            checkpoint.total_candles = total or 0
            if max_close:
                checkpoint.last_close_time = max_close
            checkpoint.last_sync_status = status
            checkpoint.last_error = error_msg
            checkpoint.detected_gaps_count = gaps_count
            checkpoint.updated_at = now_utc

        # Update Symbol.last_synced_at so market freshness & stale status stay truthful
        sym_res = await db.execute(select(Symbol).where(Symbol.symbol == symbol))
        sym_obj = sym_res.scalar_one_or_none()
        if sym_obj:
            sym_obj.last_synced_at = now_utc

        await db.flush()
        return checkpoint

    async def _persist_medallion_batch(
        self,
        symbol: str,
        timeframe: str,
        raw_batch: List[List[Any]],
        parsed: List[Dict[str, Any]],
    ) -> None:
        """Archive REST batch to Bronze (zstd JSONL) and Silver (Parquet) off the event loop."""
        now_iso = datetime.now(timezone.utc).isoformat()
        bronze_rows = [
            {
                "schema_version": "1.0.0",
                "source": "binance_rest",
                "symbol": symbol,
                "timeframe": timeframe,
                "ingestion_time": now_iso,
                "raw_kline": row,
            }
            for row in raw_batch
        ]

        def _write():
            self.medallion.write_bronze_batch(f"rest_klines_{timeframe}", symbol, bronze_rows)
            self.medallion.write_silver_klines(symbol, timeframe, parsed)

        await asyncio.to_thread(_write)

    async def sync_incremental(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        lookback_days_if_empty: int = 30,
    ) -> Dict[str, Any]:
        """Perform incremental synchronization from last known candle to present."""
        symbol = symbol.upper()
        stmt = select(func.max(Kline.close_time)).where(
            and_(
                Kline.symbol == symbol,
                Kline.timeframe == timeframe,
            )
        )
        res = await db.execute(stmt)
        latest_close = res.scalar()

        if latest_close:
            start_ms = datetime_to_ms(latest_close) + 1
            logger.info(f"Resuming incremental sync for {symbol} {timeframe} from {latest_close}")
        else:
            start_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback_days_if_empty)
            start_ms = datetime_to_ms(start_dt)
            logger.info(f"Seeding new sync for {symbol} {timeframe} from {start_dt}")

        now_ms = datetime_to_ms(datetime.now(timezone.utc).replace(tzinfo=None))
        total_synced = 0
        total_read = 0
        current_start = start_ms

        while current_start < now_ms:
            raw_batch = await self.fetch_klines_raw(
                symbol=symbol,
                interval=timeframe,
                start_time_ms=current_start,
                end_time_ms=now_ms,
                limit=1000,
            )
            if not raw_batch:
                break

            total_read += len(raw_batch)
            parsed = self.parse_kline_payload(symbol, timeframe, raw_batch)
            added = await self.save_klines_idempotent(db, parsed)
            total_synced += added

            if settings.sync.save_parquet:
                try:
                    await self._persist_medallion_batch(symbol, timeframe, raw_batch, parsed)
                except Exception as lake_exc:
                    logger.warning(f"Medallion file persistence warning for {symbol} {timeframe}: {lake_exc}")

            last_close_ms = int(raw_batch[-1][6])
            if last_close_ms <= current_start:
                break
            current_start = last_close_ms + 1

            if len(raw_batch) < 1000:
                break

        await self.update_checkpoint(db, symbol, timeframe, status="SUCCESS")
        await db.commit()

        logger.info(f"Incremental sync finished for {symbol} {timeframe}. Added {total_synced} candles.")
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "rows_read": total_read,
            "added_candles": total_synced,
            "status": "SUCCESS",
        }

    async def detect_gaps(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Tuple[datetime, datetime]]:
        """Identify missing time intervals in stored candles."""
        delta = get_interval_delta(timeframe)
        tolerance = delta * 1.5

        query = select(Kline.open_time).where(
            and_(
                Kline.symbol == symbol.upper(),
                Kline.timeframe == timeframe,
            )
        )
        if start_time:
            query = query.where(Kline.open_time >= start_time)
        if end_time:
            query = query.where(Kline.open_time <= end_time)

        query = query.order_by(Kline.open_time.asc())
        res = await db.execute(query)
        open_times = res.scalars().all()

        gaps: List[Tuple[datetime, datetime]] = []
        if len(open_times) < 2:
            return gaps

        for i in range(1, len(open_times)):
            prev_time = open_times[i - 1]
            curr_time = open_times[i]
            diff = curr_time - prev_time
            if diff > tolerance:
                gap_start = prev_time + delta
                gap_end = curr_time - delta
                gaps.append((gap_start, gap_end))

        return gaps

    async def fill_gaps(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
    ) -> int:
        """Detect and backfill all missing candle gaps."""
        gaps = await self.detect_gaps(db, symbol, timeframe)
        if not gaps:
            return 0

        logger.info(f"Found {len(gaps)} gaps for {symbol} {timeframe}. Filling...")
        total_filled = 0

        for gap_start, gap_end in gaps:
            start_ms = datetime_to_ms(gap_start)
            end_ms = datetime_to_ms(gap_end)

            cur_ms = start_ms
            while cur_ms <= end_ms:
                raw_batch = await self.fetch_klines_raw(
                    symbol=symbol,
                    interval=timeframe,
                    start_time_ms=cur_ms,
                    end_time_ms=end_ms,
                    limit=1000,
                )
                if not raw_batch:
                    break

                parsed = self.parse_kline_payload(symbol, timeframe, raw_batch)
                added = await self.save_klines_idempotent(db, parsed)
                total_filled += added

                if settings.sync.save_parquet:
                    try:
                        await self._persist_medallion_batch(symbol, timeframe, raw_batch, parsed)
                    except Exception:
                        pass

                last_close_ms = int(raw_batch[-1][6])
                if last_close_ms <= cur_ms:
                    break
                cur_ms = last_close_ms + 1

        await self.update_checkpoint(db, symbol, timeframe)
        await db.commit()
        logger.info(f"Filled {total_filled} missing candles across {len(gaps)} gaps.")
        return total_filled

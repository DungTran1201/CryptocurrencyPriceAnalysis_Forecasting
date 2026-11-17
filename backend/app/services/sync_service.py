"""Binance Market Data Synchronization Engine.

Features:
- Primary and fallback Binance REST endpoints with exponential backoff & jitter
- Timestamp normalization (milliseconds to UTC naive datetime)
- Unified SQL + Silver Parquet open->closed candle promotion
- Batch-level transactional persistence + LakeSnapshot manifests + SyncCheckpoint updates
- Deterministic leading/interior/trailing gap detection & backfill (klines + aggTrades)
"""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import random
from typing import Any, Dict, List, Optional, Tuple
import httpx
import pyarrow.parquet as pq
from sqlalchemy import and_, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.logging import get_logger, PerformanceLogger
from backend.app.models.market import Kline, Symbol, SyncCheckpoint
from backend.app.storage.medallion import (
    SILVER_KLINE_SCHEMA,
    SILVER_KLINE_SCHEMA_VERSION,
    SILVER_TRADE_SCHEMA,
    SILVER_TRADE_SCHEMA_VERSION,
    MedallionStorageManager,
    _schema_hash,
    merge_kline_records,
)

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

_BRONZE_SCHEMA_HASH = hashlib.sha256(b"binance_bronze_envelope_v1.1.0").hexdigest()


def ms_to_datetime(ms: int) -> datetime:
    """Convert millisecond timestamp to UTC naive datetime."""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)


def datetime_to_ms(dt: datetime) -> int:
    """Convert datetime to millisecond timestamp."""
    if dt.tzinfo is not None:
        return int(dt.timestamp() * 1000)
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def get_interval_delta(timeframe: str) -> timedelta:
    """Retrieve timedelta corresponding to a Kline interval; raise ValueError if unsupported."""
    tf_clean = timeframe.strip().lower().replace("min", "m")
    if tf_clean in TIMEFRAME_DELTAS:
        return TIMEFRAME_DELTAS[tf_clean]
    raise ValueError(f"Unsupported timeframe: {timeframe!r}")


def _sanitize_error(exc: Exception) -> str:
    return f"{type(exc).__name__}"[:120]


class BinanceSyncService:
    """Service for fetching, validating, and persisting market kline & aggTrade data."""

    def __init__(
        self,
        primary_url: Optional[str] = None,
        fallback_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        medallion: Optional[MedallionStorageManager] = None,
    ):
        self.primary_url = primary_url or settings.sync.binance_api_url
        self.fallback_url = fallback_url or settings.sync.binance_fallback_url
        self.timeout = timeout if timeout is not None else settings.sync.request_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else settings.sync.max_retries
        self.medallion = medallion or MedallionStorageManager()

    async def _fetch_binance_json(
        self,
        urls: List[str],
        params: Dict[str, Any],
        label: str,
    ) -> Any:
        last_error: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(1, self.max_retries + 1):
                url = urls[0] if attempt % 2 != 0 else urls[1]
                try:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        return resp.json()
                    if resp.status_code == 429:
                        sleep_time = (2 ** attempt) + random.uniform(1.0, 3.0)
                        logger.warning(f"Rate limited by Binance (429) on {label}. Backing off {sleep_time:.2f}s")
                        await asyncio.sleep(sleep_time)
                    else:
                        resp.raise_for_status()
                except Exception as exc:
                    last_error = exc
                    sleep_time = (settings.sync.retry_backoff_base ** attempt) + random.uniform(0.1, 0.5)
                    logger.warning(
                        f"Fetch error attempt {attempt}/{self.max_retries} for {label} ({url}): {exc}. "
                        f"Retrying in {sleep_time:.2f}s..."
                    )
                    await asyncio.sleep(sleep_time)

        logger.error(f"Exhausted retries fetching {label}: {last_error}")
        raise RuntimeError(f"Failed to fetch from Binance ({label}): {_sanitize_error(last_error) if last_error else 'Unknown'}")

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

        return await self._fetch_binance_json(
            [self.primary_url, self.fallback_url],
            params=params,
            label=f"klines {symbol.upper()} {interval}",
        )

    async def fetch_agg_trades_raw(
        self,
        symbol: str,
        from_id: Optional[int] = None,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Fetch raw aggregate trade dicts from Binance /api/v3/aggTrades."""
        primary_agg = self.primary_url.replace("/klines", "/aggTrades")
        fallback_agg = self.fallback_url.replace("/klines", "/aggTrades")
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "limit": min(limit, 1000),
        }
        if from_id is not None:
            params["fromId"] = int(from_id)
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)

        return await self._fetch_binance_json(
            [primary_agg, fallback_agg],
            params=params,
            label=f"aggTrades {symbol.upper()}",
        )

    def parse_kline_payload(
        self,
        symbol: str,
        timeframe: str,
        raw_klines: List[List[Any]],
        source: str = "binance_rest",
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
                "source": source,
                "ingestion_time": now_utc,
            })
        return parsed

    async def upsert_klines_sql(
        self,
        db: AsyncSession,
        klines_data: List[Dict[str, Any]],
        force_reconcile: bool = False,
    ) -> Tuple[int, int]:
        """Atomically insert/promote klines on (symbol, timeframe, open_time).

        Enforces unified open->closed promotion and rejects closed->open downgrades.
        Returns (inserted_count, updated_count).
        """
        if not klines_data:
            return 0, 0

        symbol = klines_data[0]["symbol"].upper()
        timeframe = klines_data[0]["timeframe"].lower()

        dedup_batch: Dict[datetime, Dict[str, Any]] = {}
        for raw_item in klines_data:
            item = dict(raw_item)
            item["symbol"] = item["symbol"].upper()
            item["timeframe"] = item["timeframe"].lower()
            ot = item["open_time"]
            if isinstance(ot, str):
                ot = datetime.fromisoformat(ot.replace("Z", "+00:00")).replace(tzinfo=None)
                item["open_time"] = ot
            ct = item["close_time"]
            if isinstance(ct, str):
                ct = datetime.fromisoformat(ct.replace("Z", "+00:00")).replace(tzinfo=None)
                item["close_time"] = ct
            dedup_batch[ot] = merge_kline_records(dedup_batch.get(ot), item, force_reconcile=force_reconcile)

        open_times = sorted(dedup_batch.keys())
        existing_map: Dict[datetime, Dict[str, Any]] = {}
        for i in range(0, len(open_times), 500):
            chunk_ots = open_times[i:i + 500]
            stmt = select(
                Kline.open_time,
                Kline.close_time,
                Kline.volume,
                Kline.is_closed,
            ).where(
                and_(
                    Kline.symbol == symbol,
                    Kline.timeframe == timeframe,
                    Kline.open_time.in_(chunk_ots),
                )
            )
            for ot_val, ct_val, vol_val, closed_val in (await db.execute(stmt)).all():
                existing_map[ot_val] = {
                    "open_time": ot_val,
                    "close_time": ct_val,
                    "volume": vol_val,
                    "is_closed": closed_val,
                }

        to_upsert: List[Dict[str, Any]] = []
        inserted_count = 0
        updated_count = 0

        for ot in open_times:
            incoming = dedup_batch[ot]
            existing = existing_map.get(ot)
            if existing is None:
                inserted_count += 1
                to_upsert.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open_time": incoming["open_time"],
                    "close_time": incoming["close_time"],
                    "open": float(incoming["open"]),
                    "high": float(incoming["high"]),
                    "low": float(incoming["low"]),
                    "close": float(incoming["close"]),
                    "volume": float(incoming["volume"]),
                    "quote_asset_volume": incoming.get("quote_asset_volume"),
                    "number_of_trades": incoming.get("number_of_trades"),
                    "taker_buy_base_asset_volume": incoming.get("taker_buy_base_asset_volume"),
                    "taker_buy_quote_asset_volume": incoming.get("taker_buy_quote_asset_volume"),
                    "is_closed": bool(incoming.get("is_closed", True)),
                })
            else:
                winner = merge_kline_records(existing, incoming, force_reconcile=force_reconcile)
                if winner is incoming:
                    updated_count += 1
                    to_upsert.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "open_time": incoming["open_time"],
                        "close_time": incoming["close_time"],
                        "open": float(incoming["open"]),
                        "high": float(incoming["high"]),
                        "low": float(incoming["low"]),
                        "close": float(incoming["close"]),
                        "volume": float(incoming["volume"]),
                        "quote_asset_volume": incoming.get("quote_asset_volume"),
                        "number_of_trades": incoming.get("number_of_trades"),
                        "taker_buy_base_asset_volume": incoming.get("taker_buy_base_asset_volume"),
                        "taker_buy_quote_asset_volume": incoming.get("taker_buy_quote_asset_volume"),
                        "is_closed": bool(incoming.get("is_closed", True)),
                    })

        if not to_upsert:
            return 0, 0

        bind = db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else "sqlite"

        for i in range(0, len(to_upsert), 400):
            chunk = to_upsert[i:i + 400]
            if dialect_name == "postgresql":
                ins = postgresql.insert(Kline).values(chunk)
                excl = ins.excluded
                update_cols = {
                    "close_time": excl.close_time,
                    "open": excl.open,
                    "high": excl.high,
                    "low": excl.low,
                    "close": excl.close,
                    "volume": excl.volume,
                    "quote_asset_volume": excl.quote_asset_volume,
                    "number_of_trades": excl.number_of_trades,
                    "taker_buy_base_asset_volume": excl.taker_buy_base_asset_volume,
                    "taker_buy_quote_asset_volume": excl.taker_buy_quote_asset_volume,
                    "is_closed": excl.is_closed,
                }
                if force_reconcile:
                    stmt = ins.on_conflict_do_update(
                        index_elements=["symbol", "timeframe", "open_time"],
                        set_=update_cols,
                    )
                else:
                    stmt = ins.on_conflict_do_update(
                        index_elements=["symbol", "timeframe", "open_time"],
                        set_=update_cols,
                        where=(Kline.is_closed == False) & (  # noqa: E712
                            (excl.is_closed == True)  # noqa: E712
                            | ((excl.close_time >= Kline.close_time) & (excl.volume >= Kline.volume))
                        ),
                    )
                await db.execute(stmt)
            elif dialect_name == "sqlite":
                ins = sqlite.insert(Kline).values(chunk)
                excl = ins.excluded
                update_cols = {
                    "close_time": excl.close_time,
                    "open": excl.open,
                    "high": excl.high,
                    "low": excl.low,
                    "close": excl.close,
                    "volume": excl.volume,
                    "quote_asset_volume": excl.quote_asset_volume,
                    "number_of_trades": excl.number_of_trades,
                    "taker_buy_base_asset_volume": excl.taker_buy_base_asset_volume,
                    "taker_buy_quote_asset_volume": excl.taker_buy_quote_asset_volume,
                    "is_closed": excl.is_closed,
                }
                if force_reconcile:
                    stmt = ins.on_conflict_do_update(
                        index_elements=["symbol", "timeframe", "open_time"],
                        set_=update_cols,
                    )
                else:
                    stmt = ins.on_conflict_do_update(
                        index_elements=["symbol", "timeframe", "open_time"],
                        set_=update_cols,
                        where=(Kline.is_closed == False) & (  # noqa: E712
                            (excl.is_closed == True)  # noqa: E712
                            | ((excl.close_time >= Kline.close_time) & (excl.volume >= Kline.volume))
                        ),
                    )
                await db.execute(stmt)
            else:
                for row in chunk:
                    db.add(Kline(**row))

        await db.flush()
        return inserted_count, updated_count

    async def save_klines_idempotent(
        self,
        db: AsyncSession,
        klines_data: List[Dict[str, Any]],
    ) -> int:
        """Insert/promote klines idempotently on (symbol, timeframe, open_time)."""
        inserted, updated = await self.upsert_klines_sql(db, klines_data, force_reconcile=False)
        return inserted + updated

    async def update_checkpoint(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        status: str = "SUCCESS",
        error_msg: Optional[str] = None,
        gaps_count: Optional[int] = None,
        last_agg_trade_id: Optional[int] = None,
    ) -> SyncCheckpoint:
        """Update or create synchronization checkpoint and refresh Symbol.last_synced_at."""
        symbol = symbol.upper()
        tf_norm = timeframe if timeframe == "aggTrade" else timeframe.lower()
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        stmt = select(SyncCheckpoint).where(
            and_(
                SyncCheckpoint.symbol == symbol,
                SyncCheckpoint.timeframe == tf_norm,
            )
        )
        checkpoint = (await db.execute(stmt)).scalar_one_or_none()

        if tf_norm == "aggTrade":
            total, min_open, max_open, max_close = 0, None, None, None
            resolved_gaps = gaps_count if gaps_count is not None else 0
            comp_status = "COMPLETE" if (last_agg_trade_id is not None and resolved_gaps == 0) else (
                "INCOMPLETE" if resolved_gaps > 0 else "UNPOPULATED"
            )
        else:
            stats_stmt = select(
                func.count(Kline.id),
                func.min(Kline.open_time),
                func.max(Kline.open_time),
                func.max(Kline.close_time),
            ).where(
                and_(
                    Kline.symbol == symbol,
                    Kline.timeframe == tf_norm,
                )
            )
            total, min_open, max_open, max_close = (await db.execute(stats_stmt)).one()
            total = int(total or 0)
            if gaps_count is None:
                gaps = await self.detect_gaps(db, symbol, tf_norm, include_trailing=(status == "SUCCESS"))
                resolved_gaps = len(gaps)
            else:
                resolved_gaps = gaps_count
            if total == 0:
                comp_status = "UNPOPULATED"
            elif status == "FAILED":
                comp_status = "FAILED"
            elif resolved_gaps == 0:
                comp_status = "COMPLETE"
            else:
                comp_status = "INCOMPLETE"

        safe_err = error_msg[:512] if error_msg else None

        if not checkpoint:
            checkpoint = SyncCheckpoint(
                symbol=symbol,
                timeframe=tf_norm,
                first_open_time=min_open,
                last_open_time=max_open,
                last_close_time=max_close,
                last_agg_trade_id=last_agg_trade_id,
                total_candles=total,
                last_sync_status=status,
                completeness_status=comp_status,
                last_error=safe_err,
                detected_gaps_count=resolved_gaps,
                updated_at=now_utc,
            )
            db.add(checkpoint)
        else:
            checkpoint.total_candles = total
            if min_open is not None:
                checkpoint.first_open_time = min_open
            if max_open is not None:
                checkpoint.last_open_time = max_open
            if max_close is not None:
                checkpoint.last_close_time = max_close
            if last_agg_trade_id is not None:
                checkpoint.last_agg_trade_id = max(
                    int(checkpoint.last_agg_trade_id or 0),
                    int(last_agg_trade_id),
                )
            checkpoint.last_sync_status = status
            checkpoint.completeness_status = comp_status
            checkpoint.last_error = safe_err
            checkpoint.detected_gaps_count = resolved_gaps
            checkpoint.updated_at = now_utc

        if status == "SUCCESS":
            sym_obj = (await db.execute(select(Symbol).where(Symbol.symbol == symbol))).scalar_one_or_none()
            if sym_obj:
                sym_obj.last_synced_at = now_utc

        await db.flush()
        return checkpoint

    async def _persist_medallion_batch(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        raw_batch: List[List[Any]],
        parsed: List[Dict[str, Any]],
        cleanup_replaced: bool = False,
    ) -> List[str]:
        """Archive REST batch to Bronze (zstd JSONL) and Silver (Parquet), then stage SQL manifests."""
        now_iso = datetime.now(timezone.utc).isoformat()
        bronze_rows = [
            {
                "schema_version": "1.1.0",
                "event_id": f"rest_kline:{symbol}:{timeframe}:{row[0]}",
                "event_type": "rest_kline",
                "source": "binance_rest",
                "symbol": symbol,
                "timeframe": timeframe,
                "event_time": ms_to_datetime(int(row[6])).isoformat(),
                "ingestion_time": now_iso,
                "raw_kline": row,
            }
            for row in raw_batch
        ]

        # Resolve active Silver manifest keys per dt so read-merge sees only committed objects
        active_by_dt: Dict[str, List[str]] = {}
        for item in parsed:
            dt_key = item["open_time"].strftime("%Y-%m-%d")
            if dt_key not in active_by_dt:
                active_by_dt[dt_key] = await self.medallion.get_active_manifest_keys(
                    db, "silver_klines", symbol=symbol, timeframe=timeframe, dt_key=dt_key
                )

        def _write():
            b_res = self.medallion.write_bronze_batch(f"rest_klines_{timeframe}", symbol, bronze_rows)
            s_res = self.medallion.write_silver_klines(
                symbol,
                timeframe,
                parsed,
                cleanup_replaced=cleanup_replaced,
                source_keys_override=active_by_dt if any(active_by_dt.values()) else None,
            )
            return b_res, s_res

        b_res, s_res = await asyncio.to_thread(_write)
        staged_keys: List[str] = []
        if b_res.get("file_meta"):
            staged_keys.append(b_res["file_meta"]["object_key"])
            await self.medallion.commit_manifest(
                db=db,
                dataset_id="bronze_market_events",
                new_file_metas=[b_res["file_meta"]],
                schema_version="1.1.0",
                schema_hash=_BRONZE_SCHEMA_HASH,
                batch_type="REST_BACKFILL",
                producer_name="sync_service",
                symbol=symbol,
                timeframe=timeframe,
                replace_partitions=False,
            )
        if s_res.get("file_metas"):
            staged_keys.extend(m["object_key"] for m in s_res["file_metas"])
            await self.medallion.commit_manifest(
                db=db,
                dataset_id="silver_klines",
                new_file_metas=s_res["file_metas"],
                schema_version=SILVER_KLINE_SCHEMA_VERSION,
                schema_hash=_schema_hash(SILVER_KLINE_SCHEMA),
                batch_type="REST_BACKFILL",
                producer_name="sync_service",
                symbol=symbol,
                timeframe=timeframe,
                replace_partitions=True,
            )
        return staged_keys

    def _cleanup_staged_keys(self, keys: List[str]) -> None:
        for k in keys:
            try:
                self.medallion.backend.delete(k)
            except Exception:
                pass

    async def sync_incremental(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        lookback_days_if_empty: int = 30,
    ) -> Dict[str, Any]:
        """Perform incremental synchronization from earliest unclosed or last closed candle to present."""
        symbol = symbol.upper()
        get_interval_delta(timeframe)
        tf_norm = timeframe.lower()

        min_unclosed_stmt = select(func.min(Kline.open_time)).where(
            and_(Kline.symbol == symbol, Kline.timeframe == tf_norm, Kline.is_closed == False)  # noqa: E712
        )
        min_unclosed = (await db.execute(min_unclosed_stmt)).scalar()

        if min_unclosed is not None:
            start_ms = datetime_to_ms(min_unclosed)
            logger.info(f"Resuming sync for {symbol} {tf_norm} from unclosed bar {min_unclosed}")
        else:
            latest_closed_stmt = select(func.max(Kline.close_time)).where(
                and_(Kline.symbol == symbol, Kline.timeframe == tf_norm, Kline.is_closed == True)  # noqa: E712
            )
            latest_close = (await db.execute(latest_closed_stmt)).scalar()
            if latest_close:
                start_ms = datetime_to_ms(latest_close) + 1
                logger.info(f"Resuming incremental sync for {symbol} {tf_norm} from {latest_close}")
            else:
                start_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback_days_if_empty)
                start_ms = datetime_to_ms(start_dt)
                logger.info(f"Seeding new sync for {symbol} {tf_norm} from {start_dt}")

        now_ms = datetime_to_ms(datetime.now(timezone.utc).replace(tzinfo=None))
        total_inserted = 0
        total_updated = 0
        total_read = 0
        current_start = start_ms

        try:
            while current_start < now_ms:
                raw_batch = await self.fetch_klines_raw(
                    symbol=symbol,
                    interval=tf_norm,
                    start_time_ms=current_start,
                    end_time_ms=now_ms,
                    limit=1000,
                )
                if not raw_batch:
                    break

                total_read += len(raw_batch)
                parsed = self.parse_kline_payload(symbol, tf_norm, raw_batch)
                staged_keys: List[str] = []
                try:
                    ins, upd = await self.upsert_klines_sql(db, parsed)
                    total_inserted += ins
                    total_updated += upd

                    if settings.sync.save_parquet:
                        staged_keys = await self._persist_medallion_batch(db, symbol, tf_norm, raw_batch, parsed)

                    await self.update_checkpoint(db, symbol, tf_norm, status="SUCCESS")
                    await db.commit()
                except Exception:
                    await db.rollback()
                    if staged_keys:
                        await asyncio.to_thread(self._cleanup_staged_keys, staged_keys)
                    raise

                last_close_ms = int(raw_batch[-1][6])
                if last_close_ms <= current_start:
                    break
                current_start = last_close_ms + 1

                if len(raw_batch) < 1000:
                    break

            if total_read == 0:
                await self.update_checkpoint(db, symbol, tf_norm, status="SUCCESS")
                await db.commit()

        except Exception as exc:
            await db.rollback()
            await self.update_checkpoint(db, symbol, tf_norm, status="FAILED", error_msg=_sanitize_error(exc))
            await db.commit()
            raise

        logger.info(
            f"Incremental sync finished for {symbol} {tf_norm}. "
            f"Added {total_inserted}, promoted/updated {total_updated} candles."
        )
        return {
            "symbol": symbol,
            "timeframe": tf_norm,
            "rows_read": total_read,
            "added_candles": total_inserted + total_updated,
            "inserted_candles": total_inserted,
            "updated_candles": total_updated,
            "status": "SUCCESS",
        }

    async def detect_gaps(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        include_trailing: bool = False,
    ) -> List[Tuple[datetime, datetime]]:
        """Identify missing leading, interior, and (optionally) trailing time intervals in stored candles."""
        delta = get_interval_delta(timeframe)
        tolerance = delta * 1.5
        tf_norm = timeframe.lower()

        query = select(Kline.open_time).where(
            and_(
                Kline.symbol == symbol.upper(),
                Kline.timeframe == tf_norm,
            )
        )
        if start_time:
            query = query.where(Kline.open_time >= start_time)
        if end_time:
            query = query.where(Kline.open_time <= end_time)

        query = query.order_by(Kline.open_time.asc())
        open_times = list((await db.execute(query)).scalars().all())

        gaps: List[Tuple[datetime, datetime]] = []
        if not open_times:
            if start_time is not None and end_time is not None and (end_time - start_time) >= delta:
                gaps.append((start_time, end_time))
            return gaps

        if start_time is not None and (open_times[0] - start_time) > tolerance:
            gaps.append((start_time, open_times[0] - delta))

        for i in range(1, len(open_times)):
            prev_time = open_times[i - 1]
            curr_time = open_times[i]
            if (curr_time - prev_time) > tolerance:
                gaps.append((prev_time + delta, curr_time - delta))

        tail_ref = end_time
        if tail_ref is None and include_trailing:
            tail_ref = datetime.now(timezone.utc).replace(tzinfo=None) - delta
        if tail_ref is not None and (tail_ref - open_times[-1]) > tolerance:
            gaps.append((open_times[-1] + delta, tail_ref))

        return gaps

    async def fill_gaps(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        include_trailing: bool = False,
    ) -> int:
        """Detect and backfill all missing candle gaps atomically per batch."""
        symbol = symbol.upper()
        get_interval_delta(timeframe)
        tf_norm = timeframe.lower()
        gaps = await self.detect_gaps(db, symbol, tf_norm, include_trailing=include_trailing)
        if not gaps:
            return 0

        logger.info(f"Found {len(gaps)} gaps for {symbol} {tf_norm}. Filling...")
        total_filled = 0

        try:
            for gap_start, gap_end in gaps:
                start_ms = datetime_to_ms(gap_start)
                end_ms = datetime_to_ms(gap_end)
                cur_ms = start_ms

                while cur_ms <= end_ms:
                    raw_batch = await self.fetch_klines_raw(
                        symbol=symbol,
                        interval=tf_norm,
                        start_time_ms=cur_ms,
                        end_time_ms=end_ms,
                        limit=1000,
                    )
                    if not raw_batch:
                        break

                    parsed = self.parse_kline_payload(symbol, tf_norm, raw_batch)
                    staged_keys: List[str] = []
                    try:
                        ins, upd = await self.upsert_klines_sql(db, parsed)
                        total_filled += ins + upd

                        if settings.sync.save_parquet:
                            staged_keys = await self._persist_medallion_batch(db, symbol, tf_norm, raw_batch, parsed)

                        await db.flush()
                    except Exception:
                        await db.rollback()
                        if staged_keys:
                            await asyncio.to_thread(self._cleanup_staged_keys, staged_keys)
                        raise

                    last_close_ms = int(raw_batch[-1][6])
                    if last_close_ms <= cur_ms:
                        break
                    cur_ms = last_close_ms + 1

            await self.update_checkpoint(db, symbol, tf_norm, status="SUCCESS")
            await db.commit()
        except Exception as exc:
            await db.rollback()
            await self.update_checkpoint(db, symbol, tf_norm, status="FAILED", error_msg=_sanitize_error(exc))
            await db.commit()
            raise

        logger.info(f"Filled {total_filled} missing candles across {len(gaps)} gaps for {symbol} {tf_norm}.")
        return total_filled

    def detect_agg_trade_gaps(
        self,
        symbol: str,
        dt_key: Optional[str] = None,
    ) -> List[Tuple[int, int]]:
        """Scan Silver agg_trades Parquet partitions for missing agg_trade_id ranges."""
        symbol_up = symbol.upper()
        prefix = f"{settings.storage.silver_subdir}/source=binance/event_type=agg_trades"
        if dt_key:
            prefix = f"{prefix}/dt={dt_key}/symbol={symbol_up}"
        keys = [
            k for k in self.medallion.backend.list_keys(prefix=prefix, suffix=".parquet")
            if f"/symbol={symbol_up}/" in k
        ]
        if not keys:
            return []

        ids: List[int] = []
        for k in keys:
            tbl = pq.read_table(io.BytesIO(self.medallion.backend.read_bytes(k)), columns=["agg_trade_id"])
            ids.extend(int(v) for v in tbl.column("agg_trade_id").to_pylist())

        sorted_ids = sorted(set(ids))
        gaps: List[Tuple[int, int]] = []
        for i in range(1, len(sorted_ids)):
            if sorted_ids[i] - sorted_ids[i - 1] > 1:
                gaps.append((sorted_ids[i - 1] + 1, sorted_ids[i] - 1))
        return gaps

    async def sync_agg_trades(
        self,
        db: AsyncSession,
        symbol: str,
        from_id: Optional[int] = None,
        max_batches: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Bounded REST backfill of aggregate trades via /api/v3/aggTrades?fromId=..."""
        symbol = symbol.upper()
        batch_cap = max_batches if max_batches is not None else settings.streaming.aggtrade_backfill_max_batches

        cur_from_id = from_id
        if cur_from_id is None:
            ckpt = (
                await db.execute(
                    select(SyncCheckpoint).where(
                        and_(SyncCheckpoint.symbol == symbol, SyncCheckpoint.timeframe == "aggTrade")
                    )
                )
            ).scalar_one_or_none()
            if ckpt and ckpt.last_agg_trade_id is not None:
                cur_from_id = int(ckpt.last_agg_trade_id) + 1

        total_trades = 0
        highest_id: Optional[int] = None

        try:
            for batch_idx in range(batch_cap):
                raw_trades = await self.fetch_agg_trades_raw(
                    symbol=symbol,
                    from_id=cur_from_id,
                    limit=1000,
                )
                if not raw_trades:
                    break

                now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
                parsed_trades: List[Dict[str, Any]] = []
                bronze_rows: List[Dict[str, Any]] = []
                for t in raw_trades:
                    aid = int(t["a"])
                    price = float(t["p"])
                    qty = float(t["q"])
                    trade_dt = ms_to_datetime(int(t["T"]))
                    parsed_trades.append({
                        "symbol": symbol,
                        "agg_trade_id": aid,
                        "price": price,
                        "quantity": qty,
                        "quote_quantity": round(price * qty, 8),
                        "is_buyer_maker": bool(t["m"]),
                        "trade_time": trade_dt,
                        "event_time": trade_dt,
                        "ingestion_time": now_dt,
                        "source": "binance_rest",
                    })
                    bronze_rows.append({
                        "schema_version": "1.1.0",
                        "event_id": f"aggTrade:{symbol}:{aid}",
                        "event_type": "aggTrade",
                        "source": "binance_rest",
                        "symbol": symbol,
                        "event_time": trade_dt.isoformat(),
                        "ingestion_time": now_dt.isoformat(),
                        "payload": t,
                    })

                staged_keys: List[str] = []
                try:
                    def _write_trades():
                        b_res = self.medallion.write_bronze_batch("aggtrade_rest", symbol, bronze_rows)
                        s_res = self.medallion.write_silver_trades(symbol, parsed_trades, cleanup_replaced=False)
                        return b_res, s_res

                    b_res, s_res = await asyncio.to_thread(_write_trades)
                    if b_res.get("file_meta"):
                        staged_keys.append(b_res["file_meta"]["object_key"])
                        await self.medallion.commit_manifest(
                            db=db,
                            dataset_id="bronze_market_events",
                            new_file_metas=[b_res["file_meta"]],
                            schema_version="1.1.0",
                            schema_hash=_BRONZE_SCHEMA_HASH,
                            batch_type="REST_BACKFILL",
                            producer_name="sync_service",
                            symbol=symbol,
                            replace_partitions=False,
                        )
                    if s_res.get("file_metas"):
                        staged_keys.extend(m["object_key"] for m in s_res["file_metas"])
                        await self.medallion.commit_manifest(
                            db=db,
                            dataset_id="silver_agg_trades",
                            new_file_metas=s_res["file_metas"],
                            schema_version=SILVER_TRADE_SCHEMA_VERSION,
                            schema_hash=_schema_hash(SILVER_TRADE_SCHEMA),
                            batch_type="REST_BACKFILL",
                            producer_name="sync_service",
                            symbol=symbol,
                            replace_partitions=bool(s_res.get("compacted")),
                        )

                    batch_max_id = max(t["agg_trade_id"] for t in parsed_trades)
                    highest_id = max(highest_id or 0, batch_max_id)
                    total_trades += len(parsed_trades)

                    await self.update_checkpoint(
                        db,
                        symbol,
                        "aggTrade",
                        status="SUCCESS",
                        gaps_count=0,
                        last_agg_trade_id=highest_id,
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    if staged_keys:
                        await asyncio.to_thread(self._cleanup_staged_keys, staged_keys)
                    raise

                cur_from_id = batch_max_id + 1
                if len(raw_trades) < 1000:
                    break
        except Exception as exc:
            await db.rollback()
            await self.update_checkpoint(db, symbol, "aggTrade", status="FAILED", error_msg=_sanitize_error(exc))
            await db.commit()
            raise

        return {
            "symbol": symbol,
            "added_trades": total_trades,
            "last_agg_trade_id": highest_id,
            "status": "SUCCESS",
        }

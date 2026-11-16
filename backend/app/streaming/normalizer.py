"""Normalize raw Binance WebSocket and REST payloads into canonical events."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import ValidationError

from backend.app.schemas.events import (
    CanonicalAggTradeEvent,
    CanonicalKlineEvent,
    CanonicalMarketEvent,
)


class NormalizationError(ValueError):
    """Raised when an inbound market payload violates canonical schema or geometry."""


def _ms_to_utc_naive(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)


def normalize_binance_ws_payload(
    raw_msg: Dict[str, Any],
    ingestion_time: Optional[datetime] = None,
) -> CanonicalMarketEvent:
    """Convert raw Binance WS JSON payload (combined or single stream) into canonical schema."""
    ing_ts = ingestion_time or datetime.now(timezone.utc).replace(tzinfo=None)
    payload = raw_msg.get("data", raw_msg) if isinstance(raw_msg, dict) else None
    if not isinstance(payload, dict):
        raise NormalizationError("WebSocket message payload is not a JSON object")

    event_type = payload.get("e")
    try:
        if event_type == "aggTrade":
            symbol = str(payload["s"]).upper()
            agg_id = int(payload["a"])
            price = float(payload["p"])
            qty = float(payload["q"])
            event_ms = int(payload["E"])
            trade_ms = int(payload["T"])
            return CanonicalAggTradeEvent(
                event_id=f"aggTrade:{symbol}:{agg_id}",
                source="binance_ws",
                symbol=symbol,
                agg_trade_id=agg_id,
                price=price,
                quantity=qty,
                quote_quantity=round(price * qty, 8),
                is_buyer_maker=bool(payload["m"]),
                event_time=_ms_to_utc_naive(event_ms),
                trade_time=_ms_to_utc_naive(trade_ms),
                ingestion_time=ing_ts,
            )

        if event_type == "kline":
            k = payload["k"]
            symbol = str(k.get("s") or payload["s"]).upper()
            timeframe = str(k["i"]).lower()
            open_ms = int(k["t"])
            close_ms = int(k["T"])
            is_closed = bool(k["x"])
            event_ms = int(payload.get("E", close_ms))
            # Distinct dedup id for closed bars vs forming ticks
            suffix = "closed" if is_closed else f"tick:{event_ms}"
            return CanonicalKlineEvent(
                event_id=f"kline:{symbol}:{timeframe}:{open_ms}:{suffix}",
                source="binance_ws",
                symbol=symbol,
                timeframe=timeframe,
                open_time=_ms_to_utc_naive(open_ms),
                close_time=_ms_to_utc_naive(close_ms),
                open=float(k["o"]),
                high=float(k["h"]),
                low=float(k["l"]),
                close=float(k["c"]),
                volume=float(k["v"]),
                quote_asset_volume=float(k["q"]) if k.get("q") is not None else None,
                number_of_trades=int(k["n"]) if k.get("n") is not None else None,
                taker_buy_base_asset_volume=float(k["V"]) if k.get("V") is not None else None,
                taker_buy_quote_asset_volume=float(k["Q"]) if k.get("Q") is not None else None,
                is_closed=is_closed,
                event_time=_ms_to_utc_naive(event_ms),
                ingestion_time=ing_ts,
            )

        raise NormalizationError(f"Unsupported Binance event type: {event_type!r}")
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise NormalizationError(f"Failed to normalize Binance payload: {exc}") from exc


def subject_for_event(event: CanonicalMarketEvent) -> str:
    """Compute canonical NATS subject routing key for an event."""
    if isinstance(event, CanonicalAggTradeEvent):
        return f"market.aggtrade.{event.symbol}"
    return f"market.kline.{event.timeframe}.{event.symbol}"


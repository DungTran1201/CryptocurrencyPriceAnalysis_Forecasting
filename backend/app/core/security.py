"""Security and boundary validation utilities."""

import secrets
from typing import Optional
from fastapi import Header, HTTPException, status

from backend.app.core.config import settings

VALID_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1d"}
VALID_STREAM_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}


def validate_symbol(symbol: str) -> str:
    """Validate and normalize trading symbol."""
    normalized = symbol.strip().upper()
    if not normalized or len(normalized) < 3 or len(normalized) > 20 or not normalized.isalnum():
        raise HTTPException(status_code=400, detail=f"Invalid symbol format '{symbol}'")
    return normalized


def validate_timeframe(timeframe: str, allowed: Optional[set] = None) -> str:
    """Validate candlestick timeframe against allowlist."""
    tf = timeframe.strip().lower()
    valid = allowed or VALID_TIMEFRAMES
    if tf not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported timeframe '{timeframe}'. Valid options: {', '.join(sorted(valid))}",
        )
    return tf


async def require_admin_if_configured(x_admin_token: Optional[str] = Header(default=None)) -> None:
    """Enforce X-Admin-Token on privileged mutation routes when ADMIN_API_TOKEN is configured."""
    expected = settings.admin_api_token
    if not expected:
        return
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Admin-Token header for administrative operation.",
        )


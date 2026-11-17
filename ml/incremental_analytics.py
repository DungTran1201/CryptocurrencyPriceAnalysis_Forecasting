"""Incremental O(1)-per-bar Financial Analytics & Technical Indicator Engine.

Maintains bounded per-symbol rolling state with exact mathematical parity against
vectorized batch reference calculations in `ml.features` and `AnalyticsService`.
Supports atomic JSON checkpoint serialization and idempotent trade/bar recovery.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple
import uuid
import numpy as np
import pandas as pd

from backend.app.core.logging import get_logger
from backend.app.core.metrics import PROCESSING_FAILURES
from ml.features import (
    compute_sma,
    compute_ema,
    compute_rsi,
    compute_bollinger_bands,
    compute_macd,
)

logger = get_logger("IncrementalAnalytics")

PERIODS_PER_YEAR: Dict[str, int] = {
    "1m": 365 * 24 * 60,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2,
    "1h": 365 * 24,
    "2h": 365 * 12,
    "4h": 365 * 6,
    "1d": 365,
    "1w": 52,
}


@dataclass
class IncrementalSymbolState:
    """Bounded per-symbol incremental state for indicators, risk, and live ticks."""
    symbol: str
    timeframe: str = "1m"
    max_bars: int = 300

    bar_count: int = 0
    last_open_time: Optional[str] = None
    last_close: Optional[float] = None
    prev_close: Optional[float] = None

    # EMA states (alpha = 2 / (n + 1)) matching pandas ewm(span=n, adjust=False)
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_valid_count: int = 0

    # Circular buffers for exact window parity
    closes: Deque[float] = field(default_factory=lambda: deque(maxlen=300))
    gains_14: Deque[float] = field(default_factory=lambda: deque(maxlen=14))
    losses_14: Deque[float] = field(default_factory=lambda: deque(maxlen=14))
    tr_14: Deque[float] = field(default_factory=lambda: deque(maxlen=14))
    simple_returns: Deque[float] = field(default_factory=lambda: deque(maxlen=300))
    log_returns: Deque[float] = field(default_factory=lambda: deque(maxlen=300))

    # Session VWAP (resets at UTC midnight)
    vwap_utc_date: Optional[str] = None
    vwap_pv_sum: float = 0.0
    vwap_vol_sum: float = 0.0

    # Drawdown tracking
    running_peak: Optional[float] = None
    max_drawdown_pct: float = 0.0
    current_drawdown_pct: float = 0.0

    # Live aggTrade ticker state (persisted for idempotent crash/redelivery recovery)
    last_agg_trade_id: Optional[int] = None
    live_price: Optional[float] = None
    live_trade_qty: Optional[float] = None
    live_trade_time: Optional[str] = None
    live_trades_count: int = 0
    live_vwap_pv: float = 0.0
    live_vwap_vol: float = 0.0

    def __post_init__(self) -> None:
        if self.closes.maxlen != self.max_bars:
            self.closes = deque(self.closes, maxlen=self.max_bars)
        if self.simple_returns.maxlen != self.max_bars:
            self.simple_returns = deque(self.simple_returns, maxlen=self.max_bars)
        if self.log_returns.maxlen != self.max_bars:
            self.log_returns = deque(self.log_returns, maxlen=self.max_bars)

    def update_trade(
        self,
        price: float,
        qty: float,
        trade_time: datetime,
        agg_trade_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Update intrabar live ticker & live trade VWAP in O(1) idempotently."""
        if agg_trade_id is not None:
            aid = int(agg_trade_id)
            if self.last_agg_trade_id is not None and aid <= self.last_agg_trade_id:
                return {
                    "symbol": self.symbol,
                    "live_price": self.live_price,
                    "live_trade_qty": self.live_trade_qty,
                    "live_trade_time": self.live_trade_time,
                    "live_trades_count": self.live_trades_count,
                    "live_vwap": round(self.live_vwap_pv / self.live_vwap_vol, 4) if self.live_vwap_vol > 0 else None,
                    "last_agg_trade_id": self.last_agg_trade_id,
                }
            self.last_agg_trade_id = aid

        self.live_price = float(price)
        self.live_trade_qty = float(qty)
        self.live_trade_time = trade_time.isoformat()
        self.live_trades_count += 1
        trade_day = trade_time.strftime("%Y-%m-%d")
        if self.vwap_utc_date != trade_day:
            self.live_vwap_pv = 0.0
            self.live_vwap_vol = 0.0
            self.vwap_utc_date = trade_day
            self.vwap_pv_sum = 0.0
            self.vwap_vol_sum = 0.0
        self.live_vwap_pv += price * qty
        self.live_vwap_vol += qty
        return {
            "symbol": self.symbol,
            "live_price": self.live_price,
            "live_trade_qty": self.live_trade_qty,
            "live_trade_time": self.live_trade_time,
            "live_trades_count": self.live_trades_count,
            "live_vwap": round(self.live_vwap_pv / self.live_vwap_vol, 4) if self.live_vwap_vol > 0 else None,
            "last_agg_trade_id": self.last_agg_trade_id,
        }

    def update_closed_bar(
        self,
        open_time: datetime,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> Dict[str, Any]:
        """Process one finalized chronological candle in O(1) / bounded window."""
        open_iso = open_time.isoformat()
        if self.last_open_time is not None and open_iso <= self.last_open_time:
            # Duplicate or already-processed timestamp; return latest snapshot idempotently
            return self.snapshot()

        self.bar_count += 1
        self.last_open_time = open_iso
        self.prev_close = self.last_close
        self.last_close = float(close)
        self.live_price = float(close)
        self.closes.append(float(close))

        # 1. Returns & Log Returns
        simple_ret: Optional[float] = None
        log_ret: Optional[float] = None
        if self.prev_close is not None and self.prev_close > 0:
            simple_ret = (close - self.prev_close) / self.prev_close
            log_ret = math.log(close / self.prev_close)
            self.simple_returns.append(simple_ret)
            self.log_returns.append(log_ret)

            delta = close - self.prev_close
            self.gains_14.append(max(delta, 0.0))
            self.losses_14.append(max(-delta, 0.0))

        # 2. True Range for ATR(14)
        if self.prev_close is not None:
            tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
        else:
            tr = high - low
        self.tr_14.append(tr)

        # 3. Session VWAP (UTC day reset)
        day_str = open_time.strftime("%Y-%m-%d")
        if self.vwap_utc_date != day_str:
            self.vwap_utc_date = day_str
            self.vwap_pv_sum = 0.0
            self.vwap_vol_sum = 0.0
        typical_price = (high + low + close) / 3.0
        self.vwap_pv_sum += typical_price * volume
        self.vwap_vol_sum += volume

        # 4. EMA(12) & EMA(26) & MACD(12, 26, 9) matching pandas ewm(adjust=False)
        alpha_12 = 2.0 / (12 + 1)
        alpha_26 = 2.0 / (26 + 1)
        alpha_9 = 2.0 / (9 + 1)
        if self.ema_12 is None:
            self.ema_12 = close
        else:
            self.ema_12 = alpha_12 * close + (1.0 - alpha_12) * self.ema_12

        if self.ema_26 is None:
            self.ema_26 = close
        else:
            self.ema_26 = alpha_26 * close + (1.0 - alpha_26) * self.ema_26

        if self.bar_count >= 26:
            macd_val = self.ema_12 - self.ema_26
            self.macd_valid_count += 1
            if self.macd_signal is None:
                self.macd_signal = macd_val
            else:
                self.macd_signal = alpha_9 * macd_val + (1.0 - alpha_9) * self.macd_signal

        # 5. Running Drawdown
        if self.running_peak is None or close > self.running_peak:
            self.running_peak = close
        if self.running_peak > 0:
            dd_pct = ((close - self.running_peak) / self.running_peak) * 100.0
            self.current_drawdown_pct = dd_pct
            if dd_pct < self.max_drawdown_pct:
                self.max_drawdown_pct = dd_pct

        return self.snapshot(latest_simple_return=simple_ret, latest_log_return=log_ret)

    def _sma(self, window: int) -> Optional[float]:
        if len(self.closes) < window:
            return None
        vals = list(self.closes)[-window:]
        return sum(vals) / window

    def _bollinger(self, window: int = 20, num_std: float = 2.0) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        if len(self.closes) < window:
            return None, None, None
        vals = np.array(list(self.closes)[-window:], dtype=np.float64)
        mid = float(np.mean(vals))
        std = float(np.std(vals, ddof=1))
        return mid, mid + num_std * std, mid - num_std * std

    def _rsi_14(self) -> Optional[float]:
        if len(self.gains_14) < 14:
            return None
        avg_gain = sum(self.gains_14) / 14.0
        avg_loss = sum(self.losses_14) / 14.0
        if avg_loss == 0.0:
            return 50.0 if avg_gain == 0.0 else 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _atr_14(self) -> Optional[float]:
        if len(self.tr_14) < 14:
            return None
        return sum(self.tr_14) / 14.0

    def _rolling_vol(self, window: int) -> Optional[float]:
        if len(self.simple_returns) < window:
            return None
        rets = np.array(list(self.simple_returns)[-window:], dtype=np.float64)
        std = float(np.std(rets, ddof=1))
        ann = math.sqrt(PERIODS_PER_YEAR.get(self.timeframe, 365 * 24))
        return std * ann * 100.0

    def _var_cvar(self, confidence: float = 0.95) -> Tuple[Optional[float], Optional[float]]:
        if len(self.simple_returns) < 20:
            return None, None
        rets = np.array(self.simple_returns, dtype=np.float64)
        alpha_pct = (1.0 - confidence) * 100.0
        var_val = float(np.percentile(rets, alpha_pct))
        tail = rets[rets <= var_val]
        cvar_val = float(np.mean(tail)) if len(tail) > 0 else var_val
        return var_val * 100.0, cvar_val * 100.0

    def snapshot(
        self,
        latest_simple_return: Optional[float] = None,
        latest_log_return: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Return complete current incremental analytics snapshot."""
        if latest_simple_return is None and len(self.simple_returns) > 0:
            latest_simple_return = self.simple_returns[-1]
        if latest_log_return is None and len(self.log_returns) > 0:
            latest_log_return = self.log_returns[-1]

        boll_mid, boll_up, boll_low = self._bollinger(20, 2.0)
        macd_line = (self.ema_12 - self.ema_26) if (self.bar_count >= 26 and self.ema_12 is not None and self.ema_26 is not None) else None
        macd_sig = self.macd_signal if self.macd_valid_count >= 9 else None
        macd_hist = (macd_line - macd_sig) if (macd_line is not None and macd_sig is not None) else None
        var95, cvar95 = self._var_cvar(0.95)
        var99, cvar99 = self._var_cvar(0.99)
        vwap = (self.vwap_pv_sum / self.vwap_vol_sum) if self.vwap_vol_sum > 0 else None

        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bar_count": self.bar_count,
            "last_open_time": self.last_open_time,
            "last_close": self.last_close,
            "last_agg_trade_id": self.last_agg_trade_id,
            "live_price": self.live_price,
            "live_trade_time": self.live_trade_time,
            "live_trades_count": self.live_trades_count,
            "simple_return": latest_simple_return,
            "log_return": latest_log_return,
            "sma_7": self._sma(7),
            "sma_25": self._sma(25),
            "ema_12": self.ema_12 if self.bar_count >= 12 else None,
            "ema_26": self.ema_26 if self.bar_count >= 26 else None,
            "rsi_14": self._rsi_14(),
            "macd_line": macd_line,
            "macd_signal": macd_sig,
            "macd_hist": macd_hist,
            "boll_mid": boll_mid,
            "boll_upper": boll_up,
            "boll_lower": boll_low,
            "atr_14": self._atr_14(),
            "vwap": vwap,
            "vol_7_ann_pct": self._rolling_vol(7),
            "vol_14_ann_pct": self._rolling_vol(14),
            "vol_30_ann_pct": self._rolling_vol(30),
            "var_95_pct": var95,
            "cvar_95_pct": cvar95,
            "var_99_pct": var99,
            "cvar_99_pct": cvar99,
            "running_peak": self.running_peak,
            "current_drawdown_pct": self.current_drawdown_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
        }

    def to_checkpoint(self) -> Dict[str, Any]:
        """Serialize bounded rolling state to JSON-compatible dict."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "max_bars": self.max_bars,
            "bar_count": self.bar_count,
            "last_open_time": self.last_open_time,
            "last_close": self.last_close,
            "prev_close": self.prev_close,
            "ema_12": self.ema_12,
            "ema_26": self.ema_26,
            "macd_signal": self.macd_signal,
            "macd_valid_count": self.macd_valid_count,
            "closes": list(self.closes),
            "gains_14": list(self.gains_14),
            "losses_14": list(self.losses_14),
            "tr_14": list(self.tr_14),
            "simple_returns": list(self.simple_returns),
            "log_returns": list(self.log_returns),
            "vwap_utc_date": self.vwap_utc_date,
            "vwap_pv_sum": self.vwap_pv_sum,
            "vwap_vol_sum": self.vwap_vol_sum,
            "running_peak": self.running_peak,
            "max_drawdown_pct": self.max_drawdown_pct,
            "current_drawdown_pct": self.current_drawdown_pct,
            "last_agg_trade_id": self.last_agg_trade_id,
            "live_price": self.live_price,
            "live_trade_qty": self.live_trade_qty,
            "live_trade_time": self.live_trade_time,
            "live_trades_count": self.live_trades_count,
            "live_vwap_pv": self.live_vwap_pv,
            "live_vwap_vol": self.live_vwap_vol,
        }

    @classmethod
    def from_checkpoint(cls, data: Dict[str, Any]) -> "IncrementalSymbolState":
        """Restore incremental rolling state from checkpoint JSON."""
        max_bars = int(data.get("max_bars", 300))
        raw_aid = data.get("last_agg_trade_id")
        obj = cls(
            symbol=data["symbol"],
            timeframe=data.get("timeframe", "1m"),
            max_bars=max_bars,
            bar_count=int(data.get("bar_count", 0)),
            last_open_time=data.get("last_open_time"),
            last_close=data.get("last_close"),
            prev_close=data.get("prev_close"),
            ema_12=data.get("ema_12"),
            ema_26=data.get("ema_26"),
            macd_signal=data.get("macd_signal"),
            macd_valid_count=int(data.get("macd_valid_count", 0)),
            closes=deque(data.get("closes", []), maxlen=max_bars),
            gains_14=deque(data.get("gains_14", []), maxlen=14),
            losses_14=deque(data.get("losses_14", []), maxlen=14),
            tr_14=deque(data.get("tr_14", []), maxlen=14),
            simple_returns=deque(data.get("simple_returns", []), maxlen=max_bars),
            log_returns=deque(data.get("log_returns", []), maxlen=max_bars),
            vwap_utc_date=data.get("vwap_utc_date"),
            vwap_pv_sum=float(data.get("vwap_pv_sum", 0.0)),
            vwap_vol_sum=float(data.get("vwap_vol_sum", 0.0)),
            running_peak=data.get("running_peak"),
            max_drawdown_pct=float(data.get("max_drawdown_pct", 0.0)),
            current_drawdown_pct=float(data.get("current_drawdown_pct", 0.0)),
            last_agg_trade_id=int(raw_aid) if raw_aid is not None else None,
            live_price=float(data["live_price"]) if data.get("live_price") is not None else None,
            live_trade_qty=float(data["live_trade_qty"]) if data.get("live_trade_qty") is not None else None,
            live_trade_time=data.get("live_trade_time"),
            live_trades_count=int(data.get("live_trades_count", 0)),
            live_vwap_pv=float(data.get("live_vwap_pv", 0.0)),
            live_vwap_vol=float(data.get("live_vwap_vol", 0.0)),
        )
        return obj


class IncrementalAnalyticsEngine:
    """Manages per-(symbol, timeframe) incremental state and atomic persisted checkpoints."""

    def __init__(
        self,
        checkpoint_dir: Optional[Path] = None,
        max_bars: int = 300,
        strict_checkpoints: bool = False,
    ):
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None
        self.max_bars = max_bars
        self.strict_checkpoints = strict_checkpoints
        self.states: Dict[Tuple[str, str], IncrementalSymbolState] = {}
        self.checkpoint_load_errors: int = 0
        self.last_checkpoint_error: Optional[str] = None

    def get_or_create(self, symbol: str, timeframe: str = "1m") -> IncrementalSymbolState:
        key = (symbol.upper(), timeframe.lower())
        if key not in self.states:
            if self.checkpoint_dir:
                ckpt_file = self.checkpoint_dir / f"analytics_{key[0]}_{key[1]}.json"
                if ckpt_file.exists():
                    try:
                        data = json.loads(ckpt_file.read_text(encoding="utf-8"))
                        self.states[key] = IncrementalSymbolState.from_checkpoint(data)
                        return self.states[key]
                    except Exception as exc:
                        self.checkpoint_load_errors += 1
                        self.last_checkpoint_error = f"{ckpt_file.name}: {exc}"
                        PROCESSING_FAILURES.labels(stage="analytics_checkpoint").inc()
                        logger.error(f"Corrupt analytics checkpoint {ckpt_file}: {exc}")
                        try:
                            corrupt_path = ckpt_file.with_name(f"{ckpt_file.name}.corrupt")
                            os.replace(ckpt_file, corrupt_path)
                        except OSError:
                            pass
                        if self.strict_checkpoints:
                            raise ValueError(f"Corrupt analytics checkpoint {ckpt_file.name}: {exc}") from exc
            self.states[key] = IncrementalSymbolState(symbol=key[0], timeframe=key[1], max_bars=self.max_bars)
        return self.states[key]

    def save_checkpoints(self) -> int:
        """Persist checkpoints atomically via .tmp + fsync + os.replace (REQ-DP-DEL-06)."""
        if not self.checkpoint_dir:
            return 0
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        saved = 0
        for (sym, tf), st in self.states.items():
            target = self.checkpoint_dir / f"analytics_{sym}_{tf}.json"
            tmp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
            payload = json.dumps(st.to_checkpoint()).encode("utf-8")
            try:
                with open(tmp_path, "wb") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, target)
                saved += 1
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
        return saved

    def all_snapshots(self) -> List[Dict[str, Any]]:
        return [st.snapshot() for st in self.states.values()]


def compute_batch_reference_metrics(df: pd.DataFrame, timeframe: str = "1h") -> Dict[str, Any]:
    """Independent vectorized batch reference calculation for all financial & risk metrics.

    Used both for Gold analytics and for validating mathematical parity against streaming state.
    """
    if df.empty:
        return {"count": 0}

    data = df.sort_values("open_time").reset_index(drop=True)
    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)

    simple_ret = close.pct_change()
    log_ret = np.log(close / close.shift(1))

    sma_7 = compute_sma(close, 7)
    sma_25 = compute_sma(close, 25)
    ema_12 = compute_ema(close, 12)
    ema_26 = compute_ema(close, 26)
    rsi_14 = compute_rsi(close, 14)
    macd_line, macd_sig, macd_hist = compute_macd(close)
    boll_mid, boll_up, boll_low, _ = compute_bollinger_bands(close, 20, 2.0)

    # Raw ATR(14)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr_14 = tr.rolling(window=14, min_periods=14).mean()

    # Session VWAP (UTC date grouping)
    open_dt = pd.to_datetime(data["open_time"])
    utc_day = open_dt.dt.strftime("%Y-%m-%d")
    typical_price = (high + low + close) / 3.0
    pv = typical_price * volume
    cum_pv = pv.groupby(utc_day).cumsum()
    cum_vol = volume.groupby(utc_day).cumsum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)

    ann = math.sqrt(PERIODS_PER_YEAR.get(timeframe.lower(), 365 * 24))
    vol_7 = simple_ret.rolling(7, min_periods=7).std(ddof=1) * ann * 100.0
    vol_14 = simple_ret.rolling(14, min_periods=14).std(ddof=1) * ann * 100.0
    vol_30 = simple_ret.rolling(30, min_periods=30).std(ddof=1) * ann * 100.0

    valid_rets = simple_ret.dropna().to_numpy(dtype=np.float64)
    var_95 = cvar_95 = var_99 = cvar_99 = None
    if len(valid_rets) >= 20:
        v95 = float(np.percentile(valid_rets, 5.0))
        t95 = valid_rets[valid_rets <= v95]
        var_95 = v95 * 100.0
        cvar_95 = (float(np.mean(t95)) if len(t95) > 0 else v95) * 100.0

        v99 = float(np.percentile(valid_rets, 1.0))
        t99 = valid_rets[valid_rets <= v99]
        var_99 = v99 * 100.0
        cvar_99 = (float(np.mean(t99)) if len(t99) > 0 else v99) * 100.0

    running_peak = close.cummax()
    drawdown_pct = ((close - running_peak) / running_peak.replace(0, np.nan)) * 100.0
    max_drawdown_pct = float(drawdown_pct.min()) if not drawdown_pct.empty else 0.0

    def _last_opt(series: pd.Series) -> Optional[float]:
        if series.empty:
            return None
        val = series.iloc[-1]
        return None if pd.isna(val) else float(val)

    return {
        "count": len(data),
        "last_close": float(close.iloc[-1]),
        "simple_return": _last_opt(simple_ret),
        "log_return": _last_opt(log_ret),
        "sma_7": _last_opt(sma_7),
        "sma_25": _last_opt(sma_25),
        "ema_12": _last_opt(ema_12),
        "ema_26": _last_opt(ema_26),
        "rsi_14": _last_opt(rsi_14) if len(data) >= 15 else None,
        "macd_line": _last_opt(macd_line),
        "macd_signal": _last_opt(macd_sig) if len(data) >= 34 else None,
        "macd_hist": _last_opt(macd_hist) if len(data) >= 34 else None,
        "boll_mid": _last_opt(boll_mid),
        "boll_upper": _last_opt(boll_up),
        "boll_lower": _last_opt(boll_low),
        "atr_14": _last_opt(atr_14),
        "vwap": _last_opt(vwap),
        "vol_7_ann_pct": _last_opt(vol_7),
        "vol_14_ann_pct": _last_opt(vol_14),
        "vol_30_ann_pct": _last_opt(vol_30),
        "var_95_pct": var_95,
        "cvar_95_pct": cvar_95,
        "var_99_pct": var_99,
        "cvar_99_pct": cvar_99,
        "running_peak": float(running_peak.iloc[-1]),
        "current_drawdown_pct": float(drawdown_pct.iloc[-1]),
        "max_drawdown_pct": max_drawdown_pct,
        "series": {
            "simple_return": simple_ret,
            "log_return": log_ret,
            "atr_14": atr_14,
            "vwap": vwap,
            "vol_7": vol_7,
            "vol_14": vol_14,
            "vol_30": vol_30,
            "running_peak": running_peak,
            "drawdown_pct": drawdown_pct,
        },
    }

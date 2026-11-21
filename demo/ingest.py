# Financial Multi-Source Ingestion Strategy
import websockets
import asyncio
import json

import aiohttp
from dataclasses import dataclass, field, asdict
from enum import Enum

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

from pydantic import BaseModel, Field
# Unit Definition
class Interval(str, Enum):
    MS = "ms"
    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


# Modeling
# @dataclass(frozen=True)
class Time(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    time_frame: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Token: 
    symbol: str
    time_data: Time   
    limit: Optional[int] = 1000
    timeout: Optional[int] = None


# Schemas
@dataclass(frozen=True)
class Candle:
    """Schema chuẩn hóa cho 1 cây nến OHLCV (độc lập với từng sàn)."""
    open_time: int          # Unix timestamp (ms)
    close_time: int         # Unix timestamp (ms)
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: Optional[float] = None
    trades_count: Optional[int] = None


@dataclass(frozen=True)
class IngestMetadata:
    """Thông tin ngữ cảnh của batch dữ liệu vừa ingest."""
    source: str             # Ví dụ: "binance_public"
    symbol: str             # Ví dụ: "BTCUSDT"
    time_frame: str         # Ví dụ: "1m", "5m"
    interval_unit: str      # Ví dụ: "minutes"
    interval_value: int
    count: int
    ingested_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

@dataclass(frozen=True)
class IngestResult:
    """Schema đầu ra tổng thể trả về từ hàm ingest/fetch_klines."""
    metadata: IngestMetadata
    candles: List[Candle] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển sang dict để ghi vào DB hoặc trả về API."""
        return asdict(self)

    def to_json(self) -> str:
        """Chuyển sang JSON string để đẩy vào Kafka/Redis."""
        return json.dumps(self.to_dict())


# Abstraction
class MarketDataConnector(ABC): 
    
    @abstractmethod
    def health_check(self): 
        pass

    @abstractmethod
    async def fetch_klines(self, token: Token) -> List: 
        pass

    @abstractmethod
    def _validate(self): 
        pass

class BaseCandleMapper(ABC):
    @abstractmethod
    def map_many(self, raw_data: List[Any]) -> List[Candle]:
        pass

class BaseIntervalCalculator(ABC):
    @abstractmethod
    def calculate(self, time_data: Time, interval: Interval = Interval.SECONDS) -> int:
        pass

# Binance Connector
class BinanceConnector(MarketDataConnector): 
    def __init__(self, 
                 calculator: BaseIntervalCalculator, 
                 base_url: str = "https://api.binance.com"): 
        self.calculator = calculator
        self.base_url = base_url.rstrip("/")
        self.mapper = BinanceKlineMapper()

    def health_check(self) -> bool: 
        pass 
    
    def _validate(self, token: Token, interval: Interval) -> None:
        """Kiểm tra toàn bộ tham số đầu vào trước khi gọi API ingest."""
        # 1. Kiểm tra kiểu dữ liệu tổng quát
        if not isinstance(token, Token):
            raise TypeError(f"token phải có kiểu Token, nhận được: {type(token).__name__}")

        if not isinstance(interval, Interval):
            raise TypeError(f"interval phải có kiểu Interval, nhận được: {type(interval).__name__}")

        # 2. Kiểm tra symbol
        if not isinstance(token.symbol, str) or not token.symbol.strip():
            raise ValueError("token.symbol phải là chuỗi không rỗng (ví dụ: 'BTCUSDT').")

        # 3. Kiểm tra time_data
        time_data = token.time_data
        if not isinstance(time_data, Time):
            raise TypeError(f"token.time_data phải có kiểu Time, nhận được: {type(time_data).__name__}")

        # 4. Kiểm tra start_time và end_time
        start = time_data.start_time
        end = time_data.end_time

        if start is not None and not isinstance(start, datetime):
            raise TypeError("start_time phải có kiểu datetime hoặc None.")
        if end is not None and not isinstance(end, datetime):
            raise TypeError("end_time phải có kiểu datetime hoặc None.")

        if start is not None and end is not None:
            # Tránh lỗi TypeError khi so sánh datetime có timezone (aware) và không có timezone (naive)
            if (start.tzinfo is None) != (end.tzinfo is None):
                raise ValueError("start_time và end_time phải đồng nhất về timezone (cùng có hoặc cùng không có tzinfo).")
            if end < start:
                raise ValueError("end_time phải lớn hơn hoặc bằng start_time.")
        

    async def fetch_klines (self, 
                            token: Token, 
                            interval: Interval = Interval.MINUTES ) -> List:
        self._validate(token, interval)
        symbol = token.symbol
        time_data = token.time_data
        limit = token.limit

        interval_value: int = self.calculator.calculate(time_data, interval)
        results: List[Dict[str, Any]] = []

        start_ms = int(time_data.start_time.timestamp() * 1000)
        end_ms = int(time_data.end_time.timestamp() * 1000)

        async with aiohttp.ClientSession() as session:
            for tf in time_data.time_frame or ["1m"]:
                params = {
                    "symbol": symbol.upper(),
                    "interval": tf,          # Ví dụ: "1m", "5m", "1h"
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": limit,  # Binance giới hạn tối đa 1000 nến/request
                }
                params = {k: v for k, v in params.items() if v is not None}

                async with session.get(f"{self.base_url}/api/v3/klines", params=params, timeout=10) as resp:
                    resp.raise_for_status()
                    raw_klines = await resp.json()

                candles = self.mapper.map_many(raw_klines)
                metadata = IngestMetadata(
                    source="binance_public",
                    symbol=token.symbol.upper(),
                    time_frame=tf,
                    interval_unit=interval.value,
                    interval_value=interval_value,
                    count=len(candles),
                )
                results.append(IngestResult(metadata=metadata, candles=candles))

        return results


class BinanceKlineMapper(BaseCandleMapper):
    """Chuyển mảng thô từ Binance /api/v3/klines sang List[Candle]."""

    def map_many(self, raw_data: List[List[Any]]) -> List[Candle]:
        return [
            Candle(
                open_time=int(k[0]),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                close_time=int(k[6]),
                quote_volume=float(k[7]),
                trades_count=int(k[8]),
            )
            for k in raw_data
        ]


#ByBit Connector
BYBIT_TIMEFRAME_MAP: Dict[str, str] = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "D",
    "1w": "W",
    "1M": "M",
}

class BybitKlineMapper(BaseCandleMapper):

    def map_many(self, raw_data: List[List[Any]]) -> List[Candle]:
        return [
            Candle(
                open_time=int(k[0]),
                close_time=int(k[0]),  # Bybit kline API không trả về close_time
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                quote_volume=float(k[6]),  # turnover
                trades_count=None,         # Bybit kline API không trả về trades_count
            )
            for k in reversed(raw_data)
        ]

class ByBitConnector(MarketDataConnector): 
    def __init__(
        self,
        calculator: BaseIntervalCalculator,
        mapper: BaseCandleMapper = BybitKlineMapper(),
        category: str = "spot",
        base_url: str = "https://api.bybit.com",
    ):
        self.base_url = base_url.rstrip("/")
        self.calculator = calculator
        self.mapper = mapper
        self.category = category
    
    def health_check(self): 
        pass

    def _validate(self, token: Token, interval: Interval) -> None:
        if not isinstance(token, Token):
            raise TypeError(f"token phải có kiểu Token, nhận được: {type(token).__name__}")
        if not isinstance(interval, Interval):
            raise TypeError(f"interval phải có kiểu Interval, nhận được: {type(interval).__name__}")
        if not isinstance(token.symbol, str) or not token.symbol.strip():
            raise ValueError("token.symbol phải là chuỗi không rỗng (ví dụ: 'BTCUSDT').")

        time_data = token.time_data
        if not isinstance(time_data, Time):
            raise TypeError("token.time_data phải có kiểu Time.")

        start, end = time_data.start_time, time_data.end_time
        if start is not None and end is not None:
            if (start.tzinfo is None) != (end.tzinfo is None):
                raise ValueError("start_time và end_time phải đồng nhất về timezone.")
            if end < start:
                raise ValueError("end_time phải lớn hơn hoặc bằng start_time.")

        if not time_data.time_frame:
            raise ValueError("time_frame không được rỗng.")

        # for tf in time_data.time_frame:
        #     if tf not in BYBIT_TIMEFRAME_MAP:
        #         raise ValueError(
        #             f"time_frame '{tf}' không được Bybit hỗ trợ. "
        #             f"Các giá trị hợp lệ: {list(BYBIT_TIMEFRAME_MAP.keys())}"
                # )

    async def fetch_klines(
        self,
        token: Token,
        interval: Interval = Interval.MINUTES,
    ) -> List[IngestResult]:
        self._validate(token, interval)

        time_data = token.time_data
        interval_value: int = self.calculator.calculate(time_data, interval)
        results: List[IngestResult] = []

        start_ms = int(time_data.start_time.timestamp() * 1000) if time_data.start_time else None
        end_ms = int(time_data.end_time.timestamp() * 1000) if time_data.end_time else None

        async with aiohttp.ClientSession() as session:
            for tf in time_data.time_frame:
                params = {
                    "category": self.category,
                    "symbol": token.symbol.upper(),
                    "interval": BYBIT_TIMEFRAME_MAP[tf],
                    "start": start_ms,
                    "end": end_ms,
                    "limit": min(max(interval_value, 1), 1000),
                }
                # Lọc bỏ None để tránh lỗi yarl của aiohttp
                params = {k: v for k, v in params.items() if v is not None}

                async with session.get(f"{self.base_url}/v5/market/kline", params=params, timeout=10) as resp:
                    resp.raise_for_status()
                    payload = await resp.json()

                # Kiểm tra mã lỗi nghiệp vụ của Bybit
                if payload.get("retCode") != 0:
                    raise RuntimeError(
                        f"Bybit API error (code={payload.get('retCode')}): {payload.get('retMsg')}"
                    )

                raw_klines = payload.get("result", {}).get("list", [])
                candles = self.mapper.map_many(raw_klines)

                metadata = IngestMetadata(
                    source=f"bybit_public_{self.category}",
                    symbol=token.symbol.upper(),
                    time_frame=tf,
                    interval_unit=interval.value,
                    interval_value=interval_value,
                    count=len(candles),
                )
                results.append(IngestResult(metadata=metadata, candles=candles))

        return results

# Job
class MarketIngestionJob(ABC): 
    def __init__(self, repository): 
        self.repository = repository

    @abstractmethod
    def create_connector(self) -> MarketDataConnector: 
        pass

    def run(self): 
        pass




# Processing 
class StandardIntervalCalculator(BaseIntervalCalculator):
    _MULTIPLIERS: Dict[Interval, float] = {
        Interval.MS: 1000,
        Interval.SECONDS: 1,
        Interval.MINUTES: 1 / 60,
        Interval.HOURS: 1 / 3600,
        Interval.DAYS: 1 / 86400,
    }

    def _validate(self, time_data: Time, interval: Interval) -> None:
        if time_data.start_time is None or time_data.end_time is None:
            raise ValueError("Cả start_time và end_time đều phải có giá trị.")
        if time_data.end_time < time_data.start_time:
            raise ValueError("end_time phải lớn hơn hoặc bằng start_time.")
        if not isinstance(interval, Interval):
            raise TypeError(f"interval phải có kiểu Interval, nhận được: {type(interval).__name__}")

    def calculate(self, time_data: Time, interval: Interval = Interval.SECONDS) -> int:
        self._validate(time_data, interval)
        diff_seconds = (time_data.end_time - time_data.start_time).total_seconds()
        return int(diff_seconds * self._MULTIPLIERS[interval])





import asyncio
from datetime import datetime, timezone
from ingest import Time, Interval, Token
from ingest import BaseIntervalCalculator, StandardIntervalCalculator

from ingest import BinanceConnector
async def main():
    time_range = Time(
        start_time=datetime(2026, 11, 20, 2, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 11, 20, 2, 10, 0, tzinfo=timezone.utc),
        time_frame=["1m", "5m"],
    )
    token = Token(
        symbol="BTCUSDT",
        time_data=time_range,
    )
    calculator = StandardIntervalCalculator()
    ingestor = BinanceConnector(calculator=calculator)

    data = await ingestor.fetch_klines(token= token, interval= Interval.MINUTES)

    for item in data:
        print(
            f"[{item['source']}] {item['symbol']} | TF: {item['time_frame']} | "
            f"Interval: {item['interval_value']} {item['interval_unit']} | "
            f"Candles: {item['count']}"
        )
        if item["data"]:
            print("  Sample:", item["data"][0])

if __name__ == "__main__":
    asyncio.run(main())


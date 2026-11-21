import asyncio
from datetime import datetime, timezone
from ingest import Time, Interval, Token
from ingest import BaseIntervalCalculator, StandardIntervalCalculator
from typing import List
from ingest import BinanceConnector, ByBitConnector
async def main():
    token = Token(
        symbol="BTCUSDT",
        time_data=Time(
            start_time=datetime(2026, 11, 20, 2, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 11, 20, 2, 10, 0, tzinfo=timezone.utc),
            time_frame=["1m", "5m"],
        ),
    )

    calculator = StandardIntervalCalculator()
    ingestors: List[BaseIntervalCalculator] = [
        BinanceConnector(calculator=calculator),
        ByBitConnector(calculator=calculator, category="spot"),
    ]

    # Chạy song song tất cả các sàn
    all_batches = await asyncio.gather(
        *[ingestor.fetch_klines(token=token, interval=Interval.MINUTES) for ingestor in ingestors]
    )

    for batch in all_batches:
        for res in batch:
            print(
                f"[{res.metadata.source}] {res.metadata.symbol} | "
                f"TF: {res.metadata.time_frame} | Count: {res.metadata.count}"
            )

asyncio.run(main())
    

if __name__ == "__main__":
    asyncio.run(main())


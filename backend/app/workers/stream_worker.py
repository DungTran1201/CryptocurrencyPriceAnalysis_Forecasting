"""Independent Streaming & Medallion Consumer Worker (Profile STANDARD / EXTENDED)."""

import asyncio
import signal

from backend.app.core.config import settings
from backend.app.core.database import init_db
from backend.app.core.logging import get_logger
from backend.app.streaming.runtime import StreamPlatformRuntime

logger = get_logger("StreamWorker")


async def run_stream_worker() -> None:
    """Run independent ingestion + durable NATS JetStream consumers until stopped."""
    await init_db()
    runtime = StreamPlatformRuntime()
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

    logger.info(f"Starting standalone StreamWorker [profile={settings.profile.value}]...")
    await runtime.start(start_ingestor=True, start_consumer=True)
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runtime.stop()
        logger.info("Standalone StreamWorker exited cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(run_stream_worker())
    except KeyboardInterrupt:
        logger.info("StreamWorker interrupted.")


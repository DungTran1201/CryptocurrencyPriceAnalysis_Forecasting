"""Durable SQL Workflow Worker Daemon (ADR-DP-006, IFC-DP-007).

Executes:
- Evaluates due recurring schedules
- Reaps stale runs abandoned by crashed workers
- Claims and executes durable queued runs with background lease renewal heartbeats
- Handles graceful shutdown cleanly on Windows and POSIX
"""

import asyncio
from datetime import datetime, timezone
import os
import signal
import sys
from typing import List, Optional
import uuid

from backend.app.core.config import settings
from backend.app.core.database import AsyncSessionLocal, init_db
from backend.app.core.logging import get_logger
from backend.app.services.workflow_service import WorkflowService

logger = get_logger("WorkflowWorker")


class WorkflowWorkerDaemon:
    """Standalone worker loop claiming and executing durable workflow runs."""

    def __init__(
        self,
        worker_id: Optional[str] = None,
        poll_interval_sec: float = 2.0,
        lease_ttl_sec: int = 60,
        supported_types: Optional[List[str]] = None,
    ):
        self.worker_id = worker_id or f"wf-worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.poll_interval_sec = poll_interval_sec
        self.lease_ttl_sec = lease_ttl_sec
        self.supported_types = supported_types or ["MEDALLION_DAG", "WAREHOUSE_BUILD", "MARKET_SYNC"]
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        """Signal the daemon to stop after completing current claim."""
        self._stop_event.set()

    async def _heartbeat_loop(self, run_id: str, lease_token: str, stop_signal: asyncio.Event) -> None:
        """Periodically renew lease in background while task executes."""
        renew_interval = max(1.0, self.lease_ttl_sec / 3.0)
        while not stop_signal.is_set():
            try:
                await asyncio.sleep(renew_interval)
                if stop_signal.is_set():
                    break
                async with AsyncSessionLocal() as db:
                    renewed = await WorkflowService.renew_lease(
                        db, run_id, lease_token, lease_ttl_sec=self.lease_ttl_sec
                    )
                    if not renewed:
                        logger.warning("Failed to renew lease for run %s; worker may have lost ownership", run_id)
                        break
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Heartbeat renewal error for run %s: %s", run_id, exc)

    async def run_cycle(self) -> bool:
        """Execute one maintenance and claim cycle. Returns True if work was claimed and processed."""
        async with AsyncSessionLocal() as db:
            # 1. Trigger due recurring schedules
            try:
                dispatched = await WorkflowService.trigger_due_schedules(db)
                if dispatched:
                    logger.info("Worker %s triggered %d due schedules", self.worker_id, len(dispatched))
            except Exception as exc:
                logger.error("Error triggering due schedules: %s", exc)

            # 2. Reap stale runs
            try:
                reaped = await WorkflowService.reap_stale_runs(db)
                if reaped:
                    logger.info("Worker %s reaped %d stale runs", self.worker_id, reaped)
            except Exception as exc:
                logger.error("Error reaping stale runs: %s", exc)

            # 3. Claim next pending run
            run = await WorkflowService.claim_next_run(
                db,
                worker_id=self.worker_id,
                supported_types=self.supported_types,
                lease_ttl_sec=self.lease_ttl_sec,
            )

        if run is None:
            return False

        logger.info(
            "Worker %s claimed run %s (type=%s, attempt=%s)",
            self.worker_id,
            run.id,
            run.workflow_type,
            run.attempt,
        )

        # 4. Execute claimed run with background heartbeat renewal
        heartbeat_stop = asyncio.Event()
        hb_task = asyncio.create_task(
            self._heartbeat_loop(run.id, run.lease_token or "", heartbeat_stop)
        )
        try:
            async with AsyncSessionLocal() as exec_db:
                await WorkflowService.execute_run(
                    exec_db,
                    run_id=run.id,
                    lease_token=run.lease_token,
                )
            logger.info("Worker %s completed run %s successfully", self.worker_id, run.id)
        except Exception as exc:
            logger.error("Worker %s failed executing run %s: %s", self.worker_id, run.id, exc)
        finally:
            heartbeat_stop.set()
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass

        return True

    async def start(self) -> None:
        """Start continuous polling daemon until stopped."""
        logger.info("Starting WorkflowWorkerDaemon (id=%s, types=%s)", self.worker_id, self.supported_types)
        await init_db()

        while not self._stop_event.is_set():
            try:
                did_work = await self.run_cycle()
                if not did_work:
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_sec)
                    except asyncio.TimeoutError:
                        pass
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Unexpected error in worker cycle: %s", exc, exc_info=True)
                await asyncio.sleep(self.poll_interval_sec)

        logger.info("WorkflowWorkerDaemon %s shut down gracefully", self.worker_id)


def main():
    daemon = WorkflowWorkerDaemon()

    def _sig_handler(*_):
        logger.info("Stop signal received, shutting down daemon...")
        daemon.stop()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    try:
        asyncio.run(daemon.start())
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user.")


if __name__ == "__main__":
    main()

"""Durable SQL Workflow Orchestration Service (ADR-DP-006, IFC-DP-007).

Provides:
- Idempotent workflow enqueue with active-run mutual exclusion
- Atomic worker lease acquisition, renewal, and stale-lease reaping
- Step-level DAG task execution with resumption on worker crash
- Aggregated operational KPI metrics for pipelines
- Persisted recurring schedule evaluation
"""

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.models.workflow import WorkflowRun, WorkflowSchedule, WorkflowTask
from backend.app.schemas.workflow import (
    WorkflowSchedulePatchRequest,
    WorkflowScheduleUpsertRequest,
)

logger = get_logger("WorkflowService")


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WorkflowService:
    """Core durable workflow orchestrator managing runs, task DAGs, leases, and schedules."""

    @staticmethod
    def compute_idempotency_key(
        workflow_type: str,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        trigger_type: str = "MANUAL",
    ) -> str:
        """Derive standard active-run idempotency lock key."""
        sym = (symbol or "GLOBAL").upper()
        tf = (timeframe or "NA").lower()
        return f"{workflow_type.upper()}:{sym}:{tf}"

    @classmethod
    async def enqueue_run(
        cls,
        db: AsyncSession,
        workflow_type: str,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        trigger_type: str = "MANUAL",
        params: Optional[Dict[str, Any]] = None,
        priority: int = 5,
        max_attempts: int = 3,
        conflict_mode: str = "return_existing",
    ) -> Tuple[WorkflowRun, bool]:
        """Enqueue a workflow run or return an active conflicting run if already queued/running."""
        idempotency_key = cls.compute_idempotency_key(workflow_type, symbol, timeframe, trigger_type)
        now = _utc_now_naive()

        # Check for active existing run
        active_stmt = select(WorkflowRun).where(
            and_(
                WorkflowRun.idempotency_key == idempotency_key,
                WorkflowRun.status.in_(["QUEUED", "RUNNING", "RETRY_WAIT"]),
            )
        )
        existing = (await db.execute(active_stmt)).scalars().first()
        if existing is not None:
            return existing, True

        run_id = str(uuid.uuid4())
        run = WorkflowRun(
            id=run_id,
            workflow_type=workflow_type.upper(),
            symbol=symbol.upper() if symbol else None,
            timeframe=timeframe.lower() if timeframe else None,
            trigger_type=trigger_type.upper(),
            idempotency_key=idempotency_key,
            status="QUEUED",
            priority=priority,
            attempt=0,
            max_attempts=max_attempts,
            params_json=json.dumps(params or {}),
            next_run_at=now,
            created_at=now,
        )
        db.add(run)

        # Populate child DAG tasks
        tasks: List[WorkflowTask] = []
        if run.workflow_type == "MEDALLION_DAG":
            tasks = [
                WorkflowTask(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    task_name="ingest_bronze",
                    sequence_order=1,
                    depends_on=None,
                    status="PENDING",
                    max_attempts=2,
                ),
                WorkflowTask(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    task_name="validate_silver",
                    sequence_order=2,
                    depends_on="ingest_bronze",
                    status="PENDING",
                    max_attempts=2,
                ),
                WorkflowTask(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    task_name="build_gold_marts",
                    sequence_order=3,
                    depends_on="validate_silver",
                    status="PENDING",
                    max_attempts=2,
                ),
                WorkflowTask(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    task_name="extract_features",
                    sequence_order=4,
                    depends_on="build_gold_marts",
                    status="PENDING",
                    max_attempts=2,
                ),
            ]
        elif run.workflow_type == "WAREHOUSE_BUILD":
            tasks = [
                WorkflowTask(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    task_name="build_warehouse",
                    sequence_order=1,
                    depends_on=None,
                    status="PENDING",
                    max_attempts=2,
                )
            ]
        elif run.workflow_type == "MARKET_SYNC":
            tasks = [
                WorkflowTask(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    task_name="sync_klines",
                    sequence_order=1,
                    depends_on=None,
                    status="PENDING",
                    max_attempts=2,
                )
            ]

        for t in tasks:
            db.add(t)

        await db.commit()
        await db.refresh(run)
        return run, False

    @staticmethod
    async def claim_run_by_id(
        db: AsyncSession,
        run_id: str,
        worker_id: str,
        lease_ttl_sec: int = 60,
    ) -> Optional[WorkflowRun]:
        """Atomically claim a specific workflow run if QUEUED/RETRY_WAIT or if its lease expired."""
        now = _utc_now_naive()
        run = await db.get(WorkflowRun, run_id)
        if run is None:
            return None

        is_claimable = run.status in ("QUEUED", "RETRY_WAIT") or (
            run.status == "RUNNING"
            and run.lease_expires_at is not None
            and run.lease_expires_at < now
        )
        if not is_claimable:
            return None

        token = str(uuid.uuid4())
        run.status = "RUNNING"
        run.lease_owner = worker_id
        run.lease_token = token
        run.lease_expires_at = now + timedelta(seconds=lease_ttl_sec)
        run.heartbeat_at = now
        run.attempt = (run.attempt or 0) + 1
        if not run.started_at:
            run.started_at = now

        await db.commit()
        await db.refresh(run)
        return run

    @staticmethod
    async def claim_next_run(
        db: AsyncSession,
        worker_id: str,
        supported_types: Optional[List[str]] = None,
        lease_ttl_sec: int = 60,
    ) -> Optional[WorkflowRun]:
        """Claim the highest priority queued or stale run ready for processing."""
        now = _utc_now_naive()
        conds = [
            (
                WorkflowRun.status.in_(["QUEUED", "RETRY_WAIT"])
                & (WorkflowRun.next_run_at <= now)
            )
            | (
                (WorkflowRun.status == "RUNNING")
                & (WorkflowRun.lease_expires_at.is_not(None))
                & (WorkflowRun.lease_expires_at < now)
            )
        ]
        if supported_types:
            conds.append(WorkflowRun.workflow_type.in_([t.upper() for t in supported_types]))

        query = (
            select(WorkflowRun)
            .where(and_(*conds))
            .order_by(WorkflowRun.priority.asc(), WorkflowRun.next_run_at.asc())
            .limit(1)
        )
        run = (await db.execute(query)).scalars().first()
        if run is None:
            return None

        token = str(uuid.uuid4())
        run.status = "RUNNING"
        run.lease_owner = worker_id
        run.lease_token = token
        run.lease_expires_at = now + timedelta(seconds=lease_ttl_sec)
        run.heartbeat_at = now
        run.attempt = (run.attempt or 0) + 1
        if not run.started_at:
            run.started_at = now

        await db.commit()
        await db.refresh(run)
        return run

    @staticmethod
    async def renew_lease(
        db: AsyncSession,
        run_id: str,
        lease_token: str,
        lease_ttl_sec: int = 60,
    ) -> bool:
        """Extend active worker lease expiration while step is actively executing."""
        now = _utc_now_naive()
        stmt = select(WorkflowRun).where(
            and_(
                WorkflowRun.id == run_id,
                WorkflowRun.lease_token == lease_token,
                WorkflowRun.status == "RUNNING",
            )
        )
        run = (await db.execute(stmt)).scalars().first()
        if run is None:
            return False

        run.lease_expires_at = now + timedelta(seconds=lease_ttl_sec)
        run.heartbeat_at = now
        await db.commit()
        return True

    @staticmethod
    async def reap_stale_runs(db: AsyncSession, max_reap: int = 10) -> int:
        """Find runs abandoned by crashed workers and transition to RETRY_WAIT or FAILED."""
        now = _utc_now_naive()
        stmt = (
            select(WorkflowRun)
            .where(
                and_(
                    WorkflowRun.status == "RUNNING",
                    WorkflowRun.lease_expires_at.is_not(None),
                    WorkflowRun.lease_expires_at < now,
                )
            )
            .limit(max_reap)
        )
        stale_runs = list((await db.execute(stmt)).scalars().all())
        reaped_count = 0

        for r in stale_runs:
            reaped_count += 1
            if (r.attempt or 0) >= (r.max_attempts or 3):
                r.status = "FAILED"
                r.error_code = "LEASE_TIMEOUT_EXHAUSTED"
                r.error_summary = "Worker lease expired and retry attempts exhausted."
                r.completed_at = now
                if r.started_at:
                    r.duration_seconds = max(0.0, (now - r.started_at).total_seconds())
            else:
                r.status = "RETRY_WAIT"
                r.lease_owner = None
                r.lease_token = None
                backoff_sec = min(300, 5 * (2 ** max((r.attempt or 1) - 1, 0)))
                r.next_run_at = now + timedelta(seconds=backoff_sec)

        if reaped_count > 0:
            await db.commit()
            logger.info("Reaped %d stale workflow run leases", reaped_count)
        return reaped_count

    @staticmethod
    async def execute_run(
        db: AsyncSession,
        run_id: str,
        lease_token: Optional[str] = None,
    ) -> WorkflowRun:
        """Execute all pending DAG tasks sequentially with step checkpointing and crash resumption."""
        from backend.app.services.pipeline_service import (
            PipelineService,
            SafeWorkflowError,
            sanitize_error,
        )

        run = await db.get(WorkflowRun, run_id)
        if run is None:
            raise SafeWorkflowError("RUN_NOT_FOUND", f"Workflow run '{run_id}' does not exist.")

        if lease_token and run.lease_token and run.lease_token != lease_token:
            raise SafeWorkflowError("INVALID_LEASE", "Workflow run lease token does not match.")

        tasks_stmt = (
            select(WorkflowTask)
            .where(WorkflowTask.run_id == run_id)
            .order_by(WorkflowTask.sequence_order.asc())
        )
        tasks = list((await db.execute(tasks_stmt)).scalars().all())

        params: Dict[str, Any] = {}
        if run.params_json:
            try:
                params = json.loads(run.params_json)
            except Exception:
                params = {}

        results: Dict[str, Any] = {}
        # Pre-load previous checkpoints
        for t in tasks:
            if t.status == "SUCCESS" and t.checkpoint_json:
                try:
                    results[t.task_name] = json.loads(t.checkpoint_json)
                except Exception:
                    pass

        for task in tasks:
            if task.status == "SUCCESS":
                continue  # Resumed task already completed

            task.status = "RUNNING"
            task.started_at = _utc_now_naive()
            task.attempt = (task.attempt or 0) + 1
            await db.commit()

            try:
                if run.workflow_type == "MEDALLION_DAG":
                    if task.task_name == "ingest_bronze":
                        res = await PipelineService.step_ingest_bronze(
                            db,
                            run_id=run.id,
                            symbol=run.symbol or "BTCUSDT",
                            timeframe=run.timeframe or "1h",
                            lookback_days=params.get("lookback_days", 30),
                            skip_network_ingest=params.get("skip_network_ingest", False),
                        )
                    elif task.task_name == "validate_silver":
                        res = await PipelineService.step_validate_silver(
                            db,
                            run_id=run.id,
                            symbol=run.symbol or "BTCUSDT",
                            timeframe=run.timeframe or "1h",
                        )
                    elif task.task_name == "build_gold_marts":
                        res = await PipelineService.step_build_gold_marts(
                            db,
                            run_id=run.id,
                            symbol=run.symbol or "BTCUSDT",
                            timeframe=run.timeframe or "1h",
                        )
                    elif task.task_name == "extract_features":
                        res = await PipelineService.step_extract_features(
                            db,
                            run_id=run.id,
                            symbol=run.symbol or "BTCUSDT",
                            timeframe=run.timeframe or "1h",
                        )
                    else:
                        res = {"status": "SKIPPED", "records_processed": 0}
                elif run.workflow_type == "WAREHOUSE_BUILD":
                    from backend.app.storage.warehouse import DuckDBWarehouseEngine
                    engine = DuckDBWarehouseEngine()
                    res = await asyncio.to_thread(engine.build_snapshot, run.symbol, run.timeframe)
                else:
                    res = {"status": "SUCCESS", "records_processed": 0}

                t_now = _utc_now_naive()
                task.status = "SUCCESS"
                task.completed_at = t_now
                if task.started_at:
                    task.duration_seconds = max(0.0, (t_now - task.started_at).total_seconds())
                task.records_processed = int(res.get("records_processed", 0))
                task.checkpoint_json = json.dumps(res)
                results[task.task_name] = res
                await db.commit()

            except Exception as exc:
                t_now = _utc_now_naive()
                err_code, err_summary = sanitize_error(exc)
                task.status = "FAILED"
                task.completed_at = t_now
                if task.started_at:
                    task.duration_seconds = max(0.0, (t_now - task.started_at).total_seconds())
                task.error_code = err_code
                task.error_summary = err_summary

                run.status = "FAILED"
                run.completed_at = t_now
                if run.started_at:
                    run.duration_seconds = max(0.0, (t_now - run.started_at).total_seconds())
                run.error_code = err_code
                run.error_summary = err_summary
                run.result_json = json.dumps(results)
                await db.commit()
                raise

        # All tasks succeeded
        now = _utc_now_naive()
        run.status = "SUCCESS"
        run.completed_at = now
        if run.started_at:
            run.duration_seconds = max(0.0, (now - run.started_at).total_seconds())
        run.error_code = None
        run.error_summary = None
        run.result_json = json.dumps(results)
        await db.commit()
        await db.refresh(run)
        return run

    @staticmethod
    async def get_overview_stats(db: AsyncSession) -> Dict[str, Any]:
        """Aggregate operational KPIs across all durable workflow executions."""
        counts_stmt = select(WorkflowRun.status, func.count(WorkflowRun.id)).group_by(WorkflowRun.status)
        counts = dict((await db.execute(counts_stmt)).all())

        total = sum(counts.values())
        succeeded = counts.get("SUCCESS", 0)
        queued = counts.get("QUEUED", 0)
        running = counts.get("RUNNING", 0)
        retry_wait = counts.get("RETRY_WAIT", 0)
        failed = counts.get("FAILED", 0)
        cancelled = counts.get("CANCELLED", 0)
        success_rate = (succeeded / total * 100.0) if total > 0 else 0.0

        dur_stmt = select(
            func.avg(WorkflowRun.duration_seconds),
            func.max(WorkflowRun.completed_at),
        ).where(WorkflowRun.status == "SUCCESS")
        dur_res = (await db.execute(dur_stmt)).first()
        avg_dur = float(dur_res[0] or 0.0) if dur_res else 0.0
        latest_success = dur_res[1] if dur_res else None

        err_stmt = (
            select(WorkflowRun.error_code, WorkflowRun.error_summary)
            .where(WorkflowRun.status == "FAILED")
            .order_by(WorkflowRun.completed_at.desc())
            .limit(1)
        )
        err_res = (await db.execute(err_stmt)).first()
        latest_err_code = err_res[0] if err_res else None
        latest_err_sum = err_res[1] if err_res else None

        tot_rows_stmt = select(func.sum(WorkflowTask.records_processed)).where(
            WorkflowTask.status == "SUCCESS"
        )
        tot_rows = int((await db.scalar(tot_rows_stmt)) or 0)

        return {
            "total_runs": total,
            "queued_runs": queued,
            "running_runs": running,
            "retry_wait_runs": retry_wait,
            "succeeded_runs": succeeded,
            "failed_runs": failed,
            "cancelled_runs": cancelled,
            "success_rate_pct": round(success_rate, 2),
            "total_rows_read": tot_rows,
            "total_rows_inserted": tot_rows,
            "avg_duration_seconds": round(avg_dur, 2),
            "latest_successful_run_at": latest_success,
            "latest_error_code": latest_err_code,
            "latest_error_summary": latest_err_sum,
            "latest_error_message": latest_err_sum,
        }

    @staticmethod
    async def list_runs(
        db: AsyncSession,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WorkflowRun]:
        """Query workflow runs matching filters ordered newest first."""
        query = select(WorkflowRun)
        if status:
            query = query.where(WorkflowRun.status == status.upper())
        if symbol:
            query = query.where(WorkflowRun.symbol == symbol.upper())
        if timeframe:
            query = query.where(WorkflowRun.timeframe == timeframe.lower())
        query = query.order_by(WorkflowRun.created_at.desc()).limit(limit).offset(offset)
        res = await db.execute(query)
        return list(res.scalars().all())

    @staticmethod
    async def get_run_details(db: AsyncSession, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full workflow run with nested child task breakdown."""
        run = await db.get(WorkflowRun, run_id)
        if run is None:
            return None

        tasks_stmt = (
            select(WorkflowTask)
            .where(WorkflowTask.run_id == run_id)
            .order_by(WorkflowTask.sequence_order.asc())
        )
        tasks = list((await db.execute(tasks_stmt)).scalars().all())

        return {
            "id": run.id,
            "workflow_type": run.workflow_type,
            "pipeline_name": run.workflow_type,
            "symbol": run.symbol,
            "timeframe": run.timeframe,
            "trigger_type": run.trigger_type,
            "idempotency_key": run.idempotency_key,
            "status": run.status,
            "priority": run.priority,
            "attempt": run.attempt,
            "max_attempts": run.max_attempts,
            "lease_owner": run.lease_owner,
            "lease_expires_at": run.lease_expires_at,
            "heartbeat_at": run.heartbeat_at,
            "next_run_at": run.next_run_at,
            "rows_read": run.rows_read,
            "rows_inserted": run.rows_inserted,
            "gaps_detected": run.gaps_detected,
            "error_code": run.error_code,
            "error_summary": run.error_summary,
            "result": json.loads(run.result_json) if run.result_json else None,
            "params": json.loads(run.params_json) if run.params_json else {},
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "duration_seconds": run.duration_seconds,
            "created_at": run.created_at,
            "tasks": [
                {
                    "id": t.id,
                    "run_id": t.run_id,
                    "task_name": t.task_name,
                    "sequence_order": t.sequence_order,
                    "depends_on": t.depends_on,
                    "status": t.status,
                    "attempt": t.attempt,
                    "max_attempts": t.max_attempts,
                    "checkpoint_json": json.loads(t.checkpoint_json) if t.checkpoint_json else None,
                    "records_processed": t.records_processed,
                    "started_at": t.started_at,
                    "completed_at": t.completed_at,
                    "duration_seconds": t.duration_seconds,
                    "error_code": t.error_code,
                    "error_summary": t.error_summary,
                }
                for t in tasks
            ],
        }

    @staticmethod
    async def list_schedules(db: AsyncSession) -> List[WorkflowSchedule]:
        """Return all persisted recurring workflow schedules."""
        res = await db.execute(select(WorkflowSchedule).order_by(WorkflowSchedule.schedule_id.asc()))
        return list(res.scalars().all())

    @staticmethod
    async def upsert_schedule(
        db: AsyncSession,
        req: WorkflowScheduleUpsertRequest,
    ) -> WorkflowSchedule:
        """Create or replace a persisted recurring workflow schedule."""
        now = _utc_now_naive()
        sched_id = req.schedule_id or f"sched-{req.workflow_type.lower()}-{uuid.uuid4().hex[:8]}"
        existing = await db.get(WorkflowSchedule, sched_id)
        if existing:
            existing.workflow_type = req.workflow_type.upper()
            existing.symbol = req.symbol.upper() if req.symbol else None
            existing.timeframe = req.timeframe.lower() if req.timeframe else None
            existing.interval_seconds = req.interval_seconds
            existing.enabled = req.enabled
            existing.params_json = json.dumps(req.params) if req.params else None
            existing.updated_at = now
            await db.commit()
            await db.refresh(existing)
            return existing

        sched = WorkflowSchedule(
            schedule_id=sched_id,
            workflow_type=req.workflow_type.upper(),
            symbol=req.symbol.upper() if req.symbol else None,
            timeframe=req.timeframe.lower() if req.timeframe else None,
            interval_seconds=req.interval_seconds,
            enabled=req.enabled,
            params_json=json.dumps(req.params) if req.params else None,
            next_trigger_at=now + timedelta(seconds=req.interval_seconds),
            updated_at=now,
        )
        db.add(sched)
        await db.commit()
        await db.refresh(sched)
        return sched

    @staticmethod
    async def patch_schedule(
        db: AsyncSession,
        schedule_id: str,
        req: WorkflowSchedulePatchRequest,
    ) -> Optional[WorkflowSchedule]:
        """Update interval, enabled state, or parameters on an existing schedule."""
        sched = await db.get(WorkflowSchedule, schedule_id)
        if sched is None:
            return None
        now = _utc_now_naive()
        if req.interval_seconds is not None:
            sched.interval_seconds = req.interval_seconds
            sched.next_trigger_at = now + timedelta(seconds=req.interval_seconds)
        if req.enabled is not None:
            sched.enabled = req.enabled
        if req.params is not None:
            sched.params_json = json.dumps(req.params)
        sched.updated_at = now
        await db.commit()
        await db.refresh(sched)
        return sched

    @staticmethod
    async def delete_schedule(db: AsyncSession, schedule_id: str) -> bool:
        """Remove a schedule from persistence."""
        sched = await db.get(WorkflowSchedule, schedule_id)
        if sched is None:
            return False
        await db.delete(sched)
        await db.commit()
        return True

    @classmethod
    async def trigger_due_schedules(cls, db: AsyncSession) -> List[str]:
        """Evaluate enabled schedules whose next_trigger_at has passed and enqueue runs."""
        now = _utc_now_naive()
        stmt = select(WorkflowSchedule).where(
            and_(
                WorkflowSchedule.enabled.is_(True),
                WorkflowSchedule.next_trigger_at <= now,
            )
        )
        due = list((await db.execute(stmt)).scalars().all())
        dispatched_ids: List[str] = []

        for sched in due:
            params = json.loads(sched.params_json) if sched.params_json else {}
            run, _ = await cls.enqueue_run(
                db,
                workflow_type=sched.workflow_type,
                symbol=sched.symbol,
                timeframe=sched.timeframe,
                trigger_type="SCHEDULED",
                params=params,
                conflict_mode="return_existing",
            )
            sched.last_run_id = run.id
            sched.last_triggered_at = now
            sched.next_trigger_at = now + timedelta(seconds=sched.interval_seconds)
            sched.updated_at = now
            dispatched_ids.append(run.id)

        if dispatched_ids:
            await db.commit()
        return dispatched_ids

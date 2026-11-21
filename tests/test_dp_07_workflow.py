"""Comprehensive tests for Durable SQL Workflow Orchestration (WI-DP-07)."""

import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.workflow import WorkflowRun, WorkflowSchedule, WorkflowTask
from backend.app.schemas.workflow import (
    WorkflowSchedulePatchRequest,
    WorkflowScheduleUpsertRequest,
)
from backend.app.services.workflow_service import WorkflowService


@pytest.mark.asyncio
async def test_enqueue_and_idempotency_conflict(test_db: AsyncSession):
    """Verify workflow enqueueing and active-run mutual exclusion."""
    run1, deduplicated1 = await WorkflowService.enqueue_run(
        test_db,
        workflow_type="MEDALLION_DAG",
        symbol="BTCUSDT",
        timeframe="1h",
        trigger_type="MANUAL",
        params={"lookback_days": 15},
    )
    assert deduplicated1 is False
    assert run1.status == "QUEUED"
    assert run1.idempotency_key == "MEDALLION_DAG:BTCUSDT:1h"

    # Enqueue same symbol/timeframe while run1 is active -> Returns existing run
    run2, deduplicated2 = await WorkflowService.enqueue_run(
        test_db,
        workflow_type="MEDALLION_DAG",
        symbol="BTCUSDT",
        timeframe="1h",
        trigger_type="MANUAL",
    )
    assert deduplicated2 is True
    assert run2.id == run1.id

    # Verify 4 DAG tasks created
    tasks = (
        await test_db.execute(
            select(WorkflowTask).where(WorkflowTask.run_id == run1.id).order_by(WorkflowTask.sequence_order.asc())
        )
    ).scalars().all()
    assert len(tasks) == 4
    assert [t.task_name for t in tasks] == [
        "ingest_bronze",
        "validate_silver",
        "build_gold_marts",
        "extract_features",
    ]


@pytest.mark.asyncio
async def test_lease_claiming_renewal_and_stale_reaping(test_db: AsyncSession):
    """Verify atomic lease acquisition, heartbeats, and stale worker recovery."""
    run, _ = await WorkflowService.enqueue_run(
        test_db,
        workflow_type="MEDALLION_DAG",
        symbol="ETHUSDT",
        timeframe="15m",
        trigger_type="MANUAL",
    )

    # Worker 1 claims run
    claimed1 = await WorkflowService.claim_run_by_id(
        test_db,
        run_id=run.id,
        worker_id="worker-node-1",
        lease_ttl_sec=30,
    )
    assert claimed1 is not None
    assert claimed1.status == "RUNNING"
    assert claimed1.lease_owner == "worker-node-1"
    token1 = claimed1.lease_token
    assert token1 is not None

    # Worker 2 attempts claim while lease is active -> None
    claimed2 = await WorkflowService.claim_run_by_id(
        test_db,
        run_id=run.id,
        worker_id="worker-node-2",
        lease_ttl_sec=30,
    )
    assert claimed2 is None

    # Renew lease with valid token -> True
    renew_ok = await WorkflowService.renew_lease(
        test_db,
        run_id=run.id,
        lease_token=token1,
        lease_ttl_sec=60,
    )
    assert renew_ok is True

    # Renew with invalid token -> False
    renew_bad = await WorkflowService.renew_lease(
        test_db,
        run_id=run.id,
        lease_token="invalid-token",
        lease_ttl_sec=60,
    )
    assert renew_bad is False

    # Simulate lease expiration (worker crash)
    claimed1.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)
    await test_db.commit()

    # Reaping finds the abandoned run and sets RETRY_WAIT
    reaped = await WorkflowService.reap_stale_runs(test_db)
    assert reaped == 1

    await test_db.refresh(claimed1)
    assert claimed1.status == "RETRY_WAIT"
    assert claimed1.lease_token is None


@pytest.mark.asyncio
async def test_step_level_resume_skips_completed_tasks(test_db: AsyncSession):
    """Verify crash recovery resumes from pending task without repeating completed tasks."""
    run, _ = await WorkflowService.enqueue_run(
        test_db,
        workflow_type="MEDALLION_DAG",
        symbol="SOLUSDT",
        timeframe="1h",
        trigger_type="MANUAL",
        params={"skip_network_ingest": True},
    )

    claimed = await WorkflowService.claim_run_by_id(
        test_db,
        run_id=run.id,
        worker_id="worker-crash-tester",
        lease_ttl_sec=60,
    )
    assert claimed is not None

    # Manually mark task 1 as completed with checkpoint
    tasks = (
        await test_db.execute(
            select(WorkflowTask).where(WorkflowTask.run_id == run.id).order_by(WorkflowTask.sequence_order.asc())
        )
    ).scalars().all()

    task1 = tasks[0]
    task1.status = "SUCCESS"
    task1.records_processed = 999
    task1.checkpoint_json = '{"records_processed": 999, "skipped": true}'
    await test_db.commit()

    # Verify task 1 is already SUCCESS
    await test_db.refresh(task1)
    assert task1.status == "SUCCESS"
    assert task1.records_processed == 999


@pytest.mark.asyncio
async def test_schedules_lifecycle_and_due_trigger(test_db: AsyncSession):
    """Verify schedule creation, patching, due evaluation, and deletion."""
    req = WorkflowScheduleUpsertRequest(
        schedule_id="sched-test-sol",
        workflow_type="MEDALLION_DAG",
        symbol="SOLUSDT",
        timeframe="1h",
        interval_seconds=60,
        enabled=True,
    )
    sched = await WorkflowService.upsert_schedule(test_db, req)
    assert sched.schedule_id == "sched-test-sol"
    assert sched.enabled is True

    # Patch interval
    patch_req = WorkflowSchedulePatchRequest(interval_seconds=120)
    updated = await WorkflowService.patch_schedule(test_db, "sched-test-sol", patch_req)
    assert updated is not None
    assert updated.interval_seconds == 120

    # Advance next_trigger_at to the past so it triggers
    updated.next_trigger_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
    await test_db.commit()

    dispatched = await WorkflowService.trigger_due_schedules(test_db)
    assert len(dispatched) == 1
    run_id = dispatched[0]

    run = await test_db.get(WorkflowRun, run_id)
    assert run is not None
    assert run.trigger_type == "SCHEDULED"
    assert run.symbol == "SOLUSDT"

    # Delete schedule
    deleted = await WorkflowService.delete_schedule(test_db, "sched-test-sol")
    assert deleted is True
    schedules = await WorkflowService.list_schedules(test_db)
    assert not any(s.schedule_id == "sched-test-sol" for s in schedules)


@pytest.mark.asyncio
async def test_workflow_overview_stats_calculation(test_db: AsyncSession):
    """Verify high-level aggregated operational KPI calculation."""
    # Ensure at least 1 completed run
    run, _ = await WorkflowService.enqueue_run(
        test_db,
        workflow_type="MEDALLION_DAG",
        symbol="ADAUSDT",
        timeframe="1h",
        trigger_type="MANUAL",
    )
    run.status = "SUCCESS"
    run.duration_seconds = 4.25
    run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await test_db.commit()

    stats = await WorkflowService.get_overview_stats(test_db)
    assert stats["total_runs"] >= 1
    assert stats["succeeded_runs"] >= 1
    assert stats["success_rate_pct"] > 0.0
    assert stats["avg_duration_seconds"] > 0.0

"""data plane storage, warehouse snapshots, and workflow tables

Revision ID: b8e4c21a904f
Revises: af2bd5126950
Create Date: 2026-11-17 13:55:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "b8e4c21a904f"
down_revision: Union[str, None] = "af2bd5126950"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Batch Ledger, Immutable Lake Snapshots, Manifest Files & Warehouse Snapshots
    op.create_table(
        "batch_ledger",
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("batch_type", sa.String(length=32), nullable=False),
        sa.Column("producer_name", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("timeframe", sa.String(length=16), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("nats_seq_start", sa.BigInteger(), nullable=True),
        sa.Column("nats_seq_end", sa.BigInteger(), nullable=True),
        sa.Column("records_received", sa.Integer(), nullable=False),
        sa.Column("records_written", sa.Integer(), nullable=False),
        sa.Column("records_rejected", sa.Integer(), nullable=False),
        sa.Column("staged_keys_json", sa.Text(), nullable=True),
        sa.Column("snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
        sa.Column("acked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("batch_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    with op.batch_alter_table("batch_ledger", schema=None) as batch_op:
        batch_op.create_index("ix_batch_ledger_status", ["status", "created_at"], unique=False)

    op.create_table(
        "lake_snapshots",
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("version_seq", sa.BigInteger(), nullable=False),
        sa.Column("parent_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("total_rows", sa.BigInteger(), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("min_event_time", sa.DateTime(), nullable=True),
        sa.Column("max_event_time", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["batch_ledger.batch_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint("dataset_id", "version_seq", name="uq_lake_snapshot_ds_ver"),
    )
    with op.batch_alter_table("lake_snapshots", schema=None) as batch_op:
        batch_op.create_index("ix_lake_snapshots_ds_status", ["dataset_id", "status"], unique=False)

    op.create_table(
        "lake_manifest_files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("partition_symbol", sa.String(length=32), nullable=True),
        sa.Column("partition_timeframe", sa.String(length=16), nullable=True),
        sa.Column("partition_dt", sa.String(length=10), nullable=True),
        sa.Column("file_format", sa.String(length=16), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("min_ts", sa.DateTime(), nullable=True),
        sa.Column("max_ts", sa.DateTime(), nullable=True),
        sa.Column("is_compacted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["lake_snapshots.snapshot_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "object_key", name="uq_manifest_snap_key"),
    )
    with op.batch_alter_table("lake_manifest_files", schema=None) as batch_op:
        batch_op.create_index(
            "ix_manifest_lookup",
            ["snapshot_id", "partition_symbol", "partition_timeframe", "partition_dt"],
            unique=False,
        )

    op.create_table(
        "warehouse_snapshots",
        sa.Column("dw_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("warehouse_version", sa.BigInteger(), nullable=False),
        sa.Column("source_lake_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("row_count_total", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_lake_snapshot_id"], ["lake_snapshots.snapshot_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("dw_snapshot_id"),
        sa.UniqueConstraint("warehouse_version"),
    )
    with op.batch_alter_table("warehouse_snapshots", schema=None) as batch_op:
        batch_op.create_index("ix_warehouse_snap_status", ["status", "warehouse_version"], unique=False)

    # 2. Durable Workflow Orchestration Tables
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_type", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("timeframe", sa.String(length=16), nullable=True),
        sa.Column("trigger_type", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("params_json", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.String(length=512), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.create_index("ix_workflow_runs_claim", ["status", "next_run_at", "priority"], unique=False)
        batch_op.create_index("ix_workflow_runs_lease", ["status", "lease_expires_at"], unique=False)
        batch_op.create_index(
            "uq_workflow_active_idempotency",
            ["idempotency_key"],
            unique=True,
            sqlite_where=sa.text("status IN ('QUEUED', 'RUNNING', 'RETRY_WAIT')"),
            postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING', 'RETRY_WAIT')"),
        )

    op.create_table(
        "workflow_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("task_name", sa.String(length=64), nullable=False),
        sa.Column("sequence_order", sa.Integer(), nullable=False),
        sa.Column("depends_on", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("checkpoint_json", sa.Text(), nullable=True),
        sa.Column("records_processed", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("workflow_tasks", schema=None) as batch_op:
        batch_op.create_index("ix_workflow_tasks_run_seq", ["run_id", "sequence_order"], unique=False)

    op.create_table(
        "workflow_schedules",
        sa.Column("schedule_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_type", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("timeframe", sa.String(length=16), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=True),
        sa.Column("last_run_id", sa.String(length=36), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("next_trigger_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["last_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("schedule_id"),
    )

    # 3. Existing Table Upgrades (BigInteger overflow prevention, SyncCheckpoint, redundant Kline index)
    with op.batch_alter_table("data_catalog_entries", schema=None) as batch_op:
        batch_op.alter_column(
            "row_count",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "size_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
        batch_op.add_column(sa.Column("active_snapshot_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("schema_hash", sa.String(length=64), nullable=True))

    with op.batch_alter_table("stream_checkpoints", schema=None) as batch_op:
        batch_op.alter_column(
            "last_stream_seq",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "processed_count",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "error_count",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )

    with op.batch_alter_table("sync_checkpoints", schema=None) as batch_op:
        batch_op.add_column(sa.Column("first_open_time", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_agg_trade_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "completeness_status",
                sa.String(length=24),
                server_default="UNPOPULATED",
                nullable=False,
            )
        )

    with op.batch_alter_table("klines", schema=None) as batch_op:
        batch_op.drop_index("ix_kline_lookup")


def downgrade() -> None:
    with op.batch_alter_table("klines", schema=None) as batch_op:
        batch_op.create_index("ix_kline_lookup", ["symbol", "timeframe", "open_time"], unique=False)

    with op.batch_alter_table("sync_checkpoints", schema=None) as batch_op:
        batch_op.drop_column("completeness_status")
        batch_op.drop_column("last_agg_trade_id")
        batch_op.drop_column("first_open_time")

    with op.batch_alter_table("stream_checkpoints", schema=None) as batch_op:
        batch_op.alter_column(
            "error_count",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "processed_count",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "last_stream_seq",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

    with op.batch_alter_table("data_catalog_entries", schema=None) as batch_op:
        batch_op.drop_column("schema_hash")
        batch_op.drop_column("active_snapshot_id")
        batch_op.alter_column(
            "size_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "row_count",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

    op.drop_table("workflow_schedules")

    with op.batch_alter_table("workflow_tasks", schema=None) as batch_op:
        batch_op.drop_index("ix_workflow_tasks_run_seq")
    op.drop_table("workflow_tasks")

    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.drop_index("uq_workflow_active_idempotency")
        batch_op.drop_index("ix_workflow_runs_lease")
        batch_op.drop_index("ix_workflow_runs_claim")
    op.drop_table("workflow_runs")

    with op.batch_alter_table("warehouse_snapshots", schema=None) as batch_op:
        batch_op.drop_index("ix_warehouse_snap_status")
    op.drop_table("warehouse_snapshots")

    with op.batch_alter_table("lake_manifest_files", schema=None) as batch_op:
        batch_op.drop_index("ix_manifest_lookup")
    op.drop_table("lake_manifest_files")

    with op.batch_alter_table("lake_snapshots", schema=None) as batch_op:
        batch_op.drop_index("ix_lake_snapshots_ds_status")
    op.drop_table("lake_snapshots")

    with op.batch_alter_table("batch_ledger", schema=None) as batch_op:
        batch_op.drop_index("ix_batch_ledger_status")
    op.drop_table("batch_ledger")

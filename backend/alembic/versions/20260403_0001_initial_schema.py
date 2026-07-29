"""initial schema

Revision ID: 20260403_0001
Revises:
Create Date: 2026-04-03 20:15:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260403_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "servers",
        sa.Column("server_id", sa.String(length=64), nullable=False),
        sa.Column("server_name", sa.String(length=255), nullable=False),
        sa.Column("group", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("health", sa.String(length=32), nullable=False),
        sa.Column("api_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("command_capabilities", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("server_id"),
    )
    op.create_index("ix_servers_status_last_seen", "servers", ["status", "last_seen"], unique=False)

    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("server_id", sa.String(length=64), nullable=False),
        sa.Column("cpu", sa.Float(), nullable=False),
        sa.Column("memory", sa.Float(), nullable=False),
        sa.Column("disk", sa.Float(), nullable=False),
        sa.Column("network_mbps", sa.Float(), nullable=False),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("gpu_utilization", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_metric_snapshots_server_id", "metric_snapshots", ["server_id"], unique=False)
    op.create_index("ix_metric_snapshots_timestamp", "metric_snapshots", ["timestamp"], unique=False)
    op.create_index("ix_metrics_server_timestamp", "metric_snapshots", ["server_id", "timestamp"], unique=False)

    op.create_table(
        "task_runs",
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("server_id", sa.String(length=64), nullable=False),
        sa.Column("task", sa.String(length=255), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("workflow_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("logs", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index("ix_task_runs_created_at", "task_runs", ["created_at"], unique=False)
    op.create_index("ix_task_runs_server_id", "task_runs", ["server_id"], unique=False)
    op.create_index("ix_task_runs_status", "task_runs", ["status"], unique=False)
    op.create_index("ix_task_runs_status_updated", "task_runs", ["status", "updated_at"], unique=False)
    op.create_index("ix_task_runs_server_status_created", "task_runs", ["server_id", "status", "created_at"], unique=False)
    op.create_index("ix_task_runs_workflow_id", "task_runs", ["workflow_id"], unique=False)

    op.create_table(
        "workflow_runs",
        sa.Column("workflow_id", sa.String(length=64), nullable=False),
        sa.Column("server_id", sa.String(length=64), nullable=False),
        sa.Column("workflow", sa.String(length=255), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("linked_task_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step_index", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("workflow_id"),
    )
    op.create_index("ix_workflow_runs_created_at", "workflow_runs", ["created_at"], unique=False)
    op.create_index("ix_workflow_runs_server_id", "workflow_runs", ["server_id"], unique=False)
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"], unique=False)
    op.create_index("ix_workflow_runs_server_status_created", "workflow_runs", ["server_id", "status", "created_at"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("resource", sa.String(length=255), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"], unique=False)
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"], unique=False)
    op.create_index("ix_audit_events_timestamp_action", "audit_events", ["timestamp", "action"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_events_timestamp_action", table_name="audit_events")
    op.drop_index("ix_audit_events_timestamp", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_workflow_runs_server_status_created", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_server_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_created_at", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_index("ix_task_runs_workflow_id", table_name="task_runs")
    op.drop_index("ix_task_runs_server_status_created", table_name="task_runs")
    op.drop_index("ix_task_runs_status_updated", table_name="task_runs")
    op.drop_index("ix_task_runs_status", table_name="task_runs")
    op.drop_index("ix_task_runs_server_id", table_name="task_runs")
    op.drop_index("ix_task_runs_created_at", table_name="task_runs")
    op.drop_table("task_runs")

    op.drop_index("ix_metrics_server_timestamp", table_name="metric_snapshots")
    op.drop_index("ix_metric_snapshots_timestamp", table_name="metric_snapshots")
    op.drop_index("ix_metric_snapshots_server_id", table_name="metric_snapshots")
    op.drop_table("metric_snapshots")

    op.drop_index("ix_servers_status_last_seen", table_name="servers")
    op.drop_table("servers")

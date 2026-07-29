"""ops features

Revision ID: 20260403_0002
Revises: 20260403_0001
Create Date: 2026-04-03 22:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260403_0002"
down_revision = "20260403_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("signal", sa.String(length=64), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("rule_id"),
    )
    op.create_index("ix_alert_rules_signal", "alert_rules", ["signal"], unique=False)
    op.create_index("ix_alert_rules_signal_enabled", "alert_rules", ["signal", "enabled"], unique=False)

    op.create_table(
        "alert_records",
        sa.Column("alert_id", sa.String(length=64), nullable=False),
        sa.Column("server_id", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("signal", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("message", sa.String(length=512), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("alert_id"),
    )
    op.create_index("ix_alert_records_rule_id", "alert_records", ["rule_id"], unique=False)
    op.create_index("ix_alert_records_server_id", "alert_records", ["server_id"], unique=False)
    op.create_index("ix_alert_records_severity", "alert_records", ["severity"], unique=False)
    op.create_index("ix_alert_records_signal", "alert_records", ["signal"], unique=False)
    op.create_index("ix_alert_records_state", "alert_records", ["state"], unique=False)
    op.create_index("ix_alert_records_server_state", "alert_records", ["server_id", "state"], unique=False)
    op.create_index("ix_alert_records_signal_state", "alert_records", ["signal", "state"], unique=False)

    op.create_table(
        "notification_endpoints",
        sa.Column("endpoint_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=1024), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("endpoint_id"),
    )
    op.create_index("ix_notification_endpoints_channel", "notification_endpoints", ["channel"], unique=False)

    op.create_table(
        "schedules",
        sa.Column("schedule_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("server_id", sa.String(length=64), nullable=False),
        sa.Column("workflow", sa.String(length=255), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("schedule_id"),
    )
    op.create_index("ix_schedules_server_id", "schedules", ["server_id"], unique=False)
    op.create_index("ix_schedules_next_run_at", "schedules", ["next_run_at"], unique=False)
    op.create_index("ix_schedules_active_next_run", "schedules", ["active", "next_run_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_schedules_active_next_run", table_name="schedules")
    op.drop_index("ix_schedules_next_run_at", table_name="schedules")
    op.drop_index("ix_schedules_server_id", table_name="schedules")
    op.drop_table("schedules")

    op.drop_index("ix_notification_endpoints_channel", table_name="notification_endpoints")
    op.drop_table("notification_endpoints")

    op.drop_index("ix_alert_records_signal_state", table_name="alert_records")
    op.drop_index("ix_alert_records_server_state", table_name="alert_records")
    op.drop_index("ix_alert_records_state", table_name="alert_records")
    op.drop_index("ix_alert_records_signal", table_name="alert_records")
    op.drop_index("ix_alert_records_severity", table_name="alert_records")
    op.drop_index("ix_alert_records_server_id", table_name="alert_records")
    op.drop_index("ix_alert_records_rule_id", table_name="alert_records")
    op.drop_table("alert_records")

    op.drop_index("ix_alert_rules_signal_enabled", table_name="alert_rules")
    op.drop_index("ix_alert_rules_signal", table_name="alert_rules")
    op.drop_table("alert_rules")

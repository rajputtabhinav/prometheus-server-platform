"""hardware monitoring schema

Revision ID: 20260404_0009
Revises: 20260404_0008
Create Date: 2026-04-04 18:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260404_0009"
down_revision = "20260404_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("servers")}
    tables = set(inspector.get_table_names())

    if "last_telemetry_at" not in columns:
        op.add_column("servers", sa.Column("last_telemetry_at", sa.DateTime(timezone=True), nullable=True))
    if "last_inventory_refresh_at" not in columns:
        op.add_column("servers", sa.Column("last_inventory_refresh_at", sa.DateTime(timezone=True), nullable=True))

    if "hardware_components" not in tables:
        op.create_table(
            "hardware_components",
            sa.Column("component_id", sa.String(length=128), primary_key=True),
            sa.Column("server_id", sa.String(length=64), nullable=False),
            sa.Column("component_type", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("slot_or_path", sa.String(length=255), nullable=True),
            sa.Column("vendor", sa.String(length=255), nullable=True),
            sa.Column("model", sa.String(length=255), nullable=True),
            sa.Column("serial", sa.String(length=255), nullable=True),
            sa.Column("firmware_version", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=64), nullable=False),
            sa.Column("health", sa.String(length=32), nullable=False),
            sa.Column("capabilities", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_hardware_components_server_type", "hardware_components", ["server_id", "component_type"])
        op.create_index("ix_hardware_components_server_status", "hardware_components", ["server_id", "status"])

    if "hardware_component_metrics" not in tables:
        op.create_table(
            "hardware_component_metrics",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("server_id", sa.String(length=64), nullable=False),
            sa.Column("component_id", sa.String(length=128), nullable=False),
            sa.Column("metric_key", sa.String(length=128), nullable=False),
            sa.Column("value", sa.Float(), nullable=True),
            sa.Column("unit", sa.String(length=32), nullable=True),
            sa.Column("status", sa.String(length=64), nullable=False),
            sa.Column("labels_json", sa.JSON(), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_hardware_metrics_component_key_time", "hardware_component_metrics", ["component_id", "metric_key", "recorded_at"])
        op.create_index("ix_hardware_metrics_server_time", "hardware_component_metrics", ["server_id", "recorded_at"])

    if "collector_runs" not in tables:
        op.create_table(
            "collector_runs",
            sa.Column("collector_run_id", sa.String(length=64), primary_key=True),
            sa.Column("server_id", sa.String(length=64), nullable=False),
            sa.Column("collector_name", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=64), nullable=False),
            sa.Column("message", sa.String(length=512), nullable=True),
            sa.Column("duration_ms", sa.Float(), nullable=True),
            sa.Column("capability_state", sa.String(length=64), nullable=True),
            sa.Column("metrics_emitted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("inventory_items_seen", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_collector_runs_server_collector_recorded", "collector_runs", ["server_id", "collector_name", "recorded_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    columns = {column["name"] for column in inspector.get_columns("servers")}

    if "collector_runs" in tables:
        op.drop_index("ix_collector_runs_server_collector_recorded", table_name="collector_runs")
        op.drop_table("collector_runs")
    if "hardware_component_metrics" in tables:
        op.drop_index("ix_hardware_metrics_server_time", table_name="hardware_component_metrics")
        op.drop_index("ix_hardware_metrics_component_key_time", table_name="hardware_component_metrics")
        op.drop_table("hardware_component_metrics")
    if "hardware_components" in tables:
        op.drop_index("ix_hardware_components_server_status", table_name="hardware_components")
        op.drop_index("ix_hardware_components_server_type", table_name="hardware_components")
        op.drop_table("hardware_components")
    if "last_inventory_refresh_at" in columns:
        op.drop_column("servers", "last_inventory_refresh_at")
    if "last_telemetry_at" in columns:
        op.drop_column("servers", "last_telemetry_at")

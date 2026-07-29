"""server activity tracking fields

Revision ID: 20260404_0008
Revises: 20260404_0007
Create Date: 2026-04-04 16:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260404_0008"
down_revision = "20260404_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("servers")}

    if "last_heartbeat_at" not in columns:
        op.add_column("servers", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    if "last_metric_at" not in columns:
        op.add_column("servers", sa.Column("last_metric_at", sa.DateTime(timezone=True), nullable=True))
    if "last_task_poll_at" not in columns:
        op.add_column("servers", sa.Column("last_task_poll_at", sa.DateTime(timezone=True), nullable=True))
    if "last_task_result_at" not in columns:
        op.add_column("servers", sa.Column("last_task_result_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("servers")}

    if "last_task_result_at" in columns:
        op.drop_column("servers", "last_task_result_at")
    if "last_task_poll_at" in columns:
        op.drop_column("servers", "last_task_poll_at")
    if "last_metric_at" in columns:
        op.drop_column("servers", "last_metric_at")
    if "last_heartbeat_at" in columns:
        op.drop_column("servers", "last_heartbeat_at")

"""task run events table

Revision ID: 20260404_0007
Revises: 20260404_0006
Create Date: 2026-04-04 15:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260404_0007"
down_revision = "20260404_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_run_events" in inspector.get_table_names():
        return

    op.create_table(
        "task_run_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_task_run_events_task_id", "task_run_events", ["task_id"], unique=False)
    op.create_index("ix_task_run_events_task_created", "task_run_events", ["task_id", "created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_run_events" not in inspector.get_table_names():
        return

    op.drop_index("ix_task_run_events_task_created", table_name="task_run_events")
    op.drop_index("ix_task_run_events_task_id", table_name="task_run_events")
    op.drop_table("task_run_events")

"""baseline policies table

Revision ID: 20260403_0005
Revises: 20260403_0004
Create Date: 2026-04-03 06:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260403_0005"
down_revision = "20260403_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "baseline_policies" in inspector.get_table_names():
        return
    op.create_table(
        "baseline_policies",
        sa.Column("baseline_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("group", sa.String(length=255), nullable=False),
        sa.Column("task", sa.String(length=255), nullable=False),
        sa.Column("minimum_score", sa.Float(), nullable=False),
        sa.Column("max_temperature_c", sa.Float(), nullable=True),
        sa.Column("min_throughput", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("baseline_id"),
    )
    op.create_index("ix_baseline_policies_group", "baseline_policies", ["group"], unique=False)
    op.create_index("ix_baseline_policies_task", "baseline_policies", ["task"], unique=False)
    op.create_index("ix_baseline_policies_group_task", "baseline_policies", ["group", "task"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "baseline_policies" not in inspector.get_table_names():
        return
    op.drop_index("ix_baseline_policies_group_task", table_name="baseline_policies")
    op.drop_index("ix_baseline_policies_task", table_name="baseline_policies")
    op.drop_index("ix_baseline_policies_group", table_name="baseline_policies")
    op.drop_table("baseline_policies")

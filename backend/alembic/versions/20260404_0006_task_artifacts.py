"""task artifacts table

Revision ID: 20260404_0006
Revises: 20260403_0005
Create Date: 2026-04-04 11:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260404_0006"
down_revision = "20260403_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_artifacts" in inspector.get_table_names():
        return

    op.create_table(
        "task_artifacts",
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("artifact_id"),
    )
    op.create_index("ix_task_artifacts_task_id", "task_artifacts", ["task_id"], unique=False)
    op.create_index("ix_task_artifacts_task_created", "task_artifacts", ["task_id", "created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_artifacts" not in inspector.get_table_names():
        return

    op.drop_index("ix_task_artifacts_task_created", table_name="task_artifacts")
    op.drop_index("ix_task_artifacts_task_id", table_name="task_artifacts")
    op.drop_table("task_artifacts")

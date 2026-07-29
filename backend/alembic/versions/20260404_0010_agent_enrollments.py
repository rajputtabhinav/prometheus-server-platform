"""agent enrollment bootstrap

Revision ID: 20260404_0010
Revises: 20260404_0009
Create Date: 2026-04-04 20:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260404_0010"
down_revision = "20260404_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "agent_enrollments" not in tables:
        op.create_table(
            "agent_enrollments",
            sa.Column("enrollment_id", sa.String(length=64), primary_key=True),
            sa.Column("connection_code", sa.String(length=64), nullable=False, unique=True),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("group", sa.String(length=255), nullable=False),
            sa.Column("tags", sa.JSON(), nullable=False),
            sa.Column("capabilities", sa.JSON(), nullable=False),
            sa.Column("target_os", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("claimed_server_id", sa.String(length=64), nullable=True),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_agent_enrollments_connection_code", "agent_enrollments", ["connection_code"], unique=False)
        op.create_index("ix_agent_enrollments_target_os", "agent_enrollments", ["target_os"], unique=False)
        op.create_index("ix_agent_enrollments_status", "agent_enrollments", ["status"], unique=False)
        op.create_index("ix_agent_enrollments_status_expires", "agent_enrollments", ["status", "expires_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "agent_enrollments" in tables:
        op.drop_index("ix_agent_enrollments_status_expires", table_name="agent_enrollments")
        op.drop_index("ix_agent_enrollments_status", table_name="agent_enrollments")
        op.drop_index("ix_agent_enrollments_target_os", table_name="agent_enrollments")
        op.drop_index("ix_agent_enrollments_connection_code", table_name="agent_enrollments")
        op.drop_table("agent_enrollments")

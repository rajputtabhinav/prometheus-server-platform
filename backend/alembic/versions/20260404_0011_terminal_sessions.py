"""terminal sessions

Revision ID: 20260404_0011
Revises: 20260404_0010
Create Date: 2026-04-04 21:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260404_0011"
down_revision = "20260404_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "terminal_sessions" not in tables:
        op.create_table(
            "terminal_sessions",
            sa.Column("session_id", sa.String(length=64), primary_key=True),
            sa.Column("server_id", sa.String(length=64), nullable=False),
            sa.Column("opened_by", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("shell_type", sa.String(length=64), nullable=True),
            sa.Column("terminal_supported", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("open_requested", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("close_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_agent_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_browser_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("recent_output_json", sa.JSON(), nullable=False),
            sa.Column("pending_input_json", sa.JSON(), nullable=False),
            sa.Column("pending_resize_json", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
        )
        op.create_index("ix_terminal_sessions_server_id", "terminal_sessions", ["server_id"], unique=False)
        op.create_index("ix_terminal_sessions_status", "terminal_sessions", ["status"], unique=False)
        op.create_index(
            "ix_terminal_sessions_server_status_updated",
            "terminal_sessions",
            ["server_id", "status", "updated_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "terminal_sessions" in tables:
        op.drop_index("ix_terminal_sessions_server_status_updated", table_name="terminal_sessions")
        op.drop_index("ix_terminal_sessions_status", table_name="terminal_sessions")
        op.drop_index("ix_terminal_sessions_server_id", table_name="terminal_sessions")
        op.drop_table("terminal_sessions")

"""revoked token store

Revision ID: 20260403_0004
Revises: 20260403_0003
Create Date: 2026-04-03 23:50:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260403_0004"
down_revision = "20260403_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "revoked_tokens" in inspector.get_table_names():
        return
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("token_kind", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index("ix_revoked_tokens_username", "revoked_tokens", ["username"], unique=False)
    op.create_index("ix_revoked_tokens_token_kind", "revoked_tokens", ["token_kind"], unique=False)
    op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"], unique=False)
    op.create_index(
        "ix_revoked_tokens_user_kind_expiry",
        "revoked_tokens",
        ["username", "token_kind", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "revoked_tokens" not in inspector.get_table_names():
        return
    op.drop_index("ix_revoked_tokens_user_kind_expiry", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_token_kind", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_username", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")

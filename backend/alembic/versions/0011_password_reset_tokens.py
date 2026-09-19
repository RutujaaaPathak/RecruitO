"""Password reset tokens

Stores short-lived, single-use password-reset tokens. Only a SHA-256 digest
of the raw token is persisted (never the token itself); the ``email`` column
indexes token rows so a new request revokes any previous ones for the same
account.

Revision ID: 0011_password_reset_tokens
Revises: 0010_video_interview_type
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0011_password_reset_tokens"
down_revision = "0010_video_interview_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_password_reset_tokens_id", "password_reset_tokens", ["id"]
    )
    op.create_index(
        "ix_password_reset_tokens_email", "password_reset_tokens", ["email"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_password_reset_tokens_email", table_name="password_reset_tokens"
    )
    op.drop_index("ix_password_reset_tokens_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
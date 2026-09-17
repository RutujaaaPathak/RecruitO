"""Technical Video Interview (persisted live interview sessions)

Revision ID: 0008_video_interviews
Revises: 0007_aptitude_tests
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0008_video_interviews"
down_revision = "0007_aptitude_tests"
branch_labels = None
depends_on = None

_ENUM_NAME = "assessmentstatusenum"
_ENUM_VALUES = ["in_progress", "completed"]


def _enum_column():
    # create_type=False: the enum is created explicitly below, so the table DDL
    # must not emit a second CREATE TYPE (duplicate type already exists).
    return postgresql.ENUM(*_ENUM_VALUES, name=_ENUM_NAME, create_type=False)


def _index_missing(inspector, table, name):
    return not any(i["name"] == name for i in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # The shared assessmentstatusenum already exists (mcq_assessments).
    # checkfirst skips the CREATE TYPE if the type is present.
    postgresql.ENUM(*_ENUM_VALUES, name=_ENUM_NAME).create(bind, checkfirst=True)

    if not inspector.has_table("video_interviews"):
        op.create_table(
            "video_interviews",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column(
                "application_id",
                sa.Integer(),
                sa.ForeignKey("applications.id"),
                nullable=False,
            ),
            sa.Column("status", _enum_column(), nullable=False),
            sa.Column(
                "camera_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "microphone_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "started_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
        )
    for index, cols in (
        ("ix_video_interviews_id", ["id"]),
        ("ix_video_interviews_user_id", ["user_id"]),
        ("ix_video_interviews_application_id", ["application_id"]),
    ):
        if _index_missing(inspector, "video_interviews", index):
            op.create_index(index, "video_interviews", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("video_interviews"):
        op.drop_table("video_interviews")
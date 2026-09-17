"""Video interview questions on the shared question table

Lets the shared ``mock_interview_questions`` table also back technical video
interview sessions: adds a nullable ``video_interview_id`` column and relaxes
the previously-NOT-NULL ``interview_id`` (a question is anchored to exactly one
of the two sessions).

Revision ID: 0009_video_interview_questions
Revises: 0008_video_interviews
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0009_video_interview_questions"
down_revision = "0008_video_interviews"
branch_labels = None
depends_on = None

_TABLE = "mock_interview_questions"


def _column_names(inspector, table):
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table(_TABLE):
        return

    columns = _column_names(inspector, _TABLE)
    if "video_interview_id" not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "video_interview_id",
                sa.Integer(),
                sa.ForeignKey("video_interviews.id"),
                nullable=True,
            ),
        )

    # interview_id is now optional because the shared table also stores
    # video-interview questions.
    op.alter_column(
        _TABLE,
        "interview_id",
        existing_type=sa.Integer(),
        existing_nullable=False,
        nullable=True,
    )

    existing_indexes = {i["name"] for i in inspector.get_indexes(_TABLE)}
    if "ix_mock_interview_questions_video_interview_id" not in existing_indexes:
        op.create_index(
            "ix_mock_interview_questions_video_interview_id",
            _TABLE,
            ["video_interview_id"],
        )

    existing_uc = {u["name"] for u in inspector.get_unique_constraints(_TABLE)}
    if "uq_video_interview_question_index" not in existing_uc:
        op.create_unique_constraint(
            "uq_video_interview_question_index",
            _TABLE,
            ["video_interview_id", "question_index"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table(_TABLE):
        return

    existing_uc = {u["name"] for u in inspector.get_unique_constraints(_TABLE)}
    if "uq_video_interview_question_index" in existing_uc:
        op.drop_constraint(
            "uq_video_interview_question_index",
            _TABLE,
            type_="unique",
        )

    existing_indexes = {i["name"] for i in inspector.get_indexes(_TABLE)}
    if "ix_mock_interview_questions_video_interview_id" in existing_indexes:
        op.drop_index(
            "ix_mock_interview_questions_video_interview_id",
            table_name=_TABLE,
        )

    columns = _column_names(inspector, _TABLE)
    if "video_interview_id" in columns:
        op.drop_column(_TABLE, "video_interview_id")
"""AI mock interviews (sessions + questions)

Revision ID: 0004_mock_interviews
Revises: 0003_chat_history
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004_mock_interviews"
down_revision = "0003_chat_history"
branch_labels = None
depends_on = None

_ENUM_NAME = "mockinterviewstatusenum"
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

    # The app's bootstrap (main.py -> Base.metadata.create_all) may already have
    # created the type for this revision. checkfirst skips if it exists.
    postgresql.ENUM(*_ENUM_VALUES, name=_ENUM_NAME).create(bind, checkfirst=True)

    if not inspector.has_table("mock_interviews"):
        op.create_table(
            "mock_interviews",
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
            sa.Column("max_questions", sa.Integer(), nullable=False),
            sa.Column(
                "started_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("overall_score", sa.Integer(), nullable=True),
            sa.Column("category_scores", sa.JSON(), nullable=True),
            sa.Column("strengths", sa.JSON(), nullable=True),
            sa.Column("weaknesses", sa.JSON(), nullable=True),
            sa.Column("recommended_topics", sa.JSON(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("report", sa.JSON(), nullable=True),
            sa.Column("report_generated_by", sa.String(), nullable=True),
            sa.Column("report_notice", sa.Text(), nullable=True),
            sa.Column("skill_gap", sa.JSON(), nullable=True),
            sa.Column("sources", sa.JSON(), nullable=True),
            sa.Column("model_used", sa.String(), nullable=True),
            sa.Column("used_fallback", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
        )
    for index, cols in (
        ("ix_mock_interviews_id", ["id"]),
        ("ix_mock_interviews_user_id", ["user_id"]),
        ("ix_mock_interviews_application_id", ["application_id"]),
    ):
        if _index_missing(inspector, "mock_interviews", index):
            op.create_index(index, "mock_interviews", cols)

    if not inspector.has_table("mock_interview_questions"):
        op.create_table(
            "mock_interview_questions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "interview_id",
                sa.Integer(),
                sa.ForeignKey("mock_interviews.id"),
                nullable=False,
            ),
            sa.Column("question_index", sa.Integer(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("generated_by", sa.String(), nullable=True),
            sa.Column("notice", sa.Text(), nullable=True),
            sa.Column("question_sources", sa.JSON(), nullable=True),
            sa.Column("answer_text", sa.Text(), nullable=True),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("correctness", sa.Text(), nullable=True),
            sa.Column("strengths", sa.JSON(), nullable=True),
            sa.Column("weaknesses", sa.JSON(), nullable=True),
            sa.Column("missing_points", sa.JSON(), nullable=True),
            sa.Column("feedback", sa.Text(), nullable=True),
            sa.Column("evaluation", sa.JSON(), nullable=True),
            sa.Column("evaluation_generated_by", sa.String(), nullable=True),
            sa.Column("evaluation_notice", sa.Text(), nullable=True),
            sa.Column("evaluated_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint(
                "interview_id",
                "question_index",
                name="uq_mock_interview_question_index",
            ),
        )
    for index, cols in (
        ("ix_mock_interview_questions_id", ["id"]),
        ("ix_mock_interview_questions_interview_id", ["interview_id"]),
    ):
        if _index_missing(inspector, "mock_interview_questions", index):
            op.create_index(index, "mock_interview_questions", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("mock_interview_questions"):
        op.drop_table("mock_interview_questions")
    if inspector.has_table("mock_interviews"):
        op.drop_table("mock_interviews")
    if any(e["name"] == _ENUM_NAME for e in inspector.get_enums()):
        op.execute("DROP TYPE IF EXISTS " + _ENUM_NAME)
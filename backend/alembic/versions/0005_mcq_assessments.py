"""AI MCQ Assessments (tests + questions + answers)

Revision ID: 0005_mcq_assessments
Revises: 0004_mock_interviews
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0005_mcq_assessments"
down_revision = "0004_mock_interviews"
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

    # The app's bootstrap (main.py -> Base.metadata.create_all) may already have
    # created the type for this revision. checkfirst skips if it exists.
    postgresql.ENUM(*_ENUM_VALUES, name=_ENUM_NAME).create(bind, checkfirst=True)

    if not inspector.has_table("mcq_assessments"):
        op.create_table(
            "mcq_assessments",
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
            sa.Column("total_questions", sa.Integer(), nullable=False),
            sa.Column("time_limit_minutes", sa.Integer(), nullable=False),
            sa.Column(
                "started_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("expired", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("total_scored", sa.Integer(), nullable=True),
            sa.Column("percentage", sa.Integer(), nullable=True),
            sa.Column("correct_count", sa.Integer(), nullable=True),
            sa.Column("incorrect_count", sa.Integer(), nullable=True),
            sa.Column("unanswered_count", sa.Integer(), nullable=True),
            sa.Column("passed", sa.Boolean(), nullable=True),
            sa.Column("pass_percentage", sa.Integer(), nullable=True),
            sa.Column("category_performance", sa.JSON(), nullable=True),
            sa.Column("result_notice", sa.Text(), nullable=True),
            sa.Column("generated_by", sa.String(), nullable=True),
            sa.Column("model_used", sa.String(), nullable=True),
            sa.Column("used_fallback", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
        )
    for index, cols in (
        ("ix_mcq_assessments_id", ["id"]),
        ("ix_mcq_assessments_user_id", ["user_id"]),
        ("ix_mcq_assessments_application_id", ["application_id"]),
    ):
        if _index_missing(inspector, "mcq_assessments", index):
            op.create_index(index, "mcq_assessments", cols)

    if not inspector.has_table("mcq_questions"):
        op.create_table(
            "mcq_questions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "assessment_id",
                sa.Integer(),
                sa.ForeignKey("mcq_assessments.id"),
                nullable=False,
            ),
            sa.Column("question_index", sa.Integer(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("options", sa.JSON(), nullable=False),
            sa.Column("correct_option_index", sa.Integer(), nullable=False),
            sa.Column("generated_by", sa.String(), nullable=True),
            sa.Column("notice", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint(
                "assessment_id",
                "question_index",
                name="uq_mcq_question_index",
            ),
        )
    for index, cols in (
        ("ix_mcq_questions_id", ["id"]),
        ("ix_mcq_questions_assessment_id", ["assessment_id"]),
    ):
        if _index_missing(inspector, "mcq_questions", index):
            op.create_index(index, "mcq_questions", cols)

    if not inspector.has_table("mcq_answers"):
        op.create_table(
            "mcq_answers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "assessment_id",
                sa.Integer(),
                sa.ForeignKey("mcq_assessments.id"),
                nullable=False,
            ),
            sa.Column(
                "question_id",
                sa.Integer(),
                sa.ForeignKey("mcq_questions.id"),
                nullable=False,
            ),
            sa.Column("selected_option", sa.Integer(), nullable=False),
            sa.Column("is_correct", sa.Boolean(), nullable=False),
            sa.Column(
                "answered_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "assessment_id",
                "question_id",
                name="uq_mcq_answer_question",
            ),
        )
    for index, cols in (
        ("ix_mcq_answers_id", ["id"]),
        ("ix_mcq_answers_assessment_id", ["assessment_id"]),
        ("ix_mcq_answers_question_id", ["question_id"]),
    ):
        if _index_missing(inspector, "mcq_answers", index):
            op.create_index(index, "mcq_answers", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("mcq_answers"):
        op.drop_table("mcq_answers")
    if inspector.has_table("mcq_questions"):
        op.drop_table("mcq_questions")
    if inspector.has_table("mcq_assessments"):
        op.drop_table("mcq_assessments")
    if any(e["name"] == _ENUM_NAME for e in inspector.get_enums()):
        op.execute("DROP TYPE IF EXISTS " + _ENUM_NAME)
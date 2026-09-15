"""Aptitude Tests (tests + questions + answers)

Revision ID: 0007_aptitude_tests
Revises: 0006_coding_tests
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0007_aptitude_tests"
down_revision = "0006_coding_tests"
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

    if not inspector.has_table("aptitude_tests"):
        op.create_table(
            "aptitude_tests",
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
        ("ix_aptitude_tests_id", ["id"]),
        ("ix_aptitude_tests_user_id", ["user_id"]),
        ("ix_aptitude_tests_application_id", ["application_id"]),
    ):
        if _index_missing(inspector, "aptitude_tests", index):
            op.create_index(index, "aptitude_tests", cols)

    if not inspector.has_table("aptitude_questions"):
        op.create_table(
            "aptitude_questions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "aptitude_test_id",
                sa.Integer(),
                sa.ForeignKey("aptitude_tests.id"),
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
                "aptitude_test_id",
                "question_index",
                name="uq_aptitude_question_index",
            ),
        )
    for index, cols in (
        ("ix_aptitude_questions_id", ["id"]),
        ("ix_aptitude_questions_aptitude_test_id", ["aptitude_test_id"]),
    ):
        if _index_missing(inspector, "aptitude_questions", index):
            op.create_index(index, "aptitude_questions", cols)

    if not inspector.has_table("aptitude_answers"):
        op.create_table(
            "aptitude_answers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "aptitude_test_id",
                sa.Integer(),
                sa.ForeignKey("aptitude_tests.id"),
                nullable=False,
            ),
            sa.Column(
                "question_id",
                sa.Integer(),
                sa.ForeignKey("aptitude_questions.id"),
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
                "aptitude_test_id",
                "question_id",
                name="uq_aptitude_answer_question",
            ),
        )
    for index, cols in (
        ("ix_aptitude_answers_id", ["id"]),
        ("ix_aptitude_answers_aptitude_test_id", ["aptitude_test_id"]),
        ("ix_aptitude_answers_question_id", ["question_id"]),
    ):
        if _index_missing(inspector, "aptitude_answers", index):
            op.create_index(index, "aptitude_answers", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("aptitude_answers"):
        op.drop_table("aptitude_answers")
    if inspector.has_table("aptitude_questions"):
        op.drop_table("aptitude_questions")
    if inspector.has_table("aptitude_tests"):
        op.drop_table("aptitude_tests")
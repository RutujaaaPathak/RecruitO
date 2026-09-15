"""Coding Tests (tests + problems + submissions)

Revision ID: 0006_coding_tests
Revises: 0005_mcq_assessments
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0006_coding_tests"
down_revision = "0005_mcq_assessments"
branch_labels = None
depends_on = None

_ENUM_NAME = "codingteststatusenum"
_ENUM_VALUES = ["in_progress", "completed"]


def _enum_column():
    return postgresql.ENUM(*_ENUM_VALUES, name=_ENUM_NAME, create_type=False)


def _index_missing(inspector, table, name):
    return not any(i["name"] == name for i in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    postgresql.ENUM(*_ENUM_VALUES, name=_ENUM_NAME).create(bind, checkfirst=True)

    if not inspector.has_table("coding_tests"):
        op.create_table(
            "coding_tests",
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
            sa.Column("total_problems", sa.Integer(), nullable=False),
            sa.Column(
                "solved_count", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("passed", sa.Boolean(), nullable=True),
            sa.Column("pass_percentage", sa.Integer(), nullable=False),
            sa.Column(
                "started_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
        )
    for index, cols in (
        ("ix_coding_tests_id", ["id"]),
        ("ix_coding_tests_user_id", ["user_id"]),
        ("ix_coding_tests_application_id", ["application_id"]),
    ):
        if _index_missing(inspector, "coding_tests", index):
            op.create_index(index, "coding_tests", cols)

    if not inspector.has_table("coding_problems"):
        op.create_table(
            "coding_problems",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "coding_test_id",
                sa.Integer(),
                sa.ForeignKey("coding_tests.id"),
                nullable=False,
            ),
            sa.Column("problem_index", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("difficulty", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("input_format", sa.Text(), nullable=False),
            sa.Column("output_format", sa.Text(), nullable=False),
            sa.Column("constraints", sa.Text(), nullable=False),
            sa.Column("sample_cases", sa.JSON(), nullable=False),
            sa.Column("hidden_cases", sa.JSON(), nullable=False),
            sa.Column(
                "time_limit_seconds",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("5"),
            ),
            sa.Column("supported_languages", sa.JSON(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint(
                "coding_test_id", "problem_index", name="uq_coding_problem_index"
            ),
        )
    for index, cols in (
        ("ix_coding_problems_id", ["id"]),
        ("ix_coding_problems_coding_test_id", ["coding_test_id"]),
    ):
        if _index_missing(inspector, "coding_problems", index):
            op.create_index(index, "coding_problems", cols)

    if not inspector.has_table("coding_submissions"):
        op.create_table(
            "coding_submissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "coding_test_id",
                sa.Integer(),
                sa.ForeignKey("coding_tests.id"),
                nullable=False,
            ),
            sa.Column(
                "problem_id",
                sa.Integer(),
                sa.ForeignKey("coding_problems.id"),
                nullable=False,
            ),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("language", sa.String(), nullable=False),
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("passed_cases", sa.Integer(), nullable=False),
            sa.Column("total_cases", sa.Integer(), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("execution_time_ms", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("results", sa.JSON(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint(
                "coding_test_id", "problem_id", name="uq_coding_submission_problem"
            ),
        )
    for index, cols in (
        ("ix_coding_submissions_id", ["id"]),
        ("ix_coding_submissions_coding_test_id", ["coding_test_id"]),
        ("ix_coding_submissions_problem_id", ["problem_id"]),
        ("ix_coding_submissions_user_id", ["user_id"]),
    ):
        if _index_missing(inspector, "coding_submissions", index):
            op.create_index(index, "coding_submissions", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("coding_submissions"):
        op.drop_table("coding_submissions")
    if inspector.has_table("coding_problems"):
        op.drop_table("coding_problems")
    if inspector.has_table("coding_tests"):
        op.drop_table("coding_tests")
    if any(e["name"] == _ENUM_NAME for e in inspector.get_enums()):
        op.execute("DROP TYPE IF EXISTS " + _ENUM_NAME)
"""Company Assessment Answers

Adds the candidate-answer persistence layer of the recruitment pipeline:
one row per (attempt, question) on ``assessment_answers`` where the attempt is
the existing ``assessment_assignments`` row. ``(assignment_id, question_id)``
is unique so saving is an idempotent upsert (the candidate's latest answer),
mirroring the Mock Practice ``mcq_answers`` / ``coding_submissions`` contract
without touching Mock Practice rows.

MCQ answers carry ``selected_option`` + a server-computed ``is_correct``
snapshot (never serialized); coding answers carry the source ``code``,
``language`` and the grading verdict produced by the existing Docker sandbox —
per-case ``results`` store only index/pass/status/time, never hidden-case I/O.

Revision ID: 0015_assessment_answers
Revises: 0014_assessment_question_bank
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0015_assessment_answers"
down_revision = "0014_assessment_question_bank"
branch_labels = None
depends_on = None


def _index_missing(inspector, table, index):
    return not any(i["name"] == index for i in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("assessment_answers"):
        op.create_table(
            "assessment_answers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "assignment_id",
                sa.Integer(),
                sa.ForeignKey("assessment_assignments.id"),
                nullable=False,
            ),
            sa.Column(
                "question_id",
                sa.Integer(),
                sa.ForeignKey("assessment_questions.id"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "assignment_id",
                "question_id",
                name="uq_assessment_answer_question",
            ),
            # MCQ answer (server-side only: correctness is never serialized).
            sa.Column("selected_option", sa.Integer(), nullable=True),
            sa.Column("is_correct", sa.Boolean(), nullable=True),
            # Coding answer + grading verdict (from the Docker sandbox).
            sa.Column("language", sa.String(), nullable=True),
            sa.Column("code", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("passed_cases", sa.Integer(), nullable=True),
            sa.Column("total_cases", sa.Integer(), nullable=True),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("execution_time_ms", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("results", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
    for index, cols in (
        ("ix_assessment_answers_id", ["id"]),
        ("ix_assessment_answers_assignment_id", ["assignment_id"]),
        ("ix_assessment_answers_question_id", ["question_id"]),
        (
            "ix_assessment_answers_assignment_question",
            ["assignment_id", "question_id"],
        ),
    ):
        if _index_missing(inspector, "assessment_answers", index):
            op.create_index(index, "assessment_answers", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("assessment_answers"):
        op.drop_table("assessment_answers")
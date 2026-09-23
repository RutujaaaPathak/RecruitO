"""Company Assessment Question Bank

Adds the question-bank layer of the recruitment pipeline: companies author
questions (`assessment_questions`) inside their assessment sections
(`assessment_sections`). ``question_type`` discriminates between the two
supported fulfilment engines (mcq for aptitude & technical sections, coding
for programming sections); the field contracts mirror the existing candidate
engines (``McqQuestion`` options/correct-index and ``CodingProblem``
sample/hidden cases) without touching Mock Practice rows.

One new PostgreSQL enum is created (mcq | coding). ``correct_index`` and
``hidden_cases`` stay server-side-only in the candidate-facing API.

Revision ID: 0014_assessment_question_bank
Revises: 0013_company_assessments
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0014_assessment_question_bank"
down_revision = "0013_company_assessments"
branch_labels = None
depends_on = None

_QUESTION_TYPE_ENUM = "assessmentquestiontypeenum"
_QUESTION_TYPE_VALUES = ("mcq", "coding")


def _index_missing(inspector, table, index):
    return not any(i["name"] == index for i in inspector.get_indexes(table))


def _enum_column(enum):
    """Reusable enum column that mirrors the ORM Enum default semantics.

    ``create_type=False`` so the type is created once (above) and columns only
    reference it.
    """

    return postgresql.ENUM(*enum[1], name=enum[0], create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not any(e["name"] == _QUESTION_TYPE_ENUM for e in inspector.get_enums()):
        postgresql.ENUM(*_QUESTION_TYPE_VALUES, name=_QUESTION_TYPE_ENUM).create(
            bind
        )

    if not inspector.has_table("assessment_questions"):
        op.create_table(
            "assessment_questions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "section_id",
                sa.Integer(),
                sa.ForeignKey("assessment_sections.id"),
                nullable=False,
            ),
            sa.Column(
                "question_type",
                _enum_column((_QUESTION_TYPE_ENUM, _QUESTION_TYPE_VALUES)),
                nullable=False,
            ),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("question_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "section_id",
                "question_order",
                name="uq_assessment_question_order",
            ),
            # MCQ contracts.
            sa.Column("options", sa.JSON(), nullable=True),
            sa.Column("correct_index", sa.Integer(), nullable=True),
            sa.Column("marks", sa.Integer(), nullable=True),
            sa.Column("explanation", sa.Text(), nullable=True),
            # Coding contracts.
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column("difficulty", sa.String(), nullable=True),
            sa.Column("input_format", sa.Text(), nullable=True),
            sa.Column("output_format", sa.Text(), nullable=True),
            sa.Column("constraints", sa.Text(), nullable=True),
            sa.Column("sample_cases", sa.JSON(), nullable=True),
            sa.Column("hidden_cases", sa.JSON(), nullable=True),
            sa.Column("time_limit_seconds", sa.Integer(), nullable=True),
            sa.Column("supported_languages", sa.JSON(), nullable=True),
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
        ("ix_assessment_questions_id", ["id"]),
        ("ix_assessment_questions_section_id", ["section_id"]),
        (
            "ix_assessment_questions_section_order",
            ["section_id", "question_order"],
        ),
    ):
        if _index_missing(inspector, "assessment_questions", index):
            op.create_index(index, "assessment_questions", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("assessment_questions"):
        op.drop_table("assessment_questions")

    if any(
        e["name"] == _QUESTION_TYPE_ENUM for e in inspector.get_enums()
    ):
        op.execute("DROP TYPE IF EXISTS " + _QUESTION_TYPE_ENUM)
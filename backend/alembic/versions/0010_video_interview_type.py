"""Video interview type discriminator + final report columns

Discriminates the video interview flavour (technical vs HR) so a single
application can run one live interview of each type, and stores the final
report on the session — mirroring the columns already present on the text-based
``mock_interviews`` table.

Revision ID: 0010_video_interview_type
Revises: 0009_video_interview_questions
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0010_video_interview_type"
down_revision = "0009_video_interview_questions"
branch_labels = None
depends_on = None

_TABLE = "video_interviews"


def _column_names(inspector, table):
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table(_TABLE):
        return

    columns = _column_names(inspector, _TABLE)

    # Existing sessions without a discriminator are technical interviews.
    if "interview_type" not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "interview_type",
                sa.String(20),
                nullable=False,
                server_default="technical",
            ),
        )

    # Report columns mirroring the text-based mock_interviews table.
    report_columns = {
        "overall_score": sa.Integer(),
        "category_scores": sa.JSON(),
        "strengths": sa.JSON(),
        "weaknesses": sa.JSON(),
        "recommended_topics": sa.JSON(),
        "summary": sa.Text(),
        "report": sa.JSON(),
        "report_generated_by": sa.String(),
        "report_notice": sa.Text(),
    }
    for name, type_ in report_columns.items():
        if name not in columns:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table(_TABLE):
        return

    columns = _column_names(inspector, _TABLE)
    report_columns = [
        "overall_score",
        "category_scores",
        "strengths",
        "weaknesses",
        "recommended_topics",
        "summary",
        "report",
        "report_generated_by",
        "report_notice",
    ]
    # Drops report columns first, then the discriminator, so the server default
    # backfill of interview_type is removed last.
    for name in report_columns:
        if name in columns:
            op.drop_column(_TABLE, name)

    columns = _column_names(inspector, _TABLE)
    if "interview_type" in columns:
        op.drop_column(_TABLE, "interview_type")
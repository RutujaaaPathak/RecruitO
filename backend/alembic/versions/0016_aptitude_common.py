"""Aptitude practice tests become common (section-based, application-free)

Mock Practice aptitude tests are self-practice: they must not depend on a
company, job or application. This makes ``aptitude_tests.application_id``
nullable and records which ``section`` an attempt covers ("mixed" or one of
"quantitative" / "logical_reasoning" / "verbal").

Revision ID: 0016_aptitude_common
Revises: 0015_assessment_answers
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0016_aptitude_common"
down_revision = "0015_assessment_answers"
branch_labels = None
depends_on = None


def _column(inspector, table, name):
    return next(
        (c for c in inspector.get_columns(table) if c["name"] == name), None
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("aptitude_tests"):
        return

    application_id = _column(inspector, "aptitude_tests", "application_id")
    if application_id is not None and not application_id["nullable"]:
        op.alter_column(
            "aptitude_tests",
            "application_id",
            existing_type=sa.Integer(),
            nullable=True,
        )

    if _column(inspector, "aptitude_tests", "section") is None:
        op.add_column(
            "aptitude_tests",
            sa.Column(
                "section",
                sa.String(),
                nullable=False,
                server_default="mixed",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("aptitude_tests"):
        return

    if _column(inspector, "aptitude_tests", "section") is not None:
        op.drop_column("aptitude_tests", "section")

    application_id = _column(inspector, "aptitude_tests", "application_id")
    if application_id is not None and application_id["nullable"]:
        # Rows created as common practice tests have no application; delete them
        # before restoring the NOT NULL constraint.
        op.execute("DELETE FROM aptitude_tests WHERE application_id IS NULL")
        op.alter_column(
            "aptitude_tests",
            "application_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

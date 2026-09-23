"""Company Assessments (recruitment pipeline)

Adds the catalog/assignment layer of the recruitment pipeline: a company
authors an assessment (``assessments``) made of ordered sections
(``assessment_sections``: aptitude / technical / coding / HR / technical
interview) and hands it to candidate users via ``assessment_assignments``.

Deliberately independent of Mock Practice:
  * no question bank / attempts / answers / scoring / reports here,
  * ``assessment_sections.section_type`` is a discriminator only,
  * a distinct company-facing lifecycle enum is used because the candidate
    ``assessmentstatusenum`` (in_progress/completed) expresses attempt
    progress, not company publication lifecycle.

Three new PostgreSQL enums are created (draft/published/closed assessment
status, section types, and assigned/in_progress/submitted assignment status).

Revision ID: 0013_company_assessments
Revises: 0012_notifications
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0013_company_assessments"
down_revision = "0012_notifications"
branch_labels = None
depends_on = None

_ASSESSMENT_STATUS_ENUM = "companyassessmentstatusenum"
_ASSESSMENT_STATUS_VALUES = ("draft", "published", "closed")

_SECTION_TYPE_ENUM = "assessmentsectiontypeenum"
_SECTION_TYPE_VALUES = (
    "aptitude",
    "technical",
    "coding",
    "hr",
    "technical_interview",
)

_ASSIGNMENT_STATUS_ENUM = "assessmentassignmentstatusenum"
_ASSIGNMENT_STATUS_VALUES = ("assigned", "in_progress", "submitted")


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

    for enum in (
        (_ASSESSMENT_STATUS_ENUM, _ASSESSMENT_STATUS_VALUES),
        (_SECTION_TYPE_ENUM, _SECTION_TYPE_VALUES),
        (_ASSIGNMENT_STATUS_ENUM, _ASSIGNMENT_STATUS_VALUES),
    ):
        if not any(e["name"] == enum[0] for e in inspector.get_enums()):
            postgresql.ENUM(*enum[1], name=enum[0]).create(bind)

    if not inspector.has_table("assessments"):
        op.create_table(
            "assessments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "company_id",
                sa.Integer(),
                sa.ForeignKey("companies.id"),
                nullable=False,
            ),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("instructions", sa.Text(), nullable=True),
            sa.Column(
                "status",
                _enum_column((_ASSESSMENT_STATUS_ENUM, _ASSESSMENT_STATUS_VALUES)),
                nullable=False,
            ),
            sa.Column("duration_minutes", sa.Integer(), nullable=True),
            sa.Column("starts_at", sa.DateTime(), nullable=True),
            sa.Column("ends_at", sa.DateTime(), nullable=True),
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
        ("ix_assessments_id", ["id"]),
        ("ix_assessments_company_id", ["company_id"]),
        ("ix_assessments_company_status", ["company_id", "status"]),
    ):
        if _index_missing(inspector, "assessments", index):
            op.create_index(index, "assessments", cols)

    if not inspector.has_table("assessment_sections"):
        op.create_table(
            "assessment_sections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "assessment_id",
                sa.Integer(),
                sa.ForeignKey("assessments.id"),
                nullable=False,
            ),
            sa.Column(
                "section_type",
                _enum_column((_SECTION_TYPE_ENUM, _SECTION_TYPE_VALUES)),
                nullable=False,
            ),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("section_order", sa.Integer(), nullable=False),
            sa.Column("marks", sa.Integer(), nullable=True),
            sa.Column("settings", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "assessment_id",
                "section_order",
                name="uq_assessment_section_order",
            ),
        )
    for index, cols in (
        ("ix_assessment_sections_id", ["id"]),
        ("ix_assessment_sections_assessment_id", ["assessment_id"]),
        (
            "ix_assessment_sections_assessment_order",
            ["assessment_id", "section_order"],
        ),
    ):
        if _index_missing(inspector, "assessment_sections", index):
            op.create_index(index, "assessment_sections", cols)

    if not inspector.has_table("assessment_assignments"):
        op.create_table(
            "assessment_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "assessment_id",
                sa.Integer(),
                sa.ForeignKey("assessments.id"),
                nullable=False,
            ),
            sa.Column(
                "candidate_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "status",
                _enum_column((_ASSIGNMENT_STATUS_ENUM, _ASSIGNMENT_STATUS_VALUES)),
                nullable=False,
            ),
            sa.Column("assigned_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint(
                "assessment_id",
                "candidate_id",
                name="uq_assessment_assignment_candidate",
            ),
        )
    for index, cols in (
        ("ix_assessment_assignments_id", ["id"]),
        ("ix_assessment_assignments_assessment_id", ["assessment_id"]),
        ("ix_assessment_assignments_candidate_id", ["candidate_id"]),
        (
            "ix_assessment_assignments_candidate_status",
            ["candidate_id", "status"],
        ),
    ):
        if _index_missing(inspector, "assessment_assignments", index):
            op.create_index(index, "assessment_assignments", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("assessment_assignments"):
        op.drop_table("assessment_assignments")
    if inspector.has_table("assessment_sections"):
        op.drop_table("assessment_sections")
    if inspector.has_table("assessments"):
        op.drop_table("assessments")

    for enum in (
        _ASSIGNMENT_STATUS_ENUM,
        _SECTION_TYPE_ENUM,
        _ASSESSMENT_STATUS_ENUM,
    ):
        if any(e["name"] == enum for e in inspector.get_enums()):
            op.execute("DROP TYPE IF EXISTS " + enum)

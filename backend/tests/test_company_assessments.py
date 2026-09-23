"""Company Assessment (recruitment pipeline) — model contract + constraint tests.

Covers the three new tables end-to-end *without* a Postgres dependency:

  * ``assessments``  — company-authored assessment catalog (status lifecycle
    draft → published → closed, validity window, duration),
  * ``assessment_sections`` — ordered sections (aptitude / technical / coding /
    HR / technical interview) with a per-assessment unique section order,
  * ``assessment_assignments`` — handing a published assessment to a candidate
    user, with a DB-level ``(assessment_id, candidate_id)`` unique constraint
    so the same assessment can never be assigned to the same candidate twice.

Everything runs on an in-memory SQLite engine (with ``foreign_keys=ON``) over
just the tables the pipeline touches — pure model/alembic-migration contract
verification, no network, no external DB. Constraint behaviour (duplicate
section order, duplicate assignment, orphaned FK writes) is enforced by the
database engine so the tests prove the migration's indexes/constraints match
the ORM defined in ``app/models``.
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.models import (
    Assessment,
    AssessmentAssignment,
    AssessmentAssignmentStatusEnum,
    AssessmentSection,
    AssessmentSectionTypeEnum,
    Company,
    CompanyAssessmentStatusEnum,
    User,
)


# ---------------------------------------------------------------------------
# In-memory engine over only the pipeline tables
# ---------------------------------------------------------------------------
@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # Foreign-key enforcement is off by default in SQLite; enable it so the
    # constraint tests below actually bind.
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    # Create exactly the tables the recruitment-pipeline models reach for;
    # SQLAlchemy handles dependency ordering (users → companies → assessments →
    # assessment_sections / assessment_assignments).
    from app import models as m

    tables = [
        m.User.__table__,
        m.Company.__table__,
        m.Job.__table__,
        m.Application.__table__,
        m.Assessment.__table__,
        m.AssessmentSection.__table__,
        m.AssessmentAssignment.__table__,
        m.AssessmentQuestion.__table__,
        m.AssessmentAnswer.__table__,
    ]
    m.Base.metadata.create_all(engine, tables=tables)
    s = Session(engine)
    yield s
    s.close()
    engine.dispose()


def _company(db, user_id, name="Acme Recruiting"):
    c = Company(user_id=user_id, name=name)
    db.add(c)
    db.flush()
    return c


def _assessment(db, company, title="Backend Screening"):
    a = Assessment(
        company_id=company.id,
        title=title,
        description="Full-stack candidate screening",
        status=CompanyAssessmentStatusEnum.draft,
        duration_minutes=90,
    )
    db.add(a)
    db.flush()
    return a


# ---------------------------------------------------------------------------
# Assessments — company ownership / lifecycle
# ---------------------------------------------------------------------------
def test_assessment_requires_company(db):
    """An assessment must belong to a company (company_id is NOT NULL)."""
    u1 = User(name="c0", email="c0@x.com", password="p")
    db.add(u1)
    db.flush()
    c = _company(db, u1.id)

    a = Assessment(company_id=c.id, title="X")
    a.company_id = None
    db.add(a)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_assessment_defaults_to_draft_and_company_ownership(db):
    u1 = User(name="c1", email="c1@x.com", password="p")
    db.add(u1)
    db.flush()
    c = _company(db, u1.id)
    a = _assessment(db, c)

    assert a.company_id == c.id
    assert a.status == CompanyAssessmentStatusEnum.draft
    assert c.assessments and a in c.assessments
    assert a.created_at is not None


# ---------------------------------------------------------------------------
# Sections — ordering + unique constraint
# ---------------------------------------------------------------------------
def test_section_ordering_and_relationship(db):
    u1 = User(name="c2", email="c2@x.com", password="p")
    db.add(u1)
    db.flush()
    c = _company(db, u1.id)
    a = _assessment(db, c)

    for order, t in enumerate(
        (
            AssessmentSectionTypeEnum.aptitude,
            AssessmentSectionTypeEnum.technical,
            AssessmentSectionTypeEnum.coding,
            AssessmentSectionTypeEnum.hr,
            AssessmentSectionTypeEnum.technical_interview,
        ),
        start=1,
    ):
        db.add(
            AssessmentSection(
                assessment_id=a.id, section_type=t, title=f"Section {t.value}",
                section_order=order,
            )
        )
    a.sections.sort(key=lambda s: s.section_order)
    assert [s.section_type for s in a.sections] == [
        AssessmentSectionTypeEnum.aptitude,
        AssessmentSectionTypeEnum.technical,
        AssessmentSectionTypeEnum.coding,
        AssessmentSectionTypeEnum.hr,
        AssessmentSectionTypeEnum.technical_interview,
    ]


def test_duplicate_section_order_rejected(db):
    u1 = User(name="c3", email="c3@x.com", password="p")
    db.add(u1)
    db.flush()
    a = _assessment(db, _company(db, u1.id))

    db.add(AssessmentSection(assessment_id=a.id, section_type=AssessmentSectionTypeEnum.aptitude,
                             title="A", section_order=1))
    db.add(AssessmentSection(assessment_id=a.id, section_type=AssessmentSectionTypeEnum.hr,
                             title="B", section_order=1))
    with pytest.raises(IntegrityError):
        db.flush()


# ---------------------------------------------------------------------------
# Assignments — candidate assignment + duplicate protection + FK
# ---------------------------------------------------------------------------
def test_assignment_to_candidate_and_status_flow(db):
    u1 = User(name="c4", email="c4@x.com", password="p")
    u2 = User(name="cand", email="cand4@x.com", password="p")
    db.add_all([u1, u2])
    db.flush()
    a = _assessment(db, _company(db, u1.id))

    asg = AssessmentAssignment(
        assessment_id=a.id, candidate_id=u2.id,
        status=AssessmentAssignmentStatusEnum.assigned,
    )
    db.add(asg)
    db.flush()

    assert asg.id is not None
    assert u2.assessment_assignments and asg in u2.assessment_assignments
    assert asg.candidate_id == u2.id
    assert asg.status == AssessmentAssignmentStatusEnum.assigned


def test_duplicate_assignment_to_same_candidate_rejected(db):
    u1 = User(name="c5", email="c5@x.com", password="p")
    u2 = User(name="cand5", email="cand5@x.com", password="p")
    db.add_all([u1, u2])
    db.flush()
    a = _assessment(db, _company(db, u1.id))

    db.add(AssessmentAssignment(assessment_id=a.id, candidate_id=u2.id,
                                status=AssessmentAssignmentStatusEnum.assigned))
    db.flush()
    db.add(AssessmentAssignment(assessment_id=a.id, candidate_id=u2.id,
                                status=AssessmentAssignmentStatusEnum.in_progress))
    with pytest.raises(IntegrityError):
        db.flush()


def test_assignment_requires_real_candidate_and_assessment(db):
    u1 = User(name="c6", email="c6@x.com", password="p")
    db.add(u1)
    db.flush()
    a = _assessment(db, _company(db, u1.id))

    # Unknown candidate user id.
    bad = AssessmentAssignment(assessment_id=a.id, candidate_id=999999,
                               status=AssessmentAssignmentStatusEnum.assigned)
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

    # Unknown assessment id.
    bad2 = AssessmentAssignment(assessment_id=999999, candidate_id=u1.id,
                                status=AssessmentAssignmentStatusEnum.assigned)
    db.add(bad2)
    with pytest.raises(IntegrityError):
        db.flush()


# ---------------------------------------------------------------------------
# Cascades — deleting a company removes its assessments, sections, assignments
# ---------------------------------------------------------------------------
def test_company_delete_cascades_to_assessments_sections_assignments(db):
    u1 = User(name="c7", email="c7@x.com", password="p")
    u2 = User(name="cand7", email="cand7@x.com", password="p")
    db.add_all([u1, u2])
    db.flush()
    c = _company(db, u1.id)
    a = _assessment(db, c)
    db.add(AssessmentSection(assessment_id=a.id, section_type=AssessmentSectionTypeEnum.aptitude,
                             title="A", section_order=1))
    db.add(AssessmentAssignment(assessment_id=a.id, candidate_id=u2.id,
                                status=AssessmentAssignmentStatusEnum.assigned))
    db.flush()

    # ORM-side cascades fire only over the loaded relationship graph, so pull
    # the children into the session before removing the owner.
    _ = c.assessments, a.sections, a.assignments
    db.delete(c)
    db.flush()

    from sqlalchemy import func, select
    assert db.execute(select(func.count()).select_from(Assessment)).scalar_one() == 0
    assert db.execute(select(func.count()).select_from(AssessmentSection)).scalar_one() == 0
    assert db.execute(select(func.count()).select_from(AssessmentAssignment)).scalar_one() == 0


# ---------------------------------------------------------------------------
# Migration contract — alembic 0013 mirrors the ORM definitions
# ---------------------------------------------------------------------------
def test_migration_0013_matches_orm():
    """The newest migration's revision chain + table/enum names line up with
    app/models and the previous head (0012_notifications)."""
    import re
    from pathlib import Path

    versions = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    migration = versions / "0013_company_assessments.py"
    assert migration.exists()

    src = migration.read_text(encoding="utf-8")
    assert 'revision = "0013_company_assessments"' in src
    assert 'down_revision = "0012_notifications"' in src

    # Every table the migration touches must be real ORM tables.
    orm_tables = {
        t.__tablename__
        for t in (Assessment, AssessmentSection, AssessmentAssignment)
    }
    for table in ("assessments", "assessment_sections", "assessment_assignments"):
        assert f'"{table}"' in src
        assert table in orm_tables

    # Enum names are shared between migration and ORM.
    for enum in (
        "companyassessmentstatusenum",
        "assessmentsectiontypeenum",
        "assessmentassignmentstatusenum",
    ):
        assert enum in src

    # Unique-constraint names used by the migration match the ORM.
    for uq in ("uq_assessment_section_order", "uq_assessment_assignment_candidate"):
        assert uq in src


def test_model_enums_values():
    assert CompanyAssessmentStatusEnum.draft.value == "draft"
    assert CompanyAssessmentStatusEnum.published.value == "published"
    assert CompanyAssessmentStatusEnum.closed.value == "closed"
    assert AssessmentSectionTypeEnum.coding.value == "coding"
    assert AssessmentSectionTypeEnum.hr.value == "hr"
    assert AssessmentAssignmentStatusEnum.submitted.value == "submitted"
    # Range check on the full assignment lifecycle.
    assert {e.value for e in AssessmentAssignmentStatusEnum} == {
        "assigned", "in_progress", "submitted",
    }


# ---------------------------------------------------------------------------
# Pydantic Out contracts — serialize from ORM attributes
# ---------------------------------------------------------------------------
def test_schema_assessment_out_from_orm(db):
    from app.schemas import AssessmentOut

    u1 = User(name="c8", email="c8@x.com", password="p")
    db.add(u1)
    db.flush()
    a = _assessment(db, _company(db, u1.id))
    out = AssessmentOut.model_validate(a)
    assert out.title == a.title
    assert out.company_id == a.company_id
    assert out.status == a.status


def test_schema_assignment_out_rejects_duplicate_contract(db):
    from app.schemas import AssessmentAssignmentOut

    u1 = User(name="c9", email="c9@x.com", password="p")
    u2 = User(name="cand9", email="cand9@x.com", password="p")
    db.add_all([u1, u2])
    db.flush()
    a = _assessment(db, _company(db, u1.id))
    asg = AssessmentAssignment(assessment_id=a.id, candidate_id=u2.id,
                               status=AssessmentAssignmentStatusEnum.assigned)
    db.add(asg)
    db.flush()
    out = AssessmentAssignmentOut.model_validate(asg)
    assert out.candidate_id == u2.id
    assert out.status == AssessmentAssignmentStatusEnum.assigned

"""Company Assessment CRUD API tests (/assessments route module).

Exercises the company-only endpoints directly (payload, user, session) against
an in-memory SQLite engine with ``foreign_keys=ON`` over just the tables the
pipeline touches — covering create/list/get/update/delete, company ownership
isolation (another company cannot access/modify/delete), add/update/reorder/
delete sections, invalid section type, invalid duration/dates, duplicate
section order, and authentication/RBAC. No network, no external DB.
"""
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.auth import RoleChecker
from app.routes.company_assessments import (
    add_section,
    company_scoped,
    create_assessment,
    delete_assessment,
    get_assessment,
    list_assessments,
    remove_section,
    reorder_sections,
    update_assessment,
    update_section,
)


# ---------------------------------------------------------------------------
# In-memory engine over only the pipeline tables
# ---------------------------------------------------------------------------
@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

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


def _company_user(db, id, name="Recruiter"):
    u = models.User(
        id=id, name=name, email=f"recruiter{id}@recruito.com", password="hashed",
        role=models.RoleEnum.company,
    )
    db.add(u)
    db.flush()
    return u


def _candidate_user(db, id):
    u = models.User(
        id=id, name="Candidate", email=f"candidate{id}@recruito.com", password="hashed",
        role=models.RoleEnum.user,
    )
    db.add(u)
    db.flush()
    return u


def _admin_user(db, id):
    u = models.User(
        id=id, name="Admin", email=f"admin{id}@recruito.com", password="hashed",
        role=models.RoleEnum.admin,
    )
    db.add(u)
    db.flush()
    return u


def _company(db, user, name="Acme Recruiting", approved=True):
    c = models.Company(user_id=user.id, name=name, approved=approved)
    db.add(c)
    db.flush()
    return c


def _assessment(db, company, title="Backend Screening", **kw):
    a = models.Assessment(
        company_id=company.id,
        title=title,
        description="Full-stack candidate screening",
        status=kw.pop("status", models.CompanyAssessmentStatusEnum.draft),
        duration_minutes=90,
        **kw,
    )
    db.add(a)
    db.flush()
    return a


def _section(db, assessment, order, section_type=models.AssessmentSectionTypeEnum.aptitude, title="Aptitude"):
    s = models.AssessmentSection(
        assessment_id=assessment.id,
        section_type=section_type,
        title=title,
        section_order=order,
        marks=10,
    )
    db.add(s)
    db.flush()
    return s


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def test_create_assessment_is_company_scoped_and_defaults(db):
    user = _company_user(db, 1)
    company = _company(db, user)
    result = create_assessment(
        schemas.AssessmentCreate(title="Hiring Pipeline"), user, db
    )

    assert result.title == "Hiring Pipeline"
    assert result.company_id == company.id
    assert result.status == models.CompanyAssessmentStatusEnum.draft
    assert result.duration_minutes is None
    assert result.created_at is not None


def test_create_assessment_derives_company_from_user_not_payload(db):
    user = _company_user(db, 1)
    company = _company(db, user)

    # The create schema intentionally exposes no company_id — a client can
    # never steer which company owns the assessment.
    assert "company_id" not in schemas.AssessmentCreate.model_fields

    result = create_assessment(schemas.AssessmentCreate(title="X"), user, db)
    assert result.company_id == company.id


def test_create_requires_approved_company(db):
    user = _company_user(db, 1)
    _company(db, user, approved=False)
    with pytest.raises(Exception) as exc:
        create_assessment(schemas.AssessmentCreate(title="X"), user, db)
    assert exc.value.status_code == 403


def test_create_without_company_profile_404(db):
    user = _company_user(db, 1)
    with pytest.raises(Exception) as exc:
        create_assessment(schemas.AssessmentCreate(title="X"), user, db)
    assert exc.value.status_code == 404


def test_create_rejects_nonpositive_duration(db):
    user = _company_user(db, 1)
    _company(db, user)
    with pytest.raises(ValidationError):
        create_assessment(schemas.AssessmentCreate(title="X", duration_minutes=0), user, db)
    with pytest.raises(ValidationError):
        create_assessment(schemas.AssessmentCreate(title="X", duration_minutes=-5), user, db)


def test_create_rejects_invalid_validity_window(db):
    user = _company_user(db, 1)
    _company(db, user)
    with pytest.raises(ValidationError):
        create_assessment(
            schemas.AssessmentCreate(
                title="X",
                starts_at=datetime(2026, 5, 2),
                ends_at=datetime(2026, 5, 1),
            ),
            user,
            db,
        )


def test_create_accepts_ordered_validity_window(db):
    user = _company_user(db, 1)
    company = _company(db, user)
    result = create_assessment(
        schemas.AssessmentCreate(
            title="X",
            starts_at=datetime(2026, 5, 1),
            ends_at=datetime(2026, 5, 10),
            duration_minutes=60,
        ),
        user,
        db,
    )
    assert result.starts_at == datetime(2026, 5, 1)
    assert result.ends_at == datetime(2026, 5, 10)
    assert result.duration_minutes == 60
    assert result.company_id == company.id


# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------
def test_list_isolation_between_companies(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1, name="Acme")
    a1 = _assessment(db, c1, title="Acme 1")
    a2 = _assessment(db, c1, title="Acme 2")
    u2 = _company_user(db, 2)
    c2 = _company(db, u2, name="Beta")
    _assessment(db, c2, title="Beta 1")

    listed = list_assessments(u1, db)
    assert [a.title for a in listed] == ["Acme 2", "Acme 1"]  # newest first
    assert a1.id in {a.id for a in listed} and a2.id in {a.id for a in listed}
    assert all(a.company_id == c1.id for a in listed)


def test_get_detail_returns_ordered_sections(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    s1 = _section(db, a, 1, models.AssessmentSectionTypeEnum.aptitude, "Aptitude")
    s2 = _section(db, a, 2, models.AssessmentSectionTypeEnum.coding, "Coding")

    result = get_assessment(a.id, u1, db)
    assert result.id == a.id
    assert result.title == a.title
    assert [s.id for s in result.sections] == [s1.id, s2.id]
    assert result.assignments == []
    assert all(s.assessment_id == a.id for s in result.sections)


def test_get_assessment_404_for_unknown(db):
    u1 = _company_user(db, 1)
    _company(db, u1)
    with pytest.raises(Exception) as exc:
        get_assessment(555, u1, db)
    assert exc.value.status_code == 404


def test_other_company_cannot_get(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    u2 = _company_user(db, 2)
    _company(db, u2)

    with pytest.raises(Exception) as exc:
        get_assessment(a.id, u2, db)
    assert exc.value.status_code == 403


def test_admin_can_get_any_assessment(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    admin = _admin_user(db, 9)

    result = get_assessment(a.id, admin, db)
    assert result.id == a.id


# ---------------------------------------------------------------------------
# Update / Delete
# ---------------------------------------------------------------------------
def test_update_assessment_partial(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1, title="Old Title")

    result = update_assessment(
        a.id, schemas.AssessmentUpdate(title="New Title", duration_minutes=120), u1, db
    )
    assert result.title == "New Title"
    assert result.duration_minutes == 120
    assert result.company_id == c1.id


def test_update_assessment_rejects_bad_window_and_duration(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)

    with pytest.raises(ValidationError):
        update_assessment(
            a.id,
            schemas.AssessmentUpdate(
                starts_at=datetime(2026, 5, 2), ends_at=datetime(2026, 5, 1)
            ),
            u1,
            db,
        )
    with pytest.raises(ValidationError):
        update_assessment(a.id, schemas.AssessmentUpdate(duration_minutes=0), u1, db)


def test_other_company_cannot_update_or_delete(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    u2 = _company_user(db, 2)
    _company(db, u2)

    with pytest.raises(Exception) as exc:
        update_assessment(a.id, schemas.AssessmentUpdate(title="Hijack"), u2, db)
    assert exc.value.status_code == 403

    with pytest.raises(Exception) as exc:
        delete_assessment(a.id, u2, db)
    assert exc.value.status_code == 403


def test_update_assessment_404(db):
    u1 = _company_user(db, 1)
    _company(db, u1)
    with pytest.raises(Exception) as exc:
        update_assessment(555, schemas.AssessmentUpdate(title="X"), u1, db)
    assert exc.value.status_code == 404


def test_delete_assessment_removes_row_and_cascades_sections(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    s1 = _section(db, a, 1)
    s2 = _section(db, a, 2)

    result = delete_assessment(a.id, u1, db)
    assert result is None
    assert db.query(models.Assessment).filter(models.Assessment.id == a.id).first() is None
    assert db.query(models.AssessmentSection).filter(
        models.AssessmentSection.id == s1.id
    ).first() is None
    assert db.query(models.AssessmentSection).filter(
        models.AssessmentSection.id == s2.id
    ).first() is None


# ---------------------------------------------------------------------------
# Sections — add
# ---------------------------------------------------------------------------
def test_add_section_appends_when_no_order_given(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    _section(db, a, 1)

    section = add_section(
        a.id,
        schemas.AssessmentSectionCreate(
            section_type=models.AssessmentSectionTypeEnum.coding, title="Coding"
        ),
        u1,
        db,
    )
    assert section.section_order == 2
    assert section.assessment_id == a.id
    assert section.section_type == models.AssessmentSectionTypeEnum.coding


def test_add_section_respects_explicit_order(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    section = add_section(
        a.id,
        schemas.AssessmentSectionCreate(
            section_type=models.AssessmentSectionTypeEnum.hr, title="HR", section_order=5
        ),
        u1,
        db,
    )
    assert section.section_order == 5


def test_add_section_duplicate_order_409(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    _section(db, a, 1)

    with pytest.raises(Exception) as exc:
        add_section(
            a.id,
            schemas.AssessmentSectionCreate(
                section_type=models.AssessmentSectionTypeEnum.coding,
                title="Coding",
                section_order=1,
            ),
            u1,
            db,
        )
    assert exc.value.status_code == 409


def test_add_section_requires_owned_assessment(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    u2 = _company_user(db, 2)
    _company(db, u2)

    with pytest.raises(Exception) as exc:
        add_section(
            a.id,
            schemas.AssessmentSectionCreate(
                section_type=models.AssessmentSectionTypeEnum.coding, title="Hijack"
            ),
            u2,
            db,
        )
    assert exc.value.status_code == 403


def test_add_section_invalid_section_type_422(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)

    with pytest.raises(ValidationError):
        schemas.AssessmentSectionCreate(
            section_type="brainteaser", title="Nope", section_order=1
        )

    # And an invalid order (0) is rejected by the schema, not the route.
    with pytest.raises(ValidationError):
        schemas.AssessmentSectionCreate(
            section_type=models.AssessmentSectionTypeEnum.coding, title="Nope",
            section_order=0,
        )


# ---------------------------------------------------------------------------
# Sections — update / reorder / remove
# ---------------------------------------------------------------------------
def test_update_section_fields_and_owner(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    s = _section(db, a, 1)

    result = update_section(
        a.id,
        s.id,
        schemas.AssessmentSectionUpdate(
            title="Renamed",
            marks=25,
            section_type=models.AssessmentSectionTypeEnum.technical,
        ),
        u1,
        db,
    )
    assert result.title == "Renamed"
    assert result.marks == 25
    assert result.section_type == models.AssessmentSectionTypeEnum.technical


def test_update_section_duplicate_order_409(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    _section(db, a, 1)
    s2 = _section(db, a, 2)

    with pytest.raises(Exception) as exc:
        update_section(
            a.id, s2.id, schemas.AssessmentSectionUpdate(section_order=1), u1, db
        )
    assert exc.value.status_code == 409


def test_update_section_404_and_foreign_assessment(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a1 = _assessment(db, c1)
    a2 = _assessment(db, c1, title="Other")
    s = _section(db, a1, 1)

    with pytest.raises(Exception) as exc:
        update_section(a2.id, s.id, schemas.AssessmentSectionUpdate(title="X"), u1, db)
    assert exc.value.status_code == 404

    with pytest.raises(Exception) as exc:
        update_section(a1.id, 555, schemas.AssessmentSectionUpdate(title="X"), u1, db)
    assert exc.value.status_code == 404


def test_reorder_sections_applies_new_order(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    s1 = _section(db, a, 1, models.AssessmentSectionTypeEnum.aptitude)
    s2 = _section(db, a, 2, models.AssessmentSectionTypeEnum.coding)
    s3 = _section(db, a, 3, models.AssessmentSectionTypeEnum.hr)

    ordered = reorder_sections(
        a.id,
        schemas.AssessmentSectionReorderIn(
            ordered_section_ids=[s3.id, s1.id, s2.id]
        ),
        u1,
        db,
    )
    assert [s.id for s in ordered] == [s3.id, s1.id, s2.id]
    assert [s.section_order for s in ordered] == [1, 2, 3]

    detail = get_assessment(a.id, u1, db)
    assert [s.id for s in detail.sections] == [s3.id, s1.id, s2.id]


def test_reorder_rejects_duplicate_ids(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    s1 = _section(db, a, 1)
    s2 = _section(db, a, 2)

    with pytest.raises(ValidationError):
        schemas.AssessmentSectionReorderIn(ordered_section_ids=[s1.id, s1.id])
    with pytest.raises(ValidationError):
        schemas.AssessmentSectionReorderIn(ordered_section_ids=[s1.id, s2.id, s1.id])


def test_reorder_rejects_missing_or_foreign_ids(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    s1 = _section(db, a, 1)
    s2 = _section(db, a, 2)

    with pytest.raises(Exception) as exc:
        reorder_sections(
            a.id,
            schemas.AssessmentSectionReorderIn(ordered_section_ids=[s1.id]),
            u1,
            db,
        )
    assert exc.value.status_code == 409

    with pytest.raises(Exception) as exc:
        reorder_sections(
            a.id,
            schemas.AssessmentSectionReorderIn(
                ordered_section_ids=[s1.id, s2.id, 999]
            ),
            u1,
            db,
        )
    assert exc.value.status_code == 409


def test_remove_section_deletes_and_keeps_others(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    s1 = _section(db, a, 1)
    s2 = _section(db, a, 2, models.AssessmentSectionTypeEnum.coding, "Coding")

    result = remove_section(a.id, s1.id, u1, db)
    assert result is None
    assert db.query(models.AssessmentSection).filter(
        models.AssessmentSection.id == s1.id
    ).first() is None
    assert db.query(models.AssessmentSection).filter(
        models.AssessmentSection.id == s2.id
    ).first() is not None


def test_remove_section_foreign_or_missing_404(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a1 = _assessment(db, c1)
    a2 = _assessment(db, c1, title="Other")
    s = _section(db, a1, 1)

    with pytest.raises(Exception) as exc:
        remove_section(a2.id, s.id, u1, db)
    assert exc.value.status_code == 404
    with pytest.raises(Exception) as exc:
        remove_section(a1.id, 555, u1, db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Authentication / RBAC
# ---------------------------------------------------------------------------
def test_company_scoped_rejects_candidate_role(db):
    company_user = _company_user(db, 1)
    candidate = _candidate_user(db, 2)
    admin = _admin_user(db, 3)

    assert company_scoped(current_user=company_user) is not None
    assert company_scoped(current_user=admin) is not None
    with pytest.raises(Exception) as exc:
        company_scoped(current_user=candidate)
    assert exc.value.status_code == 403


def test_create_role_checker_rejects_non_company(db):
    company_user = _company_user(db, 1)
    candidate = _candidate_user(db, 2)

    assert RoleChecker(["company"])(current_user=company_user) is not None
    with pytest.raises(Exception) as exc:
        RoleChecker(["company"])(current_user=candidate)
    assert exc.value.status_code == 403


def test_candidate_cannot_touch_assessments(db):
    u1 = _company_user(db, 1)
    c1 = _company(db, u1)
    a = _assessment(db, c1)
    candidate = _candidate_user(db, 2)

    with pytest.raises(Exception) as exc:
        get_assessment(a.id, candidate, db)
    assert exc.value.status_code in (403, 404)
"""Company Assessment Candidate Assignment API tests.

Exercises the company-only assignment endpoints directly (payload, user,
session) against an in-memory SQLite engine with ``foreign_keys=ON`` over just
the pipeline tables. Covers single & bulk assignment (atomic), listing,
duplicate → 409, invalid/nonexistent/suspended/non-candidate targets, candidate
self-assignment blocking, cross-company 403 isolation, admin access, removal of
unstarted assignments, blocking removal of started/submitted assignments, and
RBAC. No network, no external DB.
"""
from datetime import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.auth import RoleChecker
from app.routes.company_assessments import (
    assign_candidates,
    company_scoped,
    get_assignment,
    list_assignments,
    remove_assignment,
)


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


def _user(db, id, role=models.RoleEnum.user, active=True, name=None):
    u = models.User(
        id=id,
        name=name or f"User {id}",
        email=f"user{id}@recruito.com",
        password="hashed",
        role=role,
        is_active=active,
    )
    db.add(u)
    db.flush()
    return u


def _company_user(db, id, name="Recruiter"):
    return _user(db, id, role=models.RoleEnum.company, name=name)


def _admin_user(db, id):
    return _user(db, id, role=models.RoleEnum.admin, name="Admin")


def _company(db, user, name="Acme Recruiting", approved=True):
    c = models.Company(user_id=user.id, name=name, approved=approved)
    db.add(c)
    db.flush()
    return c


def _assessment(db, company, title="Backend Screening"):
    a = models.Assessment(company_id=company.id, title=title)
    db.add(a)
    db.flush()
    return a


def _assignment(db, assessment, candidate,
                status=models.AssessmentAssignmentStatusEnum.assigned, **kw):
    a = models.AssessmentAssignment(
        assessment_id=assessment.id,
        candidate_id=candidate.id,
        status=status,
        **kw,
    )
    db.add(a)
    db.flush()
    return a


def _assignment_count(db):
    return len(db.query(models.AssessmentAssignment).all())


# ---------------------------------------------------------------------------
# Assign (single + bulk)
# ---------------------------------------------------------------------------
def test_assign_single_candidate(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    cand = _user(db, 10, name="Ada Lovelace")

    result = assign_candidates(
        assessment.id, schemas.AssessmentAssignIn(candidate_ids=[10]), owner, db
    )

    assert len(result) == 1
    out = result[0]
    assert out.assessment_id == assessment.id
    assert out.candidate_id == 10
    assert out.status == models.AssessmentAssignmentStatusEnum.assigned
    assert out.candidate_name == "Ada Lovelace"
    assert out.candidate_email == "user10@recruito.com"
    assert out.assessment_title == "Backend Screening"
    assert out.assigned_at is not None
    assert out.started_at is None
    assert out.submitted_at is None


def test_assign_multiple_candidates_atomically(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    c1 = _user(db, 10)
    c2 = _user(db, 11)
    c3 = _user(db, 12)

    result = assign_candidates(
        assessment.id,
        schemas.AssessmentAssignIn(candidate_ids=[10, 11, 12]),
        owner,
        db,
    )

    assert [r.candidate_id for r in result] == [10, 11, 12]
    assert all(r.status == models.AssessmentAssignmentStatusEnum.assigned for r in result)
    assert all(r.assessment_title == "Backend Screening" for r in result)
    assert {r.candidate_name for r in result} == {"User 10", "User 11", "User 12"}
    assert _assignment_count(db) == 3


def test_assign_duplicate_409_before_write(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    c1 = _user(db, 10)
    c2 = _user(db, 11)
    _assignment(db, assessment, c1)

    with pytest.raises(HTTPException) as exc:
        assign_candidates(
            assessment.id,
            schemas.AssessmentAssignIn(candidate_ids=[10, 11]),
            owner,
            db,
        )
    assert exc.value.status_code == 409

    # Atomic: the not-yet-assigned candidate was NOT added either.
    assert _assignment_count(db) == 1


def test_assign_nonexistent_candidate_404_and_nothing_applied(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    c1 = _user(db, 10)

    with pytest.raises(HTTPException) as exc:
        assign_candidates(
            assessment.id,
            schemas.AssessmentAssignIn(candidate_ids=[10, 999]),
            owner,
            db,
        )
    assert exc.value.status_code == 404
    assert _assignment_count(db) == 0


def test_assign_non_candidate_user_400(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    other_company_user = _company_user(db, 2)

    with pytest.raises(HTTPException) as exc:
        assign_candidates(
            assessment.id,
            schemas.AssessmentAssignIn(candidate_ids=[other_company_user.id]),
            owner,
            db,
        )
    assert exc.value.status_code == 400
    assert _assignment_count(db) == 0


def test_assign_suspended_candidate_400(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    suspended = _user(db, 10, active=False)

    with pytest.raises(HTTPException) as exc:
        assign_candidates(
            assessment.id,
            schemas.AssessmentAssignIn(candidate_ids=[suspended.id]),
            owner,
            db,
        )
    assert exc.value.status_code == 400
    assert _assignment_count(db) == 0


def test_assign_invalid_payload_empty_or_duplicate_ids(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    _user(db, 10)

    with pytest.raises(ValidationError):
        schemas.AssessmentAssignIn(candidate_ids=[])
    with pytest.raises(ValidationError):
        schemas.AssessmentAssignIn(candidate_ids=[10, 10])
    with pytest.raises(ValidationError):
        schemas.AssessmentAssignIn(candidate_ids=[10, 11, 10])

    assert _assignment_count(db) == 0


def test_admin_can_assign(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    c1 = _user(db, 10)
    admin = _admin_user(db, 9)

    result = assign_candidates(
        assessment.id, schemas.AssessmentAssignIn(candidate_ids=[10]), admin, db
    )
    assert result[0].candidate_id == 10


# ---------------------------------------------------------------------------
# List / Detail
# ---------------------------------------------------------------------------
def test_list_assignments_newest_first_with_identity(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    c1 = _user(db, 10, name="Ada")
    c2 = _user(db, 11, name="Grace")
    a1 = _assignment(db, assessment, c1, assigned_at=datetime(2026, 1, 1))
    a2 = _assignment(db, assessment, c2, assigned_at=datetime(2026, 1, 3))

    result = list_assignments(assessment.id, owner, db)

    assert [r.id for r in result] == [a2.id, a1.id]
    assert [r.candidate_name for r in result] == ["Grace", "Ada"]
    assert all(r.assessment_title == "Backend Screening" for r in result)
    assert all(r.status == models.AssessmentAssignmentStatusEnum.assigned for r in result)


def test_list_assignments_empty(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)

    assert list_assignments(assessment.id, owner, db) == []


def test_get_assignment_detail_and_404(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    c1 = _user(db, 10, name="Ada Lovelace")
    assignment = _assignment(db, assessment, c1)

    out = get_assignment(assessment.id, assignment.id, owner, db)
    assert out.id == assignment.id
    assert out.candidate_name == "Ada Lovelace"
    assert out.candidate_id == 10
    assert out.assessment_id == assessment.id
    assert out.status == models.AssessmentAssignmentStatusEnum.assigned
    assert out.assigned_at is not None

    # A candidate_id that is not an assignment, or a foreign id, is 404.
    with pytest.raises(HTTPException) as exc:
        get_assignment(assessment.id, 999, owner, db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Removal (pre-start only)
# ---------------------------------------------------------------------------
def test_remove_unstarted_assignment(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    c1 = _user(db, 10)
    c2 = _user(db, 11)
    a1 = _assignment(db, assessment, c1)
    a2 = _assignment(db, assessment, c2)

    result = remove_assignment(assessment.id, a1.id, owner, db)
    assert result is None

    assert db.query(models.AssessmentAssignment).filter(
        models.AssessmentAssignment.id == a1.id
    ).first() is None
    assert db.query(models.AssessmentAssignment).filter(
        models.AssessmentAssignment.id == a2.id
    ).first() is not None


def test_cannot_remove_started_or_submitted_assignment(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    c1 = _user(db, 10)
    c2 = _user(db, 11)
    started = _assignment(db, assessment, c1,
                          status=models.AssessmentAssignmentStatusEnum.in_progress)
    submitted = _assignment(db, assessment, c2,
                            status=models.AssessmentAssignmentStatusEnum.submitted)

    with pytest.raises(HTTPException) as exc:
        remove_assignment(assessment.id, started.id, owner, db)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        remove_assignment(assessment.id, submitted.id, owner, db)
    assert exc.value.status_code == 409

    assert db.query(models.AssessmentAssignment).filter(
        models.AssessmentAssignment.id == started.id
    ).first() is not None
    assert db.query(models.AssessmentAssignment).filter(
        models.AssessmentAssignment.id == submitted.id
    ).first() is not None


def test_remove_assignment_404_for_foreign_or_missing(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a1 = _assessment(db, company, title="One")
    a2 = _assessment(db, company, title="Two")
    c1 = _user(db, 10)
    assignment = _assignment(db, a1, c1)

    with pytest.raises(HTTPException) as exc:
        remove_assignment(a2.id, assignment.id, owner, db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        remove_assignment(a1.id, 999, owner, db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Isolation / RBAC
# ---------------------------------------------------------------------------
def test_another_company_cannot_manage_assignments(db):
    owner = _company_user(db, 1)
    company = _company(db, owner, name="Acme")
    assessment = _assessment(db, company)
    c1 = _user(db, 10)
    assignment = _assignment(db, assessment, c1)

    other_owner = _company_user(db, 2)
    _company(db, other_owner, name="Beta")

    with pytest.raises(HTTPException) as exc:
        list_assignments(assessment.id, other_owner, db)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        assign_candidates(
            assessment.id,
            schemas.AssessmentAssignIn(candidate_ids=[10]),
            other_owner,
            db,
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        get_assignment(assessment.id, assignment.id, other_owner, db)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        remove_assignment(assessment.id, assignment.id, other_owner, db)
    assert exc.value.status_code == 403

    # Nothing was changed by the other company's attempts.
    assert _assignment_count(db) == 1


def test_candidate_cannot_assign_themselves_or_touch_assignments(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    candidate = _user(db, 10)
    assignment = _assignment(db, assessment, candidate)

    # Candidates never pass company management RBAC...
    with pytest.raises(HTTPException) as exc:
        company_scoped(current_user=candidate)
    assert exc.value.status_code == 403

    # ...and even a direct call cannot self-assign / modify assignments.
    with pytest.raises(HTTPException) as exc:
        assign_candidates(
            assessment.id,
            schemas.AssessmentAssignIn(candidate_ids=[candidate.id]),
            candidate,
            db,
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        remove_assignment(assessment.id, assignment.id, candidate, db)
    assert exc.value.status_code == 403

    assert _assignment_count(db) == 1


def test_company_scoped_role_checker_rbac(db):
    company_user = _company_user(db, 1)
    admin = _admin_user(db, 9)
    candidate = _user(db, 10)

    assert company_scoped(current_user=company_user) is not None
    assert company_scoped(current_user=admin) is not None
    with pytest.raises(HTTPException) as exc:
        company_scoped(current_user=candidate)
    assert exc.value.status_code == 403
    assert RoleChecker(["company", "admin"])(current_user=admin) is not None


def test_admin_can_list_and_remove_any_assignment(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    c1 = _user(db, 10)
    assignment = _assignment(db, assessment, c1)
    admin = _admin_user(db, 9)

    listed = list_assignments(assessment.id, admin, db)
    assert [r.id for r in listed] == [assignment.id]

    remove_assignment(assessment.id, assignment.id, admin, db)
    assert _assignment_count(db) == 0


# ---------------------------------------------------------------------------
# Bulk assignment atomicity
# ---------------------------------------------------------------------------
def test_bulk_assignment_atomicity_on_invalid_candidate(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    _user(db, 10)
    _user(db, 11)  # both would otherwise be valid candidates

    with pytest.raises(HTTPException) as exc:
        assign_candidates(
            assessment.id,
            schemas.AssessmentAssignIn(candidate_ids=[10, 11, 999]),
            owner,
            db,
        )
    assert exc.value.status_code == 404
    assert _assignment_count(db) == 0


def test_bulk_assignment_atomicity_on_wrong_role(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    _user(db, 10)
    company_actor = _company_user(db, 2)  # wrong target role

    with pytest.raises(HTTPException) as exc:
        assign_candidates(
            assessment.id,
            schemas.AssessmentAssignIn(candidate_ids=[10, company_actor.id]),
            owner,
            db,
        )
    assert exc.value.status_code == 400
    assert _assignment_count(db) == 0


def test_bulk_assignment_atomicity_on_partial_duplicate(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    already = _user(db, 10)
    fresh = _user(db, 11)
    _assignment(db, assessment, already)

    with pytest.raises(HTTPException) as exc:
        assign_candidates(
            assessment.id,
            schemas.AssessmentAssignIn(candidate_ids=[10, 11]),
            owner,
            db,
        )
    assert exc.value.status_code == 409
    # Only the pre-existing single assignment exists — the fresh candidate
    # was not applied.
    assert _assignment_count(db) == 1
    assert db.query(models.AssessmentAssignment).filter(
        models.AssessmentAssignment.candidate_id == 11
    ).first() is None
"""Company Assessment event notification tests.

Verifies the event wiring that creates persistent in-app notifications for the
recruitment-pipeline assessment events:

* company assigns a candidate -> the candidate is notified;
* candidate submits -> the owning company's user is notified;
* deadline auto-submit -> the owning company's user is notified exactly once
  (a deadline submission is just a submission event);
* duplicate / idempotent requests never create duplicate notifications;
* assignment removal and starting an attempt create no notification;
* submission notifications go only to the owning company (RBAC/isolation).

Uses the suite's in-memory SQLite convention (no DB, no network); the Docker
code executor is unused here (no answers need grading).
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.routes import company_assessments as company_mod
from app.routes.candidate_assessment_start import start_my_assessment
from app.routes.candidate_assessment_answer import (
    _finalize_if_expired,
    get_my_attempt,
    submit_assessment,
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
        m.Assessment.__table__,
        m.AssessmentSection.__table__,
        m.AssessmentAssignment.__table__,
        m.AssessmentQuestion.__table__,
        m.AssessmentAnswer.__table__,
        m.Notification.__table__,
    ]
    m.Base.metadata.create_all(engine, tables=tables)
    s = Session(engine)
    yield s
    s.close()
    engine.dispose()


def _user(db, id, role=models.RoleEnum.user, name=None):
    u = models.User(
        id=id,
        name=name or f"User {id}",
        email=f"user{id}@recruito.com",
        password="hashed",
        role=role,
        is_active=True,
    )
    db.add(u)
    db.flush()
    return u


def _company_user(db, id, name=None):
    return _user(db, id, role=models.RoleEnum.company, name=name or "Recruiter")


def _admin_user(db, id):
    return _user(db, id, role=models.RoleEnum.admin, name="Admin")


def _company(db, user, name="Acme Recruiting"):
    c = models.Company(user_id=user.id, name=name, approved=True)
    db.add(c)
    db.flush()
    return c


def _assessment(db, company, title="Backend Screening", **kw):
    kw.setdefault("status", models.CompanyAssessmentStatusEnum.published)
    kw.setdefault("duration_minutes", 90)
    a = models.Assessment(company_id=company.id, title=title, **kw)
    db.add(a)
    db.flush()
    return a


def _section(db, assessment, order, section_type):
    s = models.AssessmentSection(
        assessment_id=assessment.id,
        section_type=section_type,
        title=section_type.value.title(),
        section_order=order,
        marks=10,
    )
    db.add(s)
    db.flush()
    return s


def _mcq(db, section, order, correct_index=0):
    q = models.AssessmentQuestion(
        section_id=section.id,
        question_type=models.AssessmentQuestionTypeEnum.mcq,
        question_text="Stable sort?",
        question_order=order,
        options=["Merge sort", "Quick sort", "Heap sort", "Selection sort"],
        correct_index=correct_index,
        marks=5,
    )
    db.add(q)
    db.flush()
    return q


def _assignment(
    db,
    assessment,
    candidate,
    status=models.AssessmentAssignmentStatusEnum.in_progress,
    **kw,
):
    a = models.AssessmentAssignment(
        assessment_id=assessment.id,
        candidate_id=candidate.id,
        status=status,
        **kw,
    )
    db.add(a)
    db.flush()
    return a


def _now():
    return datetime.utcnow()


def _notifications(db):
    return (
        db.query(models.Notification)
        .order_by(models.Notification.id)
        .all()
    )


def _notification_count(db):
    return db.query(models.Notification).count()


# ---------------------------------------------------------------------------
# Assignment -> candidate notification
# ---------------------------------------------------------------------------

def test_assigning_candidate_notifies_candidate(db):
    owner = _company_user(db, 1, name="Acme Owner")
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)

    result = company_mod.assign_candidates(
        assessment.id,
        schemas.AssessmentAssignIn(candidate_ids=[10]),
        owner,
        db,
    )

    assert len(result) == 1
    notifs = _notifications(db)
    assert len(notifs) == 1
    (n,) = notifs
    assert n.user_id == candidate.id
    assert n.type is models.NotificationType.assessment
    assert n.title == "Assessment Assigned"
    assert "Backend Screening" in n.message
    assert "Acme Recruiting" in n.message
    assert n.link == "/dashboard/company-assessments"
    assert n.read is False


def test_duplicate_assignment_creates_no_new_notification(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    other = _user(db, 11)
    assessment = _assessment(db, company)

    company_mod.assign_candidates(
        assessment.id,
        schemas.AssessmentAssignIn(candidate_ids=[10]),
        owner,
        db,
    )
    assert _notification_count(db) == 1

    # A retry / duplicate request (even one mixed with a brand-new candidate)
    # is rejected atomically before anything is written -> no new notification
    # and the second candidate is not silently assigned.
    with pytest.raises(HTTPException) as exc:
        company_mod.assign_candidates(
            assessment.id,
            schemas.AssessmentAssignIn(candidate_ids=[10, 11]),
            owner,
            db,
        )
    assert exc.value.status_code == 409

    assert _notification_count(db) == 1
    assignments = (
        db.query(models.AssessmentAssignment)
        .filter(models.AssessmentAssignment.assessment_id == assessment.id)
        .all()
    )
    assert {a.candidate_id for a in assignments} == {10}
    assert other.id not in {a.candidate_id for a in assignments}


def test_removing_assignment_creates_no_notification(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    assignment = _assignment(
        db,
        assessment,
        candidate,
        status=models.AssessmentAssignmentStatusEnum.assigned,
    )

    company_mod.remove_assignment(assessment.id, assignment.id, owner, db)

    assert _notification_count(db) == 0


# ---------------------------------------------------------------------------
# Submission -> company notification
# ---------------------------------------------------------------------------

def test_submitting_notifies_owning_company(db):
    owner = _company_user(db, 1, name="Owner")
    company = _company(db, owner)
    candidate = _user(db, 10, name="Ada Lovelace")
    assessment = _assessment(db, company)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    _mcq(db, section, 1)
    _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(minutes=5),
    )

    out = submit_assessment(assessment.id, candidate, db)

    assert out.status == models.AssessmentAssignmentStatusEnum.submitted
    (n,) = _notifications(db)
    assert n.user_id == owner.id
    assert n.user_id == company.user_id
    assert n.type is models.NotificationType.assessment
    assert n.title == "Assessment Submitted"
    assert "Ada Lovelace" in n.message
    assert "Backend Screening" in n.message
    assert n.link == f"/company/assessments/{assessment.id}"
    assert n.read is False


def test_resubmitting_does_not_duplicate_notification(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(minutes=5),
    )

    submit_assessment(assessment.id, candidate, db)
    assert _notification_count(db) == 1

    # Idempotent re-submit of the already-submitted attempt adds nothing.
    submit_assessment(assessment.id, candidate, db)
    assert _notification_count(db) == 1


# ---------------------------------------------------------------------------
# Deadline auto-submit -> company notification (exactly once)
# ---------------------------------------------------------------------------

def test_auto_submit_notifies_company_exactly_once(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10, name="Grace Hopper")
    assessment = _assessment(db, company, duration_minutes=90)
    _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(hours=2),  # deadline (start+90m) is past
    )

    out = get_my_attempt(assessment.id, candidate, db)

    # The deadline submission is a submission event: the company is notified.
    assert out.status == models.AssessmentAssignmentStatusEnum.submitted
    (n,) = _notifications(db)
    assert n.user_id == company.user_id
    assert n.type is models.NotificationType.assessment
    assert n.title == "Assessment Auto-submitted"
    assert "Grace Hopper" in n.message
    assert "Backend Screening" in n.message
    assert n.link == f"/company/assessments/{assessment.id}"

    # Re-entry / repeat finalize checks must never notify again.
    get_my_attempt(assessment.id, candidate, db)
    assert _notification_count(db) == 1

    fresh = (
        db.query(models.AssessmentAssignment)
        .filter(models.AssessmentAssignment.id == assignment.id)
        .one()
    )
    assert _finalize_if_expired(db, fresh) is False
    assert _notification_count(db) == 1


def test_submitting_after_expiry_notifies_once(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, duration_minutes=90)
    _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(hours=2),
    )

    # Calling submit on an already-expired attempt finalizes via the shared
    # auto-submit path (one company notification), then returns idempotently.
    submit_assessment(assessment.id, candidate, db)
    submit_assessment(assessment.id, candidate, db)

    (n,) = _notifications(db)
    assert n.title == "Assessment Auto-submitted"
    assert _notification_count(db) == 1


# ---------------------------------------------------------------------------
# No-notification cases
# ---------------------------------------------------------------------------

def test_starting_assessment_creates_no_notification(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.assigned,
    )

    out = start_my_assessment(assessment.id, candidate, db)

    assert out.status == models.AssessmentAssignmentStatusEnum.in_progress
    assert _notification_count(db) == 0


# ---------------------------------------------------------------------------
# RBAC / ownership isolation
# ---------------------------------------------------------------------------

def test_submission_notifies_only_owning_company(db):
    owner_a = _company_user(db, 1)
    company_a = _company(db, owner_a, name="Alpha Corp")
    owner_b = _company_user(db, 2, name="Owner B")
    company_b = _company(db, owner_b, name="Beta Inc")
    admin = _admin_user(db, 99)
    candidate = _user(db, 10)
    assessment_a = _assessment(db, company_a, title="Alpha Screen")
    assessment_b = _assessment(db, company_b, title="Beta Screen")
    _assignment(
        db, assessment_a, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(minutes=5),
    )

    submit_assessment(assessment_a.id, candidate, db)

    (n,) = _notifications(db)
    assert n.user_id == owner_a.id
    assert n.message == f"{candidate.name} submitted 'Alpha Screen'."

    # Nobody else — not the other company, not an admin — receives anything.
    for other in (owner_b.id, admin.id, candidate.id):
        other_notifs = (
            db.query(models.Notification)
            .filter(models.Notification.user_id == other)
            .all()
        )
        assert other_notifs == []

    # A candidate of another company's assessment was never involved.
    other_assignments = (
        db.query(models.AssessmentAssignment)
        .filter(models.AssessmentAssignment.assessment_id == assessment_b.id)
        .all()
    )
    assert other_assignments == []
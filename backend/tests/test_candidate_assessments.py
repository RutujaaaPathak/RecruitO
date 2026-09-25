"""Candidate-facing Company Assessments API tests (/me/assessments route).

Exercises the candidate-only endpoints directly (user, session) against an
in-memory SQLite engine with ``foreign_keys=ON`` over just the pipeline tables.
Covers scoping to the candidate's own assignments (another candidate's / another
company's / unassigned / deleted assessments are indistinguishable 404s),
section ordering/timing in the details, per-state status & timestamps, private
field non-exposure, RBAC (candidates only; company/admin denied), and that the
existing company/admin endpoints remain unaffected. No network, no external DB.
"""
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.auth import RoleChecker
from app.routes.candidate_assessments import (
    candidate_only,
    get_my_assessment,
    get_my_assignment,
    list_my_assessments,
)
from app.routes.company_assessments import (
    delete_assessment,
    get_assessment,
    get_assignment,
    list_assignments,
    list_assessments,
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


def _user(db, id, role=models.RoleEnum.user, name=None, active=True):
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


def _assessment(db, company, title="Backend Screening", **kw):
    a = models.Assessment(
        company_id=company.id,
        title=title,
        description=kw.pop("description", "Full-stack candidate screening"),
        instructions=kw.pop("instructions", "Complete each section in order."),
        status=kw.pop("status", models.CompanyAssessmentStatusEnum.published),
        duration_minutes=kw.pop("duration_minutes", 90),
        **kw,
    )
    db.add(a)
    db.flush()
    return a


def _section(db, assessment, order, section_type=None, title=None, marks=10,
             settings=None):
    section_type = section_type or models.AssessmentSectionTypeEnum.aptitude
    s = models.AssessmentSection(
        assessment_id=assessment.id,
        section_type=section_type,
        title=title or section_type.value.title(),
        section_order=order,
        marks=marks,
        settings=settings,
    )
    db.add(s)
    db.flush()
    return s


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


def _job(db, company, title="Software Engineer"):
    j = models.Job(company_id=company.id, title=title)
    db.add(j)
    db.flush()
    return j


def _application(db, user, job):
    ap = models.Application(job_id=job.id, user_id=user.id)
    db.add(ap)
    db.flush()
    return ap


# ---------------------------------------------------------------------------
# List my assigned assessments
# ---------------------------------------------------------------------------
def test_list_my_assigned_assessments_with_full_details(db):
    owner = _company_user(db, 1)
    company = _company(db, owner, name="Acme Recruiting")
    candidate = _user(db, 10, name="Ada Lovelace")
    assessment = _assessment(
        db,
        company,
        title="Backend Screening",
        description="Full-stack candidate screening",
        instructions="Complete each section in order.",
        duration_minutes=90,
        starts_at=datetime(2026, 6, 1, 9, 0),
        ends_at=datetime(2026, 6, 30, 23, 59),
    )
    assignment = _assignment(db, assessment, candidate)

    result = list_my_assessments(candidate, db)

    assert len(result) == 1
    out = result[0]
    assert out.id == assignment.id
    assert out.assessment_id == assessment.id
    assert out.title == "Backend Screening"
    assert out.description == "Full-stack candidate screening"
    assert out.instructions == "Complete each section in order."
    assert out.company_name == "Acme Recruiting"
    assert out.duration_minutes == 90
    assert out.starts_at == datetime(2026, 6, 1, 9, 0)
    assert out.ends_at == datetime(2026, 6, 30, 23, 59)
    assert out.status == models.AssessmentAssignmentStatusEnum.assigned
    assert out.assigned_at is not None
    assert out.started_at is None
    assert out.submitted_at is None


def test_list_newest_assignment_first(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    a1 = _assessment(db, company, title="First")
    a2 = _assessment(db, company, title="Second")
    older = _assignment(db, a1, candidate, assigned_at=datetime(2026, 1, 1))
    newer = _assignment(db, a2, candidate, assigned_at=datetime(2026, 1, 3))

    result = list_my_assessments(candidate, db)
    assert [r.id for r in result] == [newer.id, older.id]


def test_list_omits_other_candidates_assessments(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    ada = _user(db, 10, name="Ada")
    grace = _user(db, 11, name="Grace")
    a1 = _assessment(db, company, title="Ada's Assign")
    a2 = _assessment(db, company, title="Grace's Assign")
    _assignment(db, a1, ada)
    _assignment(db, a2, grace)

    ada_result = list_my_assessments(ada, db)
    assert [r.assessment_id for r in ada_result] == [a1.id]
    grace_result = list_my_assessments(grace, db)
    assert [r.assessment_id for r in grace_result] == [a2.id]


def test_list_empty_for_candidate_without_assignments(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    _assessment(db, company)

    assert list_my_assessments(candidate, db) == []


# ---------------------------------------------------------------------------
# Detail — one assigned assessment
# ---------------------------------------------------------------------------
def test_detail_returns_ordered_sections_and_timing(db):
    owner = _company_user(db, 1)
    company = _company(db, owner, name="Acme Recruiting")
    candidate = _user(db, 10)
    assessment = _assessment(
        db,
        company,
        description="desc",
        instructions="instr",
        duration_minutes=120,
        starts_at=datetime(2026, 6, 1, 9, 0),
        ends_at=datetime(2026, 6, 15, 18, 0),
    )
    # Insert out of configured order on purpose.
    s3 = _section(db, assessment, 3, models.AssessmentSectionTypeEnum.hr, "HR")
    s1 = _section(
        db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude, "Aptitude"
    )
    s2 = _section(db, assessment, 2, models.AssessmentSectionTypeEnum.coding, "Coding")
    assignment = _assignment(db, assessment, candidate,
                             assigned_at=datetime(2026, 5, 1, 12, 0))

    out = get_my_assessment(assessment.id, candidate, db)

    assert out.id == assignment.id
    assert out.assessment_id == assessment.id
    assert out.title == assessment.title
    assert out.description == "desc"
    assert out.instructions == "instr"
    assert out.company_name == "Acme Recruiting"
    assert out.duration_minutes == 120
    assert out.starts_at == datetime(2026, 6, 1, 9, 0)
    assert out.ends_at == datetime(2026, 6, 15, 18, 0)
    # Sections come back in the configured order, not insertion order.
    assert [s.id for s in out.sections] == [s1.id, s2.id, s3.id]
    assert [s.section_order for s in out.sections] == [1, 2, 3]
    assert [s.section_type for s in out.sections] == [
        models.AssessmentSectionTypeEnum.aptitude,
        models.AssessmentSectionTypeEnum.coding,
        models.AssessmentSectionTypeEnum.hr,
    ]


def test_detail_for_upcoming_and_ended_windows(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    upcoming = _assessment(
        db, company, title="Upcoming",
        starts_at=datetime(2099, 1, 1), ends_at=datetime(2099, 12, 31),
    )
    expired = _assessment(
        db, company, title="Ended",
        starts_at=datetime(2020, 1, 1), ends_at=datetime(2020, 12, 31),
    )
    _assignment(db, upcoming, candidate, status=models.AssessmentAssignmentStatusEnum.assigned)
    _assignment(db, expired, candidate, status=models.AssessmentAssignmentStatusEnum.submitted)

    assert get_my_assessment(upcoming.id, candidate, db).starts_at == datetime(2099, 1, 1)
    assert get_my_assessment(expired.id, candidate, db).ends_at == datetime(2020, 12, 31)
    assert get_my_assessment(expired.id, candidate, db).status == \
        models.AssessmentAssignmentStatusEnum.submitted


def test_detail_does_not_expose_private_fields(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    _section(db, assessment, 1, settings={"points": 100, "engine": "secret"})
    _assignment(db, assessment, candidate)

    out = get_my_assessment(assessment.id, candidate, db)

    # The candidate contract never carries scoring/engine or identity internals:
    # no per-section marks/settings, no company id, no assessment lifecycle.
    assert "marks" not in out.sections[0].model_dump()
    assert "settings" not in out.sections[0].model_dump()
    assert "company_id" not in out.model_dump()
    assert "company_id" not in schemas.CandidateAssessmentAssignmentOut.model_fields
    assert "settings" not in schemas.CandidateAssessmentSectionOut.model_fields
    assert "marks" not in schemas.CandidateAssessmentSectionOut.model_fields


# ---------------------------------------------------------------------------
# Start availability contract (unavailable_reason)
# ---------------------------------------------------------------------------
def test_unavailable_reason_is_none_when_the_attempt_can_be_started(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    now = datetime.utcnow()
    assessment = _assessment(
        db, company, duration_minutes=90,
        starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1),
    )
    _assignment(db, assessment, candidate)

    assert list_my_assessments(candidate, db)[0].unavailable_reason is None
    assert get_my_assignment(assessment.id, candidate, db).unavailable_reason is None
    assert get_my_assessment(assessment.id, candidate, db).unavailable_reason is None


def test_unavailable_reason_explains_why_a_untouched_attempt_is_blocked(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    now = datetime.utcnow()
    unpublished = _assessment(
        db, company, title="Draft",
        status=models.CompanyAssessmentStatusEnum.draft,
        starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1),
    )
    upcoming = _assessment(
        db, company, title="Upcoming",
        starts_at=now + timedelta(hours=1), ends_at=now + timedelta(days=1),
    )
    ended = _assessment(
        db, company, title="Ended",
        starts_at=now - timedelta(days=2), ends_at=now - timedelta(hours=1),
    )
    too_short = _assessment(
        db, company, title="Too short", duration_minutes=90,
        starts_at=now - timedelta(days=1), ends_at=now + timedelta(minutes=10),
    )
    for assessment in (unpublished, upcoming, ended, too_short):
        _assignment(db, assessment, candidate)

    reported = {
        row.assessment_id: row.unavailable_reason
        for row in list_my_assessments(candidate, db)
    }
    # Every block reason is a complete sentence the candidate UI can show as-is.
    assert reported[unpublished.id] == "Assessment is not currently available"
    assert reported[upcoming.id] == "Assessment has not started yet"
    assert reported[ended.id] == "Assessment window has ended"
    assert reported[too_short.id] == (
        "Not enough time remaining to complete the assessment"
    )
    # Detail + status endpoints report the same reason as the list.
    assert get_my_assessment(
        unpublished.id, candidate, db
    ).unavailable_reason == "Assessment is not currently available"
    assert get_my_assignment(
        too_short.id, candidate, db
    ).unavailable_reason == "Not enough time remaining to complete the assessment"


def test_unavailable_reason_is_none_once_the_attempt_has_run(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    now = datetime.utcnow()
    # Closing the assessment blocks a fresh start, but it must not retroactively
    # mark an in-progress or submitted attempt as unavailable: those are
    # resumed/reviewed, never restarted, so gating them would hide the result.
    running = _assessment(
        db, company, title="Running", status=models.CompanyAssessmentStatusEnum.closed,
        starts_at=now - timedelta(days=2), ends_at=now - timedelta(hours=1),
    )
    done = _assessment(
        db, company, title="Done", status=models.CompanyAssessmentStatusEnum.closed,
        starts_at=now - timedelta(days=2), ends_at=now - timedelta(hours=1),
    )
    _assignment(
        db, running, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=now - timedelta(hours=2),
    )
    _assignment(
        db, done, candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=now - timedelta(hours=2), submitted_at=now - timedelta(hours=1),
    )

    reported = {
        row.assessment_id: row.unavailable_reason
        for row in list_my_assessments(candidate, db)
    }
    assert reported[running.id] is None
    assert reported[done.id] is None


# ---------------------------------------------------------------------------
# Isolation — another candidate / another company / unassigned
# ---------------------------------------------------------------------------
def test_cannot_view_another_candidates_assessment(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    ada = _user(db, 10)
    grace = _user(db, 11)
    assessment = _assessment(db, company)
    _assignment(db, assessment, ada)

    # Grace is not assigned: the detail and the status call are 404s — the
    # existence of Ada's assignment is never revealed.
    with pytest.raises(HTTPException) as exc:
        get_my_assessment(assessment.id, grace, db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        get_my_assignment(assessment.id, grace, db)
    assert exc.value.status_code == 404
    assert list_my_assessments(grace, db) == []

    # Ada can still see it, so the scope really is per-candidate.
    assert get_my_assessment(assessment.id, ada, db).assessment_id == assessment.id


def test_cannot_swap_ids_to_another_candidates_assignment(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a1 = _assessment(db, company, title="One")
    a2 = _assessment(db, company, title="Two")
    ada = _user(db, 10)
    grace = _user(db, 11)
    _assignment(db, a1, ada)
    _assignment(db, a2, grace)

    # Ada probing with Grace's assessment id gets a 404, never Grace's data.
    for probe in (a2.id + 1000, a2.id):
        with pytest.raises(HTTPException) as exc:
            get_my_assessment(probe, ada, db)
        assert exc.value.status_code == 404


def test_candidate_from_another_company_cannot_access_assignment(db):
    owner_a = _company_user(db, 1)
    company_a = _company(db, owner_a, name="Acme")
    candidate_a = _user(db, 10)
    assessment = _assessment(db, company_a, title="Acme's Screen")
    _assignment(db, assessment, candidate_a)

    owner_b = _company_user(db, 2)
    company_b = _company(db, owner_b, name="Beta")
    job = _job(db, company_b)
    candidate_b = _user(db, 11)
    _application(db, candidate_b, job)

    with pytest.raises(HTTPException) as exc:
        get_my_assessment(assessment.id, candidate_b, db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        get_my_assignment(assessment.id, candidate_b, db)
    assert exc.value.status_code == 404
    assert list_my_assessments(candidate_b, db) == []


def test_unassigned_or_unknown_assessment_404(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)

    with pytest.raises(HTTPException) as exc:
        get_my_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        get_my_assignment(assessment.id, candidate, db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        get_my_assessment(9999, candidate, db)
    assert exc.value.status_code == 404


def test_deleted_assessment_is_unavailable_404(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    _assignment(db, assessment, candidate)
    assert get_my_assessment(assessment.id, candidate, db).assessment_id == assessment.id

    # Company deletes the assessment (assignments/sections cascade away)...
    delete_assessment(assessment.id, owner, db)

    # ...and the candidate's view now 404s instead of dangling.
    with pytest.raises(HTTPException) as exc:
        get_my_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 404
    assert list_my_assessments(candidate, db) == []


# ---------------------------------------------------------------------------
# Status / timestamps per assignment state
# ---------------------------------------------------------------------------
def test_assignment_status_and_timestamps(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    fresh = _user(db, 10)
    started = _user(db, 11)
    done = _user(db, 12)
    _assignment(db, a, fresh, status=models.AssessmentAssignmentStatusEnum.assigned)
    _assignment(
        db, a, started, status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=datetime(2026, 3, 2, 10, 0),
    )
    _assignment(
        db, a, done, status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=datetime(2026, 3, 2, 10, 0),
        submitted_at=datetime(2026, 3, 2, 11, 30),
    )

    assigned_out = get_my_assignment(a.id, fresh, db)
    assert assigned_out.status == models.AssessmentAssignmentStatusEnum.assigned
    assert assigned_out.assigned_at is not None
    assert assigned_out.started_at is None
    assert assigned_out.submitted_at is None

    started_out = get_my_assignment(a.id, started, db)
    assert started_out.status == models.AssessmentAssignmentStatusEnum.in_progress
    assert started_out.started_at == datetime(2026, 3, 2, 10, 0)
    assert started_out.submitted_at is None

    done_out = get_my_assignment(a.id, done, db)
    assert done_out.status == models.AssessmentAssignmentStatusEnum.submitted
    assert done_out.started_at == datetime(2026, 3, 2, 10, 0)
    assert done_out.submitted_at == datetime(2026, 3, 2, 11, 30)


def test_get_my_assignment_is_scoped_like_detail(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    ada = _user(db, 10)
    grace = _user(db, 11)
    assessment = _assessment(db, company)
    assignment = _assignment(db, assessment, ada)

    out = get_my_assignment(assessment.id, ada, db)
    assert out.id == assignment.id
    assert out.assessment_id == assessment.id
    assert out.company_name == company.name
    with pytest.raises(HTTPException) as exc:
        get_my_assignment(assessment.id, grace, db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Company/admin endpoints remain unaffected
# ---------------------------------------------------------------------------
def test_company_endpoints_unaffected_after_candidate_access(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    _section(db, assessment, 1)
    assignment = _assignment(db, assessment, candidate)

    list_my_assessments(candidate, db)
    get_my_assessment(assessment.id, candidate, db)

    assert [a.id for a in list_assessments(owner, db)] == [assessment.id]
    detail = get_assessment(assessment.id, owner, db)
    assert [s.id for s in detail.sections] == [assessment.sections[0].id]
    listed = list_assignments(assessment.id, owner, db)
    assert [x.id for x in listed] == [assignment.id]
    assert get_assignment(assessment.id, assignment.id, owner, db).candidate_id == candidate.id


def test_company_endpoints_unaffected_after_delete(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    other_assessment = _assessment(db, company, title="Other")
    _assignment(db, other_assessment, _user(db, 10))

    delete_assessment(assessment.id, owner, db)

    assert [a.id for a in list_assessments(owner, db)] == [other_assessment.id]
    assert get_assessment(other_assessment.id, owner, db).id == other_assessment.id


def test_admin_endpoints_unaffected(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    admin = _admin_user(db, 9)
    assessment = _assessment(db, company)
    _assignment(db, assessment, candidate)

    assert get_assessment(assessment.id, admin, db).id == assessment.id
    assert [a.id for a in list_assessments(admin, db)] == [assessment.id]


def test_candidate_still_blocked_from_company_endpoints(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    _assignment(db, assessment, candidate)

    with pytest.raises(HTTPException) as exc:
        list_assignments(assessment.id, candidate, db)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        get_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Authentication / RBAC
# ---------------------------------------------------------------------------
def test_candidate_only_role_checker_rbac(db):
    candidate = _user(db, 10)
    company_user = _company_user(db, 1)
    admin = _admin_user(db, 9)

    assert candidate_only(current_user=candidate) is not None
    with pytest.raises(HTTPException) as exc:
        candidate_only(current_user=company_user)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        candidate_only(current_user=admin)
    assert exc.value.status_code == 403
    assert RoleChecker(["user"])(current_user=candidate) is not None
    with pytest.raises(HTTPException) as exc:
        RoleChecker(["user"])(current_user=admin)
    assert exc.value.status_code == 403
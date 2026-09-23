"""Candidate Company Assessment start/attempt flow tests.

Exercises ``POST /me/assessments/{id}/start`` directly (user, session) against
an in-memory SQLite engine with ``foreign_keys=ON`` over just the pipeline
tables. Covers: successful start + status/timestamps, candidate ownership,
unassigned/foreign/deleted assessments, window enforcement (before start/after
end/not enough time/not currently available), already-started/already-submitted
rejection, the atomic double-start guard, configured question ordering, MCQ
answer privacy, coding hidden-test privacy, cross-candidate isolation, RBAC,
and that the existing listing/detail/company endpoints remain unaffected. No
network, no external DB.
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, update
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
from app.routes.candidate_assessment_start import start_my_assessment
from app.routes.company_assessments import (
    delete_assessment,
    get_assessment,
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


def _company(db, user, name="Acme Recruiting"):
    c = models.Company(user_id=user.id, name=name, approved=True)
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


def _section(db, assessment, order, section_type, title=None):
    s = models.AssessmentSection(
        assessment_id=assessment.id,
        section_type=section_type,
        title=title or section_type.value.title(),
        section_order=order,
        marks=10,
    )
    db.add(s)
    db.flush()
    return s


def _mcq(db, section, order, text="Which sorting algorithm is stable?",
         correct_index=0):
    q = models.AssessmentQuestion(
        section_id=section.id,
        question_type=models.AssessmentQuestionTypeEnum.mcq,
        question_text=text,
        question_order=order,
        options=["Merge sort", "Quick sort", "Heap sort", "Selection sort"],
        correct_index=correct_index,
        marks=5,
        explanation="Merge sort is stable; the others are not.",
    )
    db.add(q)
    db.flush()
    return q


def _coding(db, section, order, text="Return indices summing to target.",
            title="Two Sum", hidden=True):
    q = models.AssessmentQuestion(
        section_id=section.id,
        question_type=models.AssessmentQuestionTypeEnum.coding,
        question_text=text,
        question_order=order,
        title=title,
        category="arrays",
        difficulty="easy",
        input_format="Line 1: N, line 2: N ints, line 3: target",
        output_format="Two space-separated indices",
        constraints="2 <= N <= 1000",
        sample_cases=[{"input": "4\n2 7 11 15\n9", "expected": "0 1"}],
        hidden_cases=[{"input": "2\n3 3\n6", "expected": "0 1"}] if hidden else [],
        time_limit_seconds=5,
        supported_languages=["python", "java"],
    )
    db.add(q)
    db.flush()
    return q


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


def _now():
    return datetime.utcnow()


def _active_window(now=None):
    """An assessment window safely open 'now' (wide enough for any duration)."""
    now = now or _now()
    return dict(
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=30),
    )


# ---------------------------------------------------------------------------
# Successful start
# ---------------------------------------------------------------------------
def test_start_returns_full_candidate_content(db):
    owner = _company_user(db, 1)
    company = _company(db, owner, name="Acme Recruiting")
    candidate = _user(db, 10, name="Ada Lovelace")
    assessment = _assessment(
        db, company,
        title="Backend Screening",
        description="Full-stack candidate screening",
        instructions="Complete each section in order.",
        duration_minutes=90,
        **_active_window(),
    )
    aptitude = _section(
        db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude, "Aptitude"
    )
    coding = _section(
        db, assessment, 2, models.AssessmentSectionTypeEnum.coding, "Coding"
    )
    mcq1 = _mcq(db, aptitude, 1, text="Q1")
    mcq2 = _mcq(db, aptitude, 2, text="Q2", correct_index=2)
    cod1 = _coding(db, coding, 1)
    assignment = _assignment(db, assessment, candidate,
                             assigned_at=datetime(2026, 5, 1, 12, 0))

    out = start_my_assessment(assessment.id, candidate, db)

    assert out.attempt_id == assignment.id
    assert out.assessment_id == assessment.id
    assert out.title == "Backend Screening"
    assert out.description == "Full-stack candidate screening"
    assert out.instructions == "Complete each section in order."
    assert out.company_name == "Acme Recruiting"
    assert out.duration_minutes == 90
    assert out.status == models.AssessmentAssignmentStatusEnum.in_progress
    assert out.started_at is not None
    assert out.deadline_at == out.started_at + timedelta(minutes=90)
    assert out.starts_at is not None
    assert out.ends_at is not None

    # Ordered sections, each with its own ordered questions.
    assert [s.id for s in out.sections] == [aptitude.id, coding.id]
    assert [s.section_order for s in out.sections] == [1, 2]
    assert [q.id for q in out.sections[0].questions] == [mcq1.id, mcq2.id]
    assert [q.question_order for q in out.sections[0].questions] == [1, 2]
    assert [q.question_text for q in out.sections[0].questions] == ["Q1", "Q2"]
    assert [q.id for q in out.sections[1].questions] == [cod1.id]


def test_start_records_status_and_started_at_on_assignment(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, **_active_window())
    _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    assignment = _assignment(db, assessment, candidate)

    out = start_my_assessment(assessment.id, candidate, db)
    db.refresh(assignment)

    assert assignment.status == models.AssessmentAssignmentStatusEnum.in_progress
    assert assignment.started_at == out.started_at
    assert assignment.started_at is not None
    assert assignment.submitted_at is None

    # Existing candidate APIs now reflect the in-progress state.
    status_out = get_my_assignment(assessment.id, candidate, db)
    assert status_out.status == models.AssessmentAssignmentStatusEnum.in_progress
    assert status_out.started_at == out.started_at
    detail = get_my_assessment(assessment.id, candidate, db)
    assert [s.id for s in detail.sections] == [assessment.sections[0].id]


def test_start_hr_section_renders_with_no_questions(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, **_active_window())
    hr = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.hr, "HR")
    _assignment(db, assessment, candidate)

    out = start_my_assessment(assessment.id, candidate, db)

    assert out.sections[0].id == hr.id
    assert out.sections[0].section_type == models.AssessmentSectionTypeEnum.hr
    assert out.sections[0].questions == []


def test_start_deadline_within_window(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    now = _now()
    # Window ends after start + duration, so the effective deadline is the
    # duration-based one, and it never exceeds the window end.
    assessment = _assessment(
        db, company,
        duration_minutes=120,
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=2),
    )
    _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    _assignment(db, assessment, candidate)

    out = start_my_assessment(assessment.id, candidate, db)

    assert out.started_at is not None
    assert out.deadline_at == min(
        out.started_at + timedelta(minutes=120), assessment.ends_at
    )
    assert out.deadline_at <= assessment.ends_at


# ---------------------------------------------------------------------------
# Window / availability enforcement
# ---------------------------------------------------------------------------
def test_start_before_start_time_400(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(
        db, company,
        starts_at=_now() + timedelta(hours=1),
        ends_at=_now() + timedelta(days=1),
    )
    _assignment(db, assessment, candidate)

    with pytest.raises(HTTPException) as exc:
        start_my_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 400
    assert "not started" in exc.value.detail


def test_start_after_end_time_400(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(
        db, company,
        starts_at=_now() - timedelta(days=1),
        ends_at=_now() - timedelta(hours=1),
    )
    _assignment(db, assessment, candidate)

    with pytest.raises(HTTPException) as exc:
        start_my_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 400
    assert "ended" in exc.value.detail


def test_start_rejected_when_not_enough_time_remaining(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(
        db, company,
        duration_minutes=90,
        starts_at=_now() - timedelta(days=1),
        ends_at=_now() + timedelta(minutes=10),
    )
    _assignment(db, assessment, candidate)

    with pytest.raises(HTTPException) as exc:
        start_my_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 400
    assert "Not enough time" in exc.value.detail

    # The failed attempts never transition the assignment.
    db.refresh(db.query(models.AssessmentAssignment).first())
    assert (
        db.query(models.AssessmentAssignment).one().status
        == models.AssessmentAssignmentStatusEnum.assigned
    )


def test_start_rejected_for_draft_and_closed_assessments(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    draft = _assessment(db, company, title="Draft",
                        status=models.CompanyAssessmentStatusEnum.draft,
                        **_active_window())
    closed = _assessment(
        db, company, title="Closed",
        status=models.CompanyAssessmentStatusEnum.closed, **_active_window(),
    )
    _assignment(db, draft, candidate)
    _assignment(db, closed, candidate)

    for assessment in (draft, closed):
        with pytest.raises(HTTPException) as exc:
            start_my_assessment(assessment.id, candidate, db)
        assert exc.value.status_code == 400
        assert "not currently available" in exc.value.detail


def test_start_rejected_before_and_after_window_when_open_edges(db):
    # Unbounded windows (no starts_at/ends_at) are always startable now.
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    _assignment(db, assessment, candidate)

    out = start_my_assessment(assessment.id, candidate, db)
    assert out.status == models.AssessmentAssignmentStatusEnum.in_progress
    assert out.deadline_at == out.started_at + timedelta(minutes=90)


# ---------------------------------------------------------------------------
# Assignment state / duplicate start
# ---------------------------------------------------------------------------
def test_start_twice_409_and_keeps_first_started_at(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, **_active_window())
    assignment = _assignment(db, assessment, candidate)

    first = start_my_assessment(assessment.id, candidate, db)
    with pytest.raises(HTTPException) as exc:
        start_my_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 409
    assert "already been started" in exc.value.detail

    # Exactly one attempt/session row, one started_at — the first start wins.
    db.refresh(assignment)
    assert assignment.status == models.AssessmentAssignmentStatusEnum.in_progress
    assert assignment.started_at == first.started_at
    assert (
        db.query(models.AssessmentAssignment)
        .filter(models.AssessmentAssignment.assessment_id == assessment.id)
        .count()
        == 1
    )


def test_start_already_submitted_409(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, **_active_window())
    _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=_now() - timedelta(hours=2),
        submitted_at=_now() - timedelta(hours=1),
    )

    with pytest.raises(HTTPException) as exc:
        start_my_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 409
    assert "already been submitted" in exc.value.detail


def test_start_guarded_when_row_already_transitioned(db):
    """A concurrent request that already moved the row (simulated here by a
    second write) is caught by the atomic conditional update, not duplicated."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, **_active_window())
    assignment = _assignment(db, assessment, candidate)

    # Simulate the concurrent request winning: it flips the row and commits.
    db.execute(
        update(models.AssessmentAssignment)
        .where(models.AssessmentAssignment.id == assignment.id)
        .values(
            status=models.AssessmentAssignmentStatusEnum.submitted,
            submitted_at=_now(),
        )
    )
    db.commit()

    with pytest.raises(HTTPException) as exc:
        start_my_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 409
    assert "already been submitted" in exc.value.detail

    # The concurrent submission is preserved — nothing was overwritten.
    db.refresh(assignment)
    assert assignment.status == models.AssessmentAssignmentStatusEnum.submitted
    assert assignment.started_at is None


# ---------------------------------------------------------------------------
# Candidate ownership / isolation
# ---------------------------------------------------------------------------
def test_start_unassigned_candidate_404(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, **_active_window())

    with pytest.raises(HTTPException) as exc:
        start_my_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 404


def test_start_missing_assessment_404(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    _assessment(db, company)

    with pytest.raises(HTTPException) as exc:
        start_my_assessment(9999, candidate, db)
    assert exc.value.status_code == 404


def test_start_other_candidates_assignment_404(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    ada = _user(db, 10)
    grace = _user(db, 11)
    assessment = _assessment(db, company, **_active_window())
    _assignment(db, assessment, ada)

    with pytest.raises(HTTPException) as exc:
        start_my_assessment(assessment.id, grace, db)
    assert exc.value.status_code == 404

    # The owner can already start it; the scope really is per-candidate.
    assert start_my_assessment(assessment.id, ada, db).attempt_id is not None


def test_start_deleted_assessment_404(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, **_active_window())
    _assignment(db, assessment, candidate)

    delete_assessment(assessment.id, owner, db)

    with pytest.raises(HTTPException) as exc:
        start_my_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 404


def test_start_cross_candidate_isolation(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    ada = _user(db, 10)
    grace = _user(db, 11)
    a1 = _assessment(db, company, title="Ada's", **_active_window())
    a2 = _assessment(db, company, title="Grace's", **_active_window())
    _assignment(db, a1, ada)
    _assignment(db, a2, grace)

    ada_out = start_my_assessment(a1.id, ada, db)
    assert ada_out.assessment_id == a1.id
    # Grace can never reach Ada's started attempt, or vice-versa.
    with pytest.raises(HTTPException) as exc:
        start_my_assessment(a1.id, grace, db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        start_my_assessment(a2.id, ada, db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Candidate-safe question content
# ---------------------------------------------------------------------------
def test_start_never_exposes_mcq_private_fields(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, **_active_window())
    section = _section(
        db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude, "Aptitude"
    )
    _mcq(db, section, 1, correct_index=3)
    _assignment(db, assessment, candidate)

    out = start_my_assessment(assessment.id, candidate, db)

    question = out.sections[0].questions[0]
    assert question.question_type == models.AssessmentQuestionTypeEnum.mcq
    assert question.options == ["Merge sort", "Quick sort", "Heap sort", "Selection sort"]

    # Private evaluation fields are absent from the contract entirely.
    dump = question.model_dump()
    for private in ("correct_index", "marks", "explanation", "hidden_cases"):
        assert private not in dump
        assert private not in schemas.CandidateAssessmentQuestionOut.model_fields


def test_start_coding_shows_sample_cases_but_not_hidden(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, **_active_window())
    section = _section(
        db, assessment, 1, models.AssessmentSectionTypeEnum.coding, "Coding"
    )
    _coding(db, section, 1)
    _assignment(db, assessment, candidate)

    out = start_my_assessment(assessment.id, candidate, db)

    question = out.sections[0].questions[0]
    assert question.question_type == models.AssessmentQuestionTypeEnum.coding
    assert question.sample_cases == [{"input": "4\n2 7 11 15\n9", "expected": "0 1"}]
    assert question.time_limit_seconds == 5
    assert question.supported_languages == ["python", "java"]
    assert question.title == "Two Sum"

    # The grading cases are absent from the contract entirely.
    dump = question.model_dump()
    assert "hidden_cases" not in dump
    assert "hidden_cases" not in schemas.CandidateAssessmentQuestionOut.model_fields


def test_start_render_questions_in_configured_order(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, **_active_window())
    section = _section(
        db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude, "Aptitude"
    )
    # Inserted out of order on purpose.
    third = _mcq(db, section, 3, text="Third")
    first = _mcq(db, section, 1, text="First")
    second = _mcq(db, section, 2, text="Second")
    _assignment(db, assessment, candidate)

    out = start_my_assessment(assessment.id, candidate, db)

    assert [q.id for q in out.sections[0].questions] == [first.id, second.id, third.id]
    assert [q.question_text for q in out.sections[0].questions] == [
        "First", "Second", "Third",
    ]
    assert [q.question_order for q in out.sections[0].questions] == [1, 2, 3]


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_start_candidate_only_rbac(db):
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


# ---------------------------------------------------------------------------
# Existing endpoints remain unaffected
# ---------------------------------------------------------------------------
def test_company_and_candidate_endpoints_unaffected_after_start(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, **_active_window())
    _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude, "Aptitude")
    assignment = _assignment(db, assessment, candidate)

    start_my_assessment(assessment.id, candidate, db)

    # Candidate listing/detail reflect the new state consistently.
    listed = list_my_assessments(candidate, db)
    assert [a.id for a in listed] == [assignment.id]
    assert listed[0].status == models.AssessmentAssignmentStatusEnum.in_progress
    assert listed[0].started_at is not None
    detail = get_my_assessment(assessment.id, candidate, db)
    assert detail.status == models.AssessmentAssignmentStatusEnum.in_progress

    # Company endpoints still work and never gained candidate questions.
    assert [a.id for a in list_assessments(owner, db)] == [assessment.id]
    assert get_assessment(assessment.id, owner, db).id == assessment.id
    db.refresh(assessment)
    assert len(assessment.sections) == 1

    # The start contract carries no company-internal fields.
    assert "company_id" not in schemas.CandidateAssessmentStartOut.model_fields
    assert "marks" not in schemas.CandidateAssessmentQuestionOut.model_fields
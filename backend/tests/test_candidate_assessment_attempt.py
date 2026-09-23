"""Candidate Company Assessment re-entry (attempt) tests.

Exercises ``GET /me/assessments/{id}/attempt`` directly (user, session)
against an in-memory SQLite engine with ``foreign_keys=ON`` over just the
pipeline tables. The Docker code executor is mocked per-test. Covers: the
not-started guard, the not-yet-started 400, full content + empty answers on a
fresh attempt, restoring the candidate's own saved MCQ and coding answers in
question order, expiry finalization (auto-submit) while still returning the
answers, the submitted snapshot, cross-candidate isolation (404), candidate-safe
serialization (no correct answers / hidden cases / stored code / per-case I/O),
and RBAC. No network, no external DB.
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.auth import RoleChecker
from app.routes.candidate_assessment_answer import (
    get_my_attempt,
    save_assessment_answer,
)
from app.routes.candidate_assessments import candidate_only
from app.services.code_executor import ExecutionResult, TestCaseResult as _TestCase

QUESTIONS = "app.routes.candidate_assessment_answer.execute_code"


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
        m.Notification.__table__,
    ]
    m.Base.metadata.create_all(engine, tables=tables)
    s = Session(engine)
    yield s
    s.close()
    engine.dispose()


@pytest.fixture
def fake_executor(monkeypatch):
    def fake(language, code, test_cases, time_limit=5, memory_limit_mb=256):
        cases = [
            _TestCase(
                case_index=i, passed=True, status="passed", time_ms=7
            )
            for i in range(len(test_cases))
        ]
        result = ExecutionResult()
        result.test_results = cases
        result.total_time_ms = sum(r.time_ms for r in cases)
        return result

    monkeypatch.setattr(QUESTIONS, fake)


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


def _company_user(db, id):
    return _user(db, id, role=models.RoleEnum.company, name="Recruiter")


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


def _mcq(db, section, order, text="Stable sort?", correct_index=0):
    q = models.AssessmentQuestion(
        section_id=section.id,
        question_type=models.AssessmentQuestionTypeEnum.mcq,
        question_text=text,
        question_order=order,
        options=["Merge sort", "Quick sort", "Heap sort", "Selection sort"],
        correct_index=correct_index,
        marks=5,
        explanation="Merge sort is stable.",
    )
    db.add(q)
    db.flush()
    return q


def _coding(db, section, order, title="Two Sum"):
    q = models.AssessmentQuestion(
        section_id=section.id,
        question_type=models.AssessmentQuestionTypeEnum.coding,
        question_text="Return indices summing to target.",
        question_order=order,
        title=title,
        category="arrays",
        difficulty="easy",
        input_format="Line 1: N",
        output_format="Two indices",
        constraints="2 <= N <= 1000",
        sample_cases=[{"input": "4\n2 7 11 15\n9", "expected": "0 1"}],
        hidden_cases=[
            {"input": "2\n3 3\n6", "expected": "0 1"},
            {"input": "5\n1 5 3 7 2\n9", "expected": "1 3"},
        ],
        time_limit_seconds=5,
        supported_languages=["python", "java"],
    )
    db.add(q)
    db.flush()
    return q


def _assignment(db, assessment, candidate,
                status=models.AssessmentAssignmentStatusEnum.in_progress, **kw):
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


def _mcq_payload(question, selected_option):
    return schemas.AssessmentAnswerSaveIn(
        question_id=question.id, selected_option=selected_option
    )


def _coding_payload(question, code='print("hi")', language="python"):
    return schemas.AssessmentAnswerSaveIn(
        question_id=question.id, code=code, language=language
    )


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def test_attempt_not_started_400(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.assigned,
    )

    with pytest.raises(HTTPException) as exc:
        get_my_attempt(assessment.id, candidate, db)
    assert exc.value.status_code == 400
    assert "not been started" in exc.value.detail


def test_attempt_missing_or_foreign_assessment_404(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(minutes=5),
    )

    for bad_id in (9999,):
        with pytest.raises(HTTPException) as exc:
            get_my_attempt(bad_id, candidate, db)
        assert exc.value.status_code == 404


def test_attempt_other_candidates_attempt_404(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    ada = _user(db, 10)
    grace = _user(db, 11)
    assessment = _assessment(db, company)
    _assignment(
        db, assessment, ada,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(minutes=5),
    )

    with pytest.raises(HTTPException) as exc:
        get_my_attempt(assessment.id, grace, db)
    assert exc.value.status_code == 404

    # The owner can still read their own attempt unscathed.
    out = get_my_attempt(assessment.id, ada, db)
    assert out.attempt_id is not None


# ---------------------------------------------------------------------------
# Fresh attempt
# ---------------------------------------------------------------------------
def test_attempt_returns_full_content_with_empty_answers(db):
    owner = _company_user(db, 1)
    company = _company(db, owner, name="Acme Recruiting")
    candidate = _user(db, 10)
    assessment = _assessment(db, company, title="Backend Screening")
    aptitude = _section(
        db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude, "Aptitude"
    )
    coding = _section(
        db, assessment, 2, models.AssessmentSectionTypeEnum.coding, "Coding"
    )
    mcq1 = _mcq(db, aptitude, 1, text="Q1")
    mcq2 = _mcq(db, aptitude, 2, text="Q2", correct_index=2)
    cod1 = _coding(db, coding, 1)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(minutes=5),
    )

    out = get_my_attempt(assessment.id, candidate, db)

    assert out.attempt_id == assignment.id
    assert out.assessment_id == assessment.id
    assert out.title == "Backend Screening"
    assert out.company_name == "Acme Recruiting"
    assert out.status == models.AssessmentAssignmentStatusEnum.in_progress
    assert out.started_at is not None
    assert out.deadline_at == out.started_at + timedelta(minutes=90)
    assert [s.id for s in out.sections] == [aptitude.id, coding.id]
    assert [q.id for q in out.sections[0].questions] == [mcq1.id, mcq2.id]
    assert [q.id for q in out.sections[1].questions] == [cod1.id]
    assert out.answers == []


# ---------------------------------------------------------------------------
# Restoring saved answers
# ---------------------------------------------------------------------------
def test_attempt_restores_saved_answers_in_question_order(db, fake_executor):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    aptitude = _section(
        db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude, "Aptitude"
    )
    coding = _section(
        db, assessment, 2, models.AssessmentSectionTypeEnum.coding, "Coding"
    )
    mcq1 = _mcq(db, aptitude, 1, text="Q1", correct_index=2)
    mcq2 = _mcq(db, aptitude, 2, text="Q2", correct_index=1)
    cod1 = _coding(db, coding, 1)
    _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(minutes=5),
    )

    save_assessment_answer(
        assessment.id, _mcq_payload(mcq1, 3), candidate, db
    )
    save_assessment_answer(
        assessment.id, _coding_payload(cod1, code='print("hi")', language="python"),
        candidate, db,
    )

    out = get_my_attempt(assessment.id, candidate, db)

    assert [a.question_id for a in out.answers] == [mcq1.id, cod1.id]
    assert out.answers[0].question_type == models.AssessmentQuestionTypeEnum.mcq
    assert out.answers[0].selected_option == 3
    assert out.answers[1].question_type == models.AssessmentQuestionTypeEnum.coding
    assert out.answers[1].language == "python"
    assert out.answers[1].passed_cases == 2
    assert out.answers[1].total_cases == 2
    assert out.answers[1].status == "passed"

    # The candidate whose attempt it is can re-enter repeatedly.
    again = get_my_attempt(assessment.id, candidate, db)
    assert [a.question_id for a in again.answers] == [mcq1.id, cod1.id]
    assert again.status == models.AssessmentAssignmentStatusEnum.in_progress
    assert again.started_at == out.started_at


# ---------------------------------------------------------------------------
# Expiry finalization
# ---------------------------------------------------------------------------
def test_attempt_finalizes_expired_attempt_and_returns_submitted(db, fake_executor):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, duration_minutes=90)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    mcq = _mcq(db, section, 1, correct_index=2)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(minutes=5),
    )

    # Answer saved while the deadline (start + 90 min) is still in the future.
    save_assessment_answer(assessment.id, _mcq_payload(mcq, 0), candidate, db)

    # The clock moved on: push started_at far enough that the deadline is past.
    db.execute(
        update(models.AssessmentAssignment)
        .where(models.AssessmentAssignment.id == assignment.id)
        .values(started_at=_now() - timedelta(hours=2))
    )
    db.commit()
    db.expire_all()

    out = get_my_attempt(assessment.id, candidate, db)

    # The auto-submit happened atomically on read (deadline = start + duration,
    # both in the past), and the saved answer is still returned.
    assert out.status == models.AssessmentAssignmentStatusEnum.submitted
    assert out.submitted_at == out.started_at + timedelta(minutes=90)
    assert [a.question_id for a in out.answers] == [mcq.id]

    row = (
        db.query(models.AssessmentAssignment)
        .filter(models.AssessmentAssignment.id == out.attempt_id)
        .one()
    )
    assert row.status == models.AssessmentAssignmentStatusEnum.submitted
    assert row.submitted_at == row.started_at + timedelta(minutes=90)


def test_attempt_submitted_returns_snapshot_idempotently(db, fake_executor):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    mcq = _mcq(db, section, 1, correct_index=1)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(minutes=5),
    )
    save_assessment_answer(assessment.id, _mcq_payload(mcq, 2), candidate, db)

    # Move the attempt into the submitted state (as a prior submit would have).
    db.execute(
        update(models.AssessmentAssignment)
        .where(models.AssessmentAssignment.id == assignment.id)
        .values(
            status=models.AssessmentAssignmentStatusEnum.submitted,
            submitted_at=_now() - timedelta(hours=1),
        )
    )
    db.commit()
    db.expire_all()

    out = get_my_attempt(assessment.id, candidate, db)

    assert out.status == models.AssessmentAssignmentStatusEnum.submitted
    assert [a.question_id for a in out.answers] == [mcq.id]
    assert out.answers[0].selected_option == 2


# ---------------------------------------------------------------------------
# Candidate safety
# ---------------------------------------------------------------------------
def test_attempt_never_exposes_private_evaluation_data(db, fake_executor):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    aptitude = _section(
        db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude, "Aptitude"
    )
    coding = _section(
        db, assessment, 2, models.AssessmentSectionTypeEnum.coding, "Coding"
    )
    mcq = _mcq(db, aptitude, 1, correct_index=3)
    cod = _coding(db, coding, 1, title="Hidden")
    _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(minutes=5),
    )

    save_assessment_answer(assessment.id, _mcq_payload(mcq, 1), candidate, db)
    save_assessment_answer(
        assessment.id, _coding_payload(cod, code="secret draft", language="python"),
        candidate, db,
    )

    out = get_my_attempt(assessment.id, candidate, db)

    # Question contracts never carry private fields.
    for section in out.sections:
        for question in section.questions:
            dump = question.model_dump()
            for private in ("correct_index", "marks", "explanation", "hidden_cases"):
                assert private not in dump

    # Answer contracts never leak correctness, the stored code draft, or the
    # hidden-case I/O.
    for answer in out.answers:
        dump = answer.model_dump()
        for private in ("is_correct", "code", "correct_index", "hidden_cases"):
            assert private not in dump
        for result in dump.get("results", []):
            assert "input" not in result
            assert "output" not in result
            assert "expected" not in result

    assert "code" not in schemas.AssessmentAnswerOut.model_fields
    assert "is_correct" not in schemas.AssessmentAnswerOut.model_fields


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_attempt_candidate_only_rbac(db):
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
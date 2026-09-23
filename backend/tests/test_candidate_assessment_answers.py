"""Company Assessment answer submission tests (save / submit / auto-submit).

Exercises ``POST /me/assessments/{id}/answers`` and ``POST
/me/assessments/{id}/submit`` directly (user, session) against an in-memory
SQLite engine with ``foreign_keys=ON`` over just the pipeline tables. The
Docker code executor is mocked per-test (nothing ever executes on the host);
one test asserts the route delegates to the shared executor. Covers MCQ
save/update (server-computed correctness, idempotent upsert), coding grading
verdicts (candidate-safe results), invalid question/assessment combinations,
cross-candidate isolation, state guards (not started / submitted / deadline),
atomic + idempotent final submission, expired auto-submit finalization, RBAC,
and candidate-safe serialization (no correct answers / hidden cases). No
network, no external DB.
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.auth import RoleChecker
from app.routes.candidate_assessment_answer import (
    save_assessment_answer,
    submit_assessment,
)
from app.routes.candidate_assessments import (
    candidate_only,
    get_my_assessment,
    get_my_assignment,
)
from app.routes.company_assessments import list_assessments
from app.services.code_executor import (
    ExecutionResult,
    TestCaseResult as _TestCase,
)

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


def _coding(db, section, order, languages=None, hidden_cases=None,
            time_limit=5):
    q = models.AssessmentQuestion(
        section_id=section.id,
        question_type=models.AssessmentQuestionTypeEnum.coding,
        question_text="Return indices summing to target.",
        question_order=order,
        title="Two Sum",
        category="arrays",
        difficulty="easy",
        input_format="Line 1: N",
        output_format="Two indices",
        constraints="2 <= N <= 1000",
        sample_cases=[{"input": "4\n2 7 11 15\n9", "expected": "0 1"}],
        hidden_cases=(
            hidden_cases
            if hidden_cases is not None
            else [
                {"input": "2\n3 3\n6", "expected": "0 1"},
                {"input": "5\n1 5 3 7 2\n9", "expected": "1 3"},
            ]
        ),
        time_limit_seconds=time_limit,
        supported_languages=languages or ["python", "java"],
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


def _expired_assignment(assessment, db, candidate):
    """An in-progress assignment whose deadline (start + duration) is past."""
    return _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now() - timedelta(hours=2),
    )


def _mcq_payload(question, selected_option):
    return schemas.AssessmentAnswerSaveIn(
        question_id=question.id, selected_option=selected_option
    )


def _coding_payload(question, code='print("hi")', language="python"):
    return schemas.AssessmentAnswerSaveIn(
        question_id=question.id, code=code, language=language
    )


def _exec_result(*cases):
    result = ExecutionResult()
    result.test_results = list(cases)
    result.total_time_ms = sum(r.time_ms for r in result.test_results)
    return result


def _passed_case(index=0, time_ms=7):
    return _TestCase(
        case_index=index, passed=True, status="passed", time_ms=time_ms
    )


def _failed_case(index=1):
    return _TestCase(
        case_index=index, passed=False, status="wrong_answer", time_ms=8
    )


@pytest.fixture
def fake_executor(monkeypatch):
    """Route saves delegate to the (shared Docker) executor, mocked here."""
    calls = []

    def fake(language, code, test_cases, time_limit=5, memory_limit_mb=256):
        calls.append((language, code, list(test_cases), time_limit))
        return _exec_result(*(_passed_case(i) for i in range(len(test_cases))))

    monkeypatch.setattr(QUESTIONS, fake)
    return calls


def _answers(db, assignment_id):
    return (
        db.query(models.AssessmentAnswer)
        .filter(models.AssessmentAnswer.assignment_id == assignment_id)
        .all()
    )


# ---------------------------------------------------------------------------
# MCQ save / update
# ---------------------------------------------------------------------------
def test_save_mcq_answer_persists_and_computes_correctness_server_side(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    question = _mcq(db, section, 1, correct_index=2)
    assignment = _assignment(db, assessment, candidate)

    out = save_assessment_answer(
        assessment.id, _mcq_payload(question, 1), candidate, db
    )

    assert out.question_id == question.id
    assert out.question_type == models.AssessmentQuestionTypeEnum.mcq
    assert out.selected_option == 1
    # Correctness is never exposed — but it IS persisted (server-side).
    assert "is_correct" not in schemas.AssessmentAnswerOut.model_fields
    row = _answers(db, assignment.id)[0]
    assert row.selected_option == 1
    assert row.is_correct is False
    # No coding fields are persisted for an MCQ answer.
    assert row.code is None and row.status is None and row.language is None


def test_save_mcq_answer_is_idempotent_upsert(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    question = _mcq(db, section, 1, correct_index=2)
    assignment = _assignment(db, assessment, candidate)

    first = save_assessment_answer(
        assessment.id, _mcq_payload(question, 1), candidate, db
    )
    second = save_assessment_answer(
        assessment.id, _mcq_payload(question, 2), candidate, db
    )

    assert len(_answers(db, assignment.id)) == 1  # never a duplicate row
    assert first.selected_option == 1
    assert second.selected_option == 2
    row = _answers(db, assignment.id)[0]
    assert row.selected_option == 2
    assert row.is_correct is True  # in-range: correct_index==2
    assert second.updated_at >= row.created_at


def test_save_mcq_answer_validates_option_bounds(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    question = _mcq(db, section, 1)
    _assignment(db, assessment, candidate)

    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(
            assessment.id, _mcq_payload(question, 99), candidate, db
        )
    assert exc.value.status_code == 400
    assert "out of range" in exc.value.detail
    # Negative indexes are rejected at the schema boundary.
    with pytest.raises(ValidationError):
        schemas.AssessmentAnswerSaveIn(question_id=question.id, selected_option=-1)


def test_save_rejects_mixed_or_missing_answer_modes(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    question = _mcq(
        db, _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude), 1
    )

    with pytest.raises(ValidationError):
        schemas.AssessmentAnswerSaveIn(question_id=question.id)
    with pytest.raises(ValidationError):
        schemas.AssessmentAnswerSaveIn(
            question_id=question.id,
            selected_option=0,
            code="print(1)",
            language="python",
        )
    with pytest.raises(ValidationError):
        schemas.AssessmentAnswerSaveIn(
            question_id=question.id, language="python"
        )
    with pytest.raises(ValidationError):
        schemas.AssessmentAnswerSaveIn(question_id=question.id, code="")


# ---------------------------------------------------------------------------
# Coding save / grading
# ---------------------------------------------------------------------------
def test_coding_answers_run_through_docker_executor(db, fake_executor):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.coding)
    question = _coding(db, section, 1, time_limit=7)
    assignment = _assignment(db, assessment, candidate)

    code = "nums = list(map(int, input().split()))"
    out = save_assessment_answer(
        assessment.id, _coding_payload(question, code=code), candidate, db
    )

    # The route delegated to the shared executor with the HIDDEN cases + the
    # question's time limit — the code is never executed on the host.
    assert len(fake_executor) == 1
    language, called_code, cases, time_limit = fake_executor[0]
    assert language == "python"
    assert called_code == code
    assert cases == question.hidden_cases
    assert time_limit == 7

    assert out.question_type == models.AssessmentQuestionTypeEnum.coding
    assert out.status == "passed"
    assert out.passed_cases == 2
    assert out.total_cases == 2
    assert out.score == 100
    assert out.language == "python"
    assert out.error_message is None

    row = _answers(db, assignment.id)[0]
    assert row is not None
    assert row.code == code


def test_save_coding_persists_grading_verdict_and_code(db, monkeypatch):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.coding)
    question = _coding(db, section, 1)
    assignment = _assignment(db, assessment, candidate)

    def fake(language, code, test_cases, time_limit=5, memory_limit_mb=256):
        return _exec_result(_passed_case(0), _failed_case(1))

    monkeypatch.setattr(QUESTIONS, fake)
    code = "print('partial')"
    out = save_assessment_answer(
        assessment.id, _coding_payload(question, code=code), candidate, db
    )

    assert out.status == "failed"
    assert out.passed_cases == 1
    assert out.total_cases == 2
    assert out.score == 50
    assert out.execution_time_ms == 15
    assert [r.case_index for r in out.results] == [0, 1]
    assert [r.passed for r in out.results] == [True, False]

    row = _answers(db, assignment.id)[0]
    assert row.code == code
    assert row.language == "python"
    assert row.status == "failed"
    assert row.is_correct is None
    assert row.selected_option is None


def test_save_coding_compile_error_persists_error_state(db, monkeypatch):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.coding)
    question = _coding(db, section, 1)
    assignment = _assignment(db, assessment, candidate)

    def fake(language, code, test_cases, time_limit=5, memory_limit_mb=256):
        return ExecutionResult(
            compile_error=True,
            compile_stderr="expected ';'",
            test_results=[],
        )

    monkeypatch.setattr(QUESTIONS, fake)
    out = save_assessment_answer(
        assessment.id,
        _coding_payload(question, code="void main( {"),
        candidate,
        db,
    )

    assert out.status == "error"
    assert out.score == 0
    assert out.passed_cases == 0
    assert "expected ';'" in out.error_message
    row = _answers(db, assignment.id)[0]
    assert row.status == "error"


def test_save_coding_validates_language_and_code_before_execution(
    db, monkeypatch
):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.coding)
    question = _coding(db, section, 1, languages=["python", "java"])
    _assignment(db, assessment, candidate)

    calls = []

    def fake(language, code, test_cases, time_limit=5, memory_limit_mb=256):
        calls.append(language)
        return _exec_result()

    monkeypatch.setattr(QUESTIONS, fake)

    # Language not supported by THIS question.
    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(
            assessment.id, _coding_payload(question, language="cpp"), candidate, db
        )
    assert exc.value.status_code == 400
    assert "python" in exc.value.detail and "java" in exc.value.detail
    assert calls == []

    # Oversized code is rejected without invoking the executor.
    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(
            assessment.id,
            _coding_payload(question, code="x" * (64 * 1024 + 1)),
            candidate,
            db,
        )
    assert exc.value.status_code == 400
    assert calls == []  # the executor was never reached


def test_answer_type_must_match_question_type(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    mcq_section = _section(
        db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude
    )
    coding_section = _section(
        db, assessment, 2, models.AssessmentSectionTypeEnum.coding
    )
    mcq_q = _mcq(db, mcq_section, 1)
    coding_q = _coding(db, coding_section, 1)
    assignment = _assignment(db, assessment, candidate)

    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(
            assessment.id, _mcq_payload(coding_q, 0), candidate, db
        )
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(
            assessment.id, _coding_payload(mcq_q), candidate, db
        )
    assert exc.value.status_code == 400
    assert _answers(db, assignment.id) == []
    assert (
        db.query(models.AssessmentAnswer).count() == 0
    )  # nothing persisted on reject


# ---------------------------------------------------------------------------
# Candidate-safe coding serialization
# ---------------------------------------------------------------------------
def test_coding_grading_never_leaks_hidden_cases(db, monkeypatch):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.coding)
    question = _coding(db, section, 1)
    assignment = _assignment(db, assessment, candidate)

    def fake(language, code, test_cases, time_limit=5, memory_limit_mb=256):
        return _exec_result(_passed_case(0), _failed_case(1))

    monkeypatch.setattr(QUESTIONS, fake)
    out = save_assessment_answer(
        assessment.id, _coding_payload(question), candidate, db
    )

    dump = out.model_dump()
    assert "hidden_cases" not in dump
    assert "is_correct" not in dump
    assert "correct_index" not in dump
    for result in out.results:
        item = result.model_dump()
        assert item.keys() == {
            "case_index", "passed", "status", "stdout", "stderr", "time_ms",
        }
        assert item["stdout"] == "" and item["stderr"] == ""

    # The stored results carry only index/pass/status/time too.
    row = _answers(db, assignment.id)[0]
    for stored in row.results:
        assert set(stored.keys()) == {"case_index", "passed", "status", "time_ms"}
        assert "input" not in stored and "expected" not in stored

    for private in ("correct_index", "hidden_cases", "is_correct"):
        assert private not in schemas.AssessmentAnswerOut.model_fields


# ---------------------------------------------------------------------------
# Invalid question/assessment combinations
# ---------------------------------------------------------------------------
def test_save_question_from_another_assessment_400(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    a1 = _assessment(db, company, title="One")
    a2 = _assessment(db, company, title="Two")
    q_of_a2 = _mcq(
        db, _section(db, a2, 1, models.AssessmentSectionTypeEnum.aptitude), 1
    )
    _assignment(db, a1, candidate)

    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(a1.id, _mcq_payload(q_of_a2, 0), candidate, db)
    assert exc.value.status_code == 400
    assert "does not belong" in exc.value.detail
    assert db.query(models.AssessmentAnswer).count() == 0


def test_save_unknown_question_400(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    _assignment(db, assessment, candidate)

    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(
            assessment.id,
            schemas.AssessmentAnswerSaveIn(
                question_id=9999, selected_option=0
            ),
            candidate,
            db,
        )
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# State / deadline enforcement
# ---------------------------------------------------------------------------
def test_save_before_start_400(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    question = _mcq(
        db, _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude), 1
    )
    _assignment(db, assessment, candidate, status=models.AssessmentAssignmentStatusEnum.assigned)

    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(
            assessment.id, _mcq_payload(question, 0), candidate, db
        )
    assert exc.value.status_code == 400
    assert "not been started" in exc.value.detail


def test_save_after_submission_409(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    question = _mcq(
        db, _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude), 1
    )
    _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=_now() - timedelta(hours=1),
        submitted_at=_now() - timedelta(minutes=10),
    )

    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(
            assessment.id, _mcq_payload(question, 0), candidate, db
        )
    assert exc.value.status_code == 409
    assert "already been submitted" in exc.value.detail


def test_save_after_deadline_auto_submits_then_409(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    # duration 10 minutes, started 2h ago → deadline long passed.
    assessment = _assessment(db, company, duration_minutes=10)
    question = _mcq(
        db, _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude), 1
    )
    assignment = _expired_assignment(assessment, db, candidate)
    deadline = assignment.started_at + timedelta(minutes=10)

    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(
            assessment.id, _mcq_payload(question, 0), candidate, db
        )
    assert exc.value.status_code == 409
    assert "deadline" in exc.value.detail

    # The assessment is finalized (auto-submit), not left in_progress.
    db.refresh(assignment)
    assert assignment.status == models.AssessmentAssignmentStatusEnum.submitted
    assert assignment.submitted_at == deadline

    # A further save now reports the submitted state.
    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(
            assessment.id, _mcq_payload(question, 0), candidate, db
        )
    assert exc.value.status_code == 409
    assert "already been submitted" in exc.value.detail
    assert db.query(models.AssessmentAnswer).count() == 0


# ---------------------------------------------------------------------------
# Final submission
# ---------------------------------------------------------------------------
def test_submit_success_persists_state_and_is_idempotent(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude)
    q1 = _mcq(db, section, 1)
    q2 = _mcq(db, section, 2, text="Second?", correct_index=1)
    assignment = _assignment(db, assessment, candidate)
    save_assessment_answer(assessment.id, _mcq_payload(q1, 0), candidate, db)
    save_assessment_answer(assessment.id, _mcq_payload(q2, 1), candidate, db)

    out = submit_assessment(assessment.id, candidate, db)
    assert out.attempt_id == assignment.id
    assert out.assessment_id == assessment.id
    assert out.status == models.AssessmentAssignmentStatusEnum.submitted
    assert out.submitted_at is not None
    assert out.answered_count == 2

    # Idempotent: a second submit returns the exact same final state.
    again = submit_assessment(assessment.id, candidate, db)
    assert again.status == models.AssessmentAssignmentStatusEnum.submitted
    assert again.submitted_at == out.submitted_at
    assert again.answered_count == 2

    db.refresh(assignment)
    assert assignment.status == models.AssessmentAssignmentStatusEnum.submitted
    assert assignment.submitted_at == out.submitted_at


def test_submit_before_start_400(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    _assignment(db, assessment, candidate, status=models.AssessmentAssignmentStatusEnum.assigned)

    with pytest.raises(HTTPException) as exc:
        submit_assessment(assessment.id, candidate, db)
    assert exc.value.status_code == 400
    assert "not been started" in exc.value.detail


def test_submit_is_atomic_for_concurrent_calls(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    assignment = _assignment(db, assessment, candidate)

    first = submit_assessment(assessment.id, candidate, db)
    second = submit_assessment(assessment.id, candidate, db)

    # Exactly one transition — the second call is a harmless re-read.
    assert first.status == models.AssessmentAssignmentStatusEnum.submitted
    assert second.submitted_at == first.submitted_at
    db.refresh(assignment)
    assert assignment.submitted_at == first.submitted_at
    assert (
        db.query(models.AssessmentAssignment)
        .filter(models.AssessmentAssignment.id == assignment.id)
        .count()
        == 1
    )


def test_submit_after_deadline_finalizes_with_deadline_timestamp(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company, duration_minutes=10)
    assignment = _expired_assignment(assessment, db, candidate)
    deadline = assignment.started_at + timedelta(minutes=10)

    out = submit_assessment(assessment.id, candidate, db)

    assert out.status == models.AssessmentAssignmentStatusEnum.submitted
    assert out.submitted_at == deadline
    db.refresh(assignment)
    assert assignment.status == models.AssessmentAssignmentStatusEnum.submitted
    assert assignment.submitted_at == deadline


# ---------------------------------------------------------------------------
# Isolation / RBAC
# ---------------------------------------------------------------------------
def test_cross_candidate_answer_isolation(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    ada = _user(db, 10)
    grace = _user(db, 11)
    stranger = _user(db, 12)
    assessment = _assessment(db, company)
    question = _mcq(
        db, _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude), 1
    )
    ada_assignment = _assignment(db, assessment, ada)
    grace_assignment = _assignment(db, assessment, grace)

    save_assessment_answer(assessment.id, _mcq_payload(question, 1), ada, db)
    # Grace's save goes to HER OWN attempt — never to Ada's.
    grace_out = save_assessment_answer(
        assessment.id, _mcq_payload(question, 3), grace, db
    )
    assert grace_out.selected_option == 3

    assert len(_answers(db, ada_assignment.id)) == 1
    assert _answers(db, ada_assignment.id)[0].selected_option == 1
    assert len(_answers(db, grace_assignment.id)) == 1
    assert _answers(db, grace_assignment.id)[0].selected_option == 3

    # Each candidate submits only their own attempt.
    ada_submit = submit_assessment(assessment.id, ada, db)
    grace_submit = submit_assessment(assessment.id, grace, db)
    assert ada_submit.attempt_id == ada_assignment.id
    assert grace_submit.attempt_id == grace_assignment.id
    assert ada_submit.status == grace_submit.status

    db.refresh(ada_assignment)
    db.refresh(grace_assignment)
    assert ada_assignment.submitted_at == ada_submit.submitted_at
    assert grace_assignment.submitted_at == grace_submit.submitted_at

    # A candidate with no assignment at all is rejected with 404.
    with pytest.raises(HTTPException) as exc:
        save_assessment_answer(
            assessment.id, _mcq_payload(question, 0), stranger, db
        )
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        submit_assessment(assessment.id, stranger, db)
    assert exc.value.status_code == 404


def test_rbac_company_and_admin_denied(db):
    candidate = _user(db, 10)
    company_user = _company_user(db, 1)
    admin = _admin_user(db, 9)

    with pytest.raises(HTTPException) as exc:
        candidate_only(current_user=company_user)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        candidate_only(current_user=admin)
    assert exc.value.status_code == 403
    assert candidate_only(current_user=candidate) is not None
    assert RoleChecker(["user"])(current_user=candidate) is not None


# ---------------------------------------------------------------------------
# Candidate-safe responses + surfacing existing endpoints
# ---------------------------------------------------------------------------
def test_answer_out_never_exposes_private_fields(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    question = _mcq(
        db, _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude), 1,
        correct_index=3,
    )
    _assignment(db, assessment, candidate)

    out = save_assessment_answer(
        assessment.id, _mcq_payload(question, 3), candidate, db
    )

    dump = out.model_dump()
    for private in ("is_correct", "correct_index", "hidden_cases",
                    "explanation", "marks"):
        assert private not in dump
        assert private not in schemas.AssessmentAnswerOut.model_fields
    # The candidate's own selection is the only answer content returned.
    assert out.selected_option == 3


def test_submit_and_answers_keep_existing_endpoints_consistent(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    question = _mcq(
        db, _section(db, assessment, 1, models.AssessmentSectionTypeEnum.aptitude), 1
    )
    assignment = _assignment(db, assessment, candidate)
    save_assessment_answer(assessment.id, _mcq_payload(question, 0), candidate, db)

    out = submit_assessment(assessment.id, candidate, db)
    assert out.answered_count == 1

    # Existing candidate read APIs reflect the final state.
    status_out = get_my_assignment(assessment.id, candidate, db)
    assert status_out.status == models.AssessmentAssignmentStatusEnum.submitted
    detail = get_my_assessment(assessment.id, candidate, db)
    assert detail.status == models.AssessmentAssignmentStatusEnum.submitted
    assert detail.submitted_at == out.submitted_at

    # Company endpoints unaffected and raise no candidate internals.
    assert [a.id for a in list_assessments(owner, db)] == [assessment.id]
    assert assignment.answers is not None
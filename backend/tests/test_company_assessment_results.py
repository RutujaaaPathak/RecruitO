"""Company Assessment Results API tests.

Exercises the company/admin-only results endpoints (``GET
/assessments/{id}/results`` and ``GET /assessments/{id}/results/{assignment_id}``)
directly (payload, user, session) against an in-memory SQLite engine with
``foreign_keys=ON`` over just the pipeline tables. Answers are seeded directly
onto ``assessment_answers`` from persisted verdicts (exactly what the answer
submission routes store), so scoring is exercised without any Docker executor.
Covers list/detail, total/max/percentage scoring, section-wise breakdown,
coding proportional + compile-error grading, incomplete in-progress attempts,
expired (auto-submitted) attempts, zero-question and zero-mark edge cases,
missing-marks default, deterministic output, company ownership isolation,
unknown-assignment 404s, unassigned-candidate privacy, admin access, candidate
RBAC, and hidden coding-test / execution-I/O privacy. No network, no external DB.
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.routes.company_assessment_results import get_result, list_results
from app.routes.company_assessments import company_scoped


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
    kw.setdefault("status", models.CompanyAssessmentStatusEnum.published)
    kw.setdefault("duration_minutes", 60)
    a = models.Assessment(company_id=company.id, title=title, **kw)
    db.add(a)
    db.flush()
    return a


def _section(db, assessment, section_type, order=1, marks=10, title=None):
    s = models.AssessmentSection(
        assessment_id=assessment.id,
        section_type=section_type,
        title=title or section_type.value.title(),
        section_order=order,
        marks=marks,
    )
    db.add(s)
    db.flush()
    return s


def _mcq(db, section, order, marks=5, correct_index=0, text="Q", options=None):
    q = models.AssessmentQuestion(
        section_id=section.id,
        question_type=models.AssessmentQuestionTypeEnum.mcq,
        question_text=text,
        question_order=order,
        options=options or ["A", "B", "C", "D"],
        correct_index=correct_index,
        marks=marks,
        explanation="Because.",
    )
    db.add(q)
    db.flush()
    return q


def _coding(db, section, order, marks=10, time_limit=5, title="Two Sum"):
    q = models.AssessmentQuestion(
        section_id=section.id,
        question_type=models.AssessmentQuestionTypeEnum.coding,
        question_text="Code the solution.",
        question_order=order,
        title=title,
        category="arrays",
        difficulty="easy",
        marks=marks,
        input_format="N",
        output_format="index",
        constraints="1 <= N <= 1000",
        sample_cases=[{"input": "1", "expected": "0"}],
        hidden_cases=[{"input": "2", "expected": "1"}],
        time_limit_seconds=time_limit,
        supported_languages=["python", "java"],
    )
    db.add(q)
    db.flush()
    return q


def _now():
    return datetime(2026, 1, 1, 10, 0, 0)


def _assignment(db, assessment, candidate, status, started_at=None,
                submitted_at=None, assigned_at=None):
    a = models.AssessmentAssignment(
        assessment_id=assessment.id,
        candidate_id=candidate.id,
        status=status,
        assigned_at=assigned_at or _now(),
        started_at=started_at,
        submitted_at=submitted_at,
    )
    db.add(a)
    db.flush()
    return a


def _mcq_answer(db, assignment, question, selected_option, correct=None):
    if correct is None:
        correct = selected_option == question.correct_index
    answer = models.AssessmentAnswer(
        assignment_id=assignment.id,
        question_id=question.id,
        selected_option=selected_option,
        is_correct=correct,
    )
    db.add(answer)
    db.flush()
    return answer


def _coding_answer(db, assignment, question, status="passed", score=100,
                   passed_cases=2, total_cases=2, exec_ms=15, code="print(1)",
                   language="python", results=None, error_message=None):
    if results is None:
        results = [
            {"case_index": i, "passed": True, "status": "passed", "time_ms": 7}
            for i in range(passed_cases)
        ]
    answer = models.AssessmentAnswer(
        assignment_id=assignment.id,
        question_id=question.id,
        language=language,
        code=code,
        status=status,
        passed_cases=passed_cases,
        total_cases=total_cases,
        score=score,
        execution_time_ms=exec_ms,
        error_message=error_message,
        results=results,
    )
    db.add(answer)
    db.flush()
    return answer


def _canonical(db):
    """The canonical scoring scenario.

    Section S1 (aptitude): MCQ Q1 marks=2 (correct), MCQ Q2 marks=3 (wrong),
    MCQ Q3 marks=None->1 (correct). Section S2 (coding): Q4 marks=10 passed,
    Q5 marks=4 with 50% score, Q6 marks=None unanswered. Totals: 6 questions,
    5 answered, 21 max, 15 earned, 71%.
    """
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10, name="Grace Hopper", )
    candidate.email = "grace@acme.com"
    assessment = _assessment(db, company)
    s1 = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude, order=1)
    s2 = _section(db, assessment, models.AssessmentSectionTypeEnum.coding, order=2)
    q1 = _mcq(db, s1, 1, marks=2, correct_index=0, text="Q1")
    q2 = _mcq(db, s1, 2, marks=3, correct_index=1, text="Q2")
    q3 = _mcq(db, s1, 3, marks=None, correct_index=2, text="Q3")
    q4 = _coding(db, s2, 1, marks=10)
    q5 = _coding(db, s2, 2, marks=4)
    q6 = _coding(db, s2, 3, marks=None)
    assignment = _assignment(
        db,
        assessment,
        candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=_now(),
        submitted_at=_now() + timedelta(minutes=45),
    )
    a1 = _mcq_answer(db, assignment, q1, 0)
    a2 = _mcq_answer(db, assignment, q2, 0)
    a3 = _mcq_answer(db, assignment, q3, 2)
    a4 = _coding_answer(db, assignment, q4, status="passed", score=100,
                        passed_cases=3, total_cases=3)
    a5 = _coding_answer(db, assignment, q5, status="failed", score=50,
                        passed_cases=1, total_cases=2)
    db.commit()
    return {
        "owner": owner,
        "company": company,
        "candidate": candidate,
        "assessment": assessment,
        "s1": s1,
        "s2": s2,
        "q1": q1,
        "q2": q2,
        "q3": q3,
        "q4": q4,
        "q5": q5,
        "q6": q6,
        "assignment": assignment,
        "a4": a4,
    }


# ---------------------------------------------------------------------------
# List results
# ---------------------------------------------------------------------------
def test_list_results_includes_every_assigned_candidate_in_stable_order(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate_a = _user(db, 10)
    candidate_b = _user(db, 11)
    candidate_c = _user(db, 12)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    question = _mcq(db, section, 1, marks=2)
    sub = _assignment(
        db, assessment, candidate_a,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=_now(),
        submitted_at=_now() + timedelta(minutes=30),
    )
    prog = _assignment(
        db, assessment, candidate_b,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now(),
    )
    assigned = _assignment(
        db, assessment, candidate_c,
        status=models.AssessmentAssignmentStatusEnum.assigned,
    )
    _mcq_answer(db, sub, question, 0)
    _mcq_answer(db, prog, question, 1)

    rows = list_results(assessment.id, owner, db)

    assert [r.assignment_id for r in rows] == [sub.id, prog.id, assigned.id]
    assert [r.status for r in rows] == [
        models.AssessmentAssignmentStatusEnum.submitted,
        models.AssessmentAssignmentStatusEnum.in_progress,
        models.AssessmentAssignmentStatusEnum.assigned,
    ]
    assert [r.candidate_name for r in rows] == [
        candidate_a.name, candidate_b.name, candidate_c.name,
    ]
    assert [r.candidate_email for r in rows] == [
        candidate_a.email, candidate_b.email, candidate_c.email,
    ]
    assert rows[0].assigned_at == sub.assigned_at
    assert rows[0].submitted_at == sub.submitted_at
    assert rows[1].started_at == prog.started_at
    assert rows[1].submitted_at is None
    assert rows[2].started_at is None
    assert rows[2].submitted_at is None
    # Partial/wrong answers are reflected truthfully for every state.
    assert rows[0].answered_questions == 1
    assert rows[0].total_score == 2
    assert rows[1].answered_questions == 1
    assert rows[1].total_score == 0
    assert rows[2].answered_questions == 0
    assert rows[2].total_score == 0


def test_list_results_is_empty_for_assessment_without_assignments(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)

    assert list_results(assessment.id, owner, db) == []


def test_list_results_unassigned_candidates_never_appear(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assigned_candidate = _user(db, 10)
    unassigned_candidate = _user(db, 11)
    assessment = _assessment(db, company)
    other_assessment = _assessment(db, company, title="Other")
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    question = _mcq(db, section, 1)
    _assignment(
        db, assessment, assigned_candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=_now(), submitted_at=_now(),
    )
    # In another assessment but never this one.
    other_section = _section(
        db, other_assessment, models.AssessmentSectionTypeEnum.aptitude
    )
    other_question = _mcq(db, other_section, 1)
    stranger_assignment = _assignment(
        db, other_assessment, unassigned_candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
    )
    _mcq_answer(db, stranger_assignment, other_question, 0)

    rows = list_results(assessment.id, owner, db)

    assert [r.candidate_id for r in rows] == [assigned_candidate.id]
    assert unassigned_candidate.id not in {r.candidate_id for r in rows}


# ---------------------------------------------------------------------------
# Score / percentage / section-wise
# ---------------------------------------------------------------------------
def test_score_and_percentage_of_submitted_assessment(db):
    env = _canonical(db)
    owner = env["owner"]

    row = list_results(env["assessment"].id, owner, db)[0]

    assert row.total_questions == 6
    assert row.answered_questions == 5
    assert row.maximum_score == 21  # 2 + 3 + 1(default) + 10 + 4 + 1(default)
    assert row.total_score == 15  # 2 + 0 + 1 + 10 + 2 + 0
    assert row.percentage == 71  # round(15 / 21 * 100)


def test_section_wise_breakdown(db):
    env = _canonical(db)
    owner = env["owner"]

    row = list_results(env["assessment"].id, owner, db)[0]

    assert [s.section_id for s in row.sections] == [env["s1"].id, env["s2"].id]
    assert row.sections[0].title == "Aptitude"
    assert row.sections[0].total_questions == 3
    assert row.sections[0].answered_questions == 3
    assert row.sections[0].maximum_score == 6
    assert row.sections[0].total_score == 3
    assert row.sections[0].percentage == 50

    assert row.sections[1].section_type == models.AssessmentSectionTypeEnum.coding
    assert row.sections[1].total_questions == 3
    assert row.sections[1].answered_questions == 2
    assert row.sections[1].maximum_score == 15
    assert row.sections[1].total_score == 12
    assert row.sections[1].percentage == 80


def test_detail_question_level_performance(db):
    env = _canonical(db)
    owner = env["owner"]

    detail = get_result(env["assessment"].id, env["assignment"].id, owner, db)

    q = {q.question_id: q for q in detail.questions}
    assert len(detail.questions) == 6

    q1 = q[env["q1"].id]
    assert q1.question_type == models.AssessmentQuestionTypeEnum.mcq
    assert q1.answered is True
    assert q1.selected_option == 0
    assert q1.correct is True
    assert q1.earned_score == 2
    assert q1.max_score == 2
    assert q1.percentage == 100
    assert q1.status is None

    q2 = q[env["q2"].id]
    assert q2.correct is False
    assert q2.earned_score == 0
    assert q2.max_score == 3
    assert q2.percentage == 0

    q3 = q[env["q3"].id]
    assert q3.correct is True
    assert q3.max_score == 1  # missing marks default to 1
    assert q3.earned_score == 1

    q4 = q[env["q4"].id]
    assert q4.question_type == models.AssessmentQuestionTypeEnum.coding
    assert q4.correct is True
    assert q4.earned_score == 10
    assert q4.max_score == 10
    assert q4.percentage == 100
    assert q4.status == "passed"
    assert q4.passed_cases == 3
    assert q4.total_cases == 3
    assert q4.execution_time_ms == 15
    assert q4.selected_option is None

    q5 = q[env["q5"].id]
    assert q5.correct is False
    assert q5.earned_score == 2  # round(4 * 50 / 100)
    assert q5.percentage == 50
    assert q5.status == "failed"
    assert q5.passed_cases == 1
    assert q5.total_cases == 2

    q6 = q[env["q6"].id]
    assert q6.answered is False
    assert q6.correct is None
    assert q6.earned_score == 0
    assert q6.max_score == 1  # missing marks default to 1
    assert q6.percentage == 0
    assert q6.status is None
    assert q6.answered_at is None


def test_detail_and_list_agree(db):
    env = _canonical(db)
    owner = env["owner"]

    row = list_results(env["assessment"].id, owner, db)[0]
    detail = get_result(env["assessment"].id, env["assignment"].id, owner, db)

    for field in (
        "assignment_id", "assessment_id", "assessment_title", "candidate_id",
        "candidate_name", "candidate_email", "status", "assigned_at",
        "started_at", "submitted_at", "total_questions", "answered_questions",
        "total_score", "maximum_score", "percentage",
    ):
        assert getattr(detail, field) == getattr(row, field), field
    assert detail.sections == row.sections


def test_results_are_deterministic_across_calls(db):
    env = _canonical(db)
    owner = env["owner"]

    first = [r.model_dump_json() for r in list_results(env["assessment"].id, owner, db)]
    again = [r.model_dump_json() for r in list_results(env["assessment"].id, owner, db)]
    assert first == again

    d1 = get_result(env["assessment"].id, env["assignment"].id, owner, db).model_dump_json()
    d2 = get_result(env["assessment"].id, env["assignment"].id, owner, db).model_dump_json()
    assert d1 == d2


# ---------------------------------------------------------------------------
# Coding grading edge cases
# ---------------------------------------------------------------------------
def test_coding_compile_error_and_partial_scores(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.coding)
    good = _coding(db, section, 1, marks=10)
    partial = _coding(db, section, 2, marks=8)
    broken = _coding(db, section, 3, marks=5)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=_now(), submitted_at=_now(),
    )
    _coding_answer(db, assignment, good, status="passed", score=100)
    _coding_answer(db, assignment, partial, status="failed", score=25,
                   passed_cases=1, total_cases=4, results=[
                       {"case_index": 0, "passed": True, "status": "passed",
                        "time_ms": 7},
                       {"case_index": 1, "passed": False, "status": "wrong_answer",
                        "time_ms": 8},
                       {"case_index": 2, "passed": False, "status": "wrong_answer",
                        "time_ms": 8},
                       {"case_index": 3, "passed": False, "status": "wrong_answer",
                        "time_ms": 8},
                   ])
    _coding_answer(db, assignment, broken, status="error", score=0,
                   error_message="expected ';'")

    detail = get_result(assessment.id, assignment.id, owner, db)
    by_id = {q.question_id: q for q in detail.questions}

    assert by_id[good.id].earned_score == 10
    assert by_id[good.id].correct is True
    assert by_id[good.id].percentage == 100
    assert by_id[partial.id].earned_score == 2  # round(8 * 25 / 100)
    assert by_id[partial.id].correct is False
    assert by_id[partial.id].percentage == 25
    assert by_id[partial.id].status == "failed"
    assert by_id[broken.id].earned_score == 0
    assert by_id[broken.id].correct is False
    assert by_id[broken.id].status == "error"
    assert by_id[broken.id].percentage == 0

    assert detail.total_score == 12
    assert detail.maximum_score == 23
    assert detail.percentage == 52  # round(12 / 23 * 100)


def test_coding_score_can_never_exceed_marks(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.coding)
    question = _coding(db, section, 1, marks=10)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=_now(), submitted_at=_now(),
    )
    # Corruption: a stored score above 100 must still not earn more than marks.
    _coding_answer(db, assignment, question, status="passed", score=500)

    detail = get_result(assessment.id, assignment.id, owner, db)
    q = detail.questions[0]
    assert q.earned_score == 10
    assert q.max_score == 10
    assert q.percentage == 100


# ---------------------------------------------------------------------------
# Incomplete / expired / not-started
# ---------------------------------------------------------------------------
def test_in_progress_assessment_partial_scores(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    q1 = _mcq(db, section, 1, marks=2)
    q2 = _mcq(db, section, 2, marks=3)
    coding_section = _section(
        db, assessment, models.AssessmentSectionTypeEnum.coding, order=2
    )
    q3 = _coding(db, coding_section, 1, marks=5)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=_now(),
    )
    _mcq_answer(db, assignment, q1, 0)  # correct
    _coding_answer(db, assignment, q3, status="failed", score=40)  # 40% of 5 = 2

    rows = list_results(assessment.id, owner, db)
    row = rows[0]

    assert row.status == models.AssessmentAssignmentStatusEnum.in_progress
    assert row.started_at == assignment.started_at
    assert row.submitted_at is None
    assert row.answered_questions == 2
    assert row.total_questions == 3
    assert row.total_score == 4  # 2 + 2
    assert row.maximum_score == 10  # 2 + 3 + 5
    assert row.percentage == 40  # round(4 / 10 * 100)

    detail = get_result(assessment.id, assignment.id, owner, db)
    by_id = {q.question_id: q for q in detail.questions}
    assert by_id[q2.id].answered is False  # unanswered counted only as max
    assert by_id[q2.id].earned_score == 0


def test_expired_auto_submitted_assessment_keeps_deadline(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    # duration 10 minutes; started 2h ago -> deadline = started + 10 minutes.
    assessment = _assessment(db, company, duration_minutes=10)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    question = _mcq(db, section, 1, marks=4)
    started_at = _now() - timedelta(hours=2)
    deadline = started_at + timedelta(minutes=10)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=started_at,
        submitted_at=deadline,  # recorded by the deadline auto-submit
    )
    _mcq_answer(db, assignment, question, 0)

    rows = list_results(assessment.id, owner, db)
    row = rows[0]
    assert row.status == models.AssessmentAssignmentStatusEnum.submitted
    assert row.submitted_at == deadline
    assert row.started_at == started_at
    assert row.total_questions == 1
    assert row.answered_questions == 1
    assert row.total_score == 4
    assert row.percentage == 100


def test_assigned_not_started_zero_scores_but_full_paper(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    q1 = _mcq(db, section, 1, marks=2)
    _mcq(db, section, 2, marks=3)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.assigned,
    )

    row = list_results(assessment.id, owner, db)[0]
    assert row.status == models.AssessmentAssignmentStatusEnum.assigned
    assert row.answered_questions == 0
    assert row.total_score == 0
    assert row.maximum_score == 5
    assert row.percentage == 0
    assert row.total_questions == 2
    assert row.started_at is None and row.submitted_at is None

    detail = get_result(assessment.id, assignment.id, owner, db)
    assert len(detail.questions) == 2
    assert all(q.answered is False and q.correct is None for q in detail.questions)


# ---------------------------------------------------------------------------
# Zero-question / zero-mark edge cases
# ---------------------------------------------------------------------------
def test_zero_question_assessment_does_not_divide_by_zero(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    # Sections without any question bank entries are not part of the scored paper.
    _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    _section(db, assessment, models.AssessmentSectionTypeEnum.hr, order=2)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=_now(), submitted_at=_now(),
    )

    row = list_results(assessment.id, owner, db)[0]
    assert row.total_questions == 0
    assert row.answered_questions == 0
    assert row.maximum_score == 0
    assert row.total_score == 0
    assert row.percentage == 0
    assert row.sections == []

    detail = get_result(assessment.id, assignment.id, owner, db)
    assert detail.questions == []
    assert detail.percentage == 0


def test_zero_maximum_marks_does_not_divide_by_zero(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    q1 = _mcq(db, section, 1, marks=0)
    q2 = _mcq(db, section, 2, marks=0)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=_now(), submitted_at=_now(),
    )
    _mcq_answer(db, assignment, q1, 0)  # correct but worth 0
    _mcq_answer(db, assignment, q2, 1)  # wrong

    row = list_results(assessment.id, owner, db)[0]
    assert row.maximum_score == 0
    assert row.total_score == 0
    assert row.percentage == 0
    assert row.sections[0].maximum_score == 0
    assert row.sections[0].percentage == 0


def test_missing_marks_default_to_one(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    question = _mcq(db, section, 1, marks=None)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=_now(), submitted_at=_now(),
    )
    _mcq_answer(db, assignment, question, 0)

    row = list_results(assessment.id, owner, db)[0]
    assert row.maximum_score == 1
    assert row.total_score == 1
    assert row.percentage == 100


# ---------------------------------------------------------------------------
# Authorization / isolation / privacy
# ---------------------------------------------------------------------------
def test_other_company_receives_ownership_error(db):
    env = _canonical(db)
    other_owner = _company_user(db, 2)
    _company(db, other_owner, name="Competitor")

    with pytest.raises(HTTPException) as exc:
        list_results(env["assessment"].id, other_owner, db)
    assert exc.value.status_code == 403
    assert exc.value.detail == "You do not have permission to access this assessment"

    with pytest.raises(HTTPException) as exc:
        get_result(env["assessment"].id, env["assignment"].id, other_owner, db)
    assert exc.value.status_code == 403
    assert exc.value.detail == "You do not have permission to access this assessment"


def test_unknown_or_foreign_assignment_404(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _user(db, 10)
    other_candidate = _user(db, 11)
    assessment = _assessment(db, company, title="A")
    other_assessment = _assessment(db, company, title="B")
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    _mcq(db, section, 1)
    other_section = _section(
        db, other_assessment, models.AssessmentSectionTypeEnum.aptitude
    )
    _mcq(db, other_section, 1)
    assignment = _assignment(
        db, assessment, candidate,
        status=models.AssessmentAssignmentStatusEnum.submitted,
        started_at=_now(), submitted_at=_now(),
    )
    # An assignment of a DIFFERENT assessment of the same company.
    foreign = _assignment(
        db, other_assessment, other_candidate,
        status=models.AssessmentAssignmentStatusEnum.in_progress,
    )

    with pytest.raises(HTTPException) as exc:
        get_result(assessment.id, 999999, owner, db)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Assignment not found"

    with pytest.raises(HTTPException) as exc:
        get_result(assessment.id, foreign.id, owner, db)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Assignment not found"

    assert list_results(assessment.id, owner, db)[0].assignment_id == assignment.id


def test_admin_can_access_any_companys_results(db):
    env = _canonical(db)
    admin = _admin_user(db, 9)

    rows = list_results(env["assessment"].id, admin, db)
    assert len(rows) == 1
    assert rows[0].candidate_id == env["candidate"].id

    detail = get_result(env["assessment"].id, env["assignment"].id, admin, db)
    assert detail.assignment_id == env["assignment"].id
    assert len(detail.questions) == 6


def test_candidate_cannot_access_results_endpoints(db):
    candidate = _user(db, 10)

    with pytest.raises(HTTPException) as exc:
        company_scoped(current_user=candidate)
    assert exc.value.status_code == 403
    assert exc.value.detail == "You do not have permission to access this resource"


def test_hidden_coding_privacy_in_detail(db):
    env = _canonical(db)
    owner = env["owner"]
    # Simulate a grading result that happens to carry private I/O — none of it
    # may ever reach the results payload. Q1 keeps its answer key on the row.
    env["a4"].results = [
        {
            "case_index": 0,
            "passed": True,
            "status": "passed",
            "time_ms": 7,
            "stdout": "SECRET_OUTPUT",
            "expected": "1",
            "input": "2",
        }
    ]
    env["q1"].correct_index = 0  # answer key exists on the question row

    detail = get_result(env["assessment"].id, env["assignment"].id, owner, db)

    for question in detail.questions:
        dump = question.model_dump()
        for private in (
            "results", "hidden_cases", "correct_index", "code",
            "stdout", "stderr", "expected", "input",
        ):
            assert private not in dump, private
    # The company result schema itself exposes none of these keys.
    base_fields = schemas.AssessmentResultDetailOut.model_fields
    for private in ("hidden_cases", "correct_index", "results"):
        assert private not in base_fields


def test_hidden_coding_privacy_in_list(db):
    env = _canonical(db)
    owner = env["owner"]
    env["a4"].results = [
        {"case_index": 0, "passed": True, "status": "passed", "time_ms": 7,
         "input": "x", "expected": "y"}
    ]

    payload = list_results(env["assessment"].id, owner, db)[0].model_dump_json()

    for private in ("hidden_cases", "correct_index", "results", "code",
                    "stdout", "stderr", "expected"):
        assert private not in payload, private


def test_candidate_identity_fields_available_to_owner(db):
    env = _canonical(db)
    owner = env["owner"]

    row = list_results(env["assessment"].id, owner, db)[0]
    assert row.candidate_name == "Grace Hopper"
    assert row.candidate_email == "grace@acme.com"
    assert row.candidate_id == env["candidate"].id
    assert row.assessment_title == "Backend Screening"
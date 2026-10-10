"""Assessment deletion-integrity policy tests (Task 24).

Deleting an ``Assessment`` cascades through the ORM relationships:

    Assessment --(delete-orphan)--> AssessmentSection --> AssessmentQuestion --> AssessmentAnswer
    Assessment --(delete-orphan)--> AssessmentAssignment --> AssessmentAnswer

so a delete can silently destroy an in-flight attempt or already-recorded
answers/results. These tests pin down the deletion policy and prove the fix:

  * unused assessment (no assignments)                 : deletable (unchanged)
  * assigned-but-not-started candidates only           : deletable (unchanged —
    mirrors ``remove_assignment``, which already permits removing a
    not-started assignment; no answers exist, so nothing is lost)
  * any in_progress OR submitted attempt               : rejected with 409

The route locks the assessment's assignment rows ``FOR UPDATE`` (a no-op on
SQLite, whose writes are serialized) before checking, so a concurrent
start/submit cannot slip between the check and the cascade delete: whichever
transaction commits first wins, and the loser observes the committed state
(submit-after-delete finds the row gone → 404; delete-after-submit sees
``submitted`` → 409). The concurrency tests below exercise both orderings at
the route level.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.routes.candidate_assessment_start import start_my_assessment
from app.routes.company_assessment_results import get_result
from app.routes.company_assessments import delete_assessment


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


def _company(db, user, name="Acme Recruiting", approved=True):
    c = models.Company(user_id=user.id, name=name, approved=approved)
    db.add(c)
    db.flush()
    return c


def _assessment(db, company, title="Backend Screening", **kw):
    kw.setdefault("status", models.CompanyAssessmentStatusEnum.published)
    kw.setdefault("duration_minutes", 90)
    kw.setdefault("starts_at", datetime(2020, 1, 1))
    kw.setdefault("ends_at", datetime(2030, 1, 1))
    a = models.Assessment(company_id=company.id, title=title, **kw)
    db.add(a)
    db.flush()
    return a


def _section(db, assessment, order=1, section_type=models.AssessmentSectionTypeEnum.aptitude, title="Aptitude"):
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


def _question(db, section, order=1, marks=1):
    q = models.AssessmentQuestion(
        section_id=section.id,
        question_type=models.AssessmentQuestionTypeEnum.mcq,
        question_text="Which option?",
        question_order=order,
        options=["a", "b"],
        correct_index=0,
        marks=marks,
    )
    db.add(q)
    db.flush()
    return q


def _assignment(db, assessment, candidate, status, **kw):
    a = models.AssessmentAssignment(
        assessment_id=assessment.id,
        candidate_id=candidate.id,
        status=status,
        **kw,
    )
    db.add(a)
    db.flush()
    return a


def _answer(db, assignment, question, selected=0, correct=True):
    a = models.AssessmentAnswer(
        assignment_id=assignment.id,
        question_id=question.id,
        selected_option=selected,
        is_correct=correct,
    )
    db.add(a)
    db.flush()
    return a


def _expect_409(fn, *args):
    with pytest.raises(Exception) as exc:
        fn(*args)
    assert exc.value.status_code == 409
    return exc


def _expect_404(fn, *args):
    with pytest.raises(Exception) as exc:
        fn(*args)
    assert exc.value.status_code == 404
    return exc


# ---------------------------------------------------------------------------
# Deletion stays allowed for assessments nothing depends on
# ---------------------------------------------------------------------------

def test_unused_assessment_deletion_allowed(db):
    """An assessment with no assignments (draft or published) is deletable."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company, status=models.CompanyAssessmentStatusEnum.draft)
    s = _section(db, a)
    _question(db, s)

    delete_assessment(a.id, owner, db)

    assert db.get(models.Assessment, a.id) is None
    assert db.get(models.AssessmentSection, s.id) is None


def test_assigned_but_not_started_deletion_allowed(db):
    """Assigned-but-not-started candidates do not block deletion.

    Nobody has started, so there are no answers/results to lose. This mirrors
    ``remove_assignment``, which already lets a company remove a not-started
    assignment — deleting the whole assessment is the same operation at scale.
    """
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    _question(db, s)
    cand = _candidate_user(db, 10)
    assignment = _assignment(
        db, a, cand, models.AssessmentAssignmentStatusEnum.assigned
    )

    delete_assessment(a.id, owner, db)

    assert db.get(models.Assessment, a.id) is None
    assert db.get(models.AssessmentAssignment, assignment.id) is None


# ---------------------------------------------------------------------------
# Deletion blocked once an attempt is in progress or submitted
# ---------------------------------------------------------------------------

def test_delete_rejected_with_in_progress_attempt(db):
    """An active attempt blocks deletion; the whole paper stays intact."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    q = _question(db, s)
    cand = _candidate_user(db, 10)
    assignment = _assignment(
        db, a, cand, models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=datetime.utcnow() - timedelta(minutes=5),
    )

    _expect_409(delete_assessment, a.id, owner, db)

    # Nothing was cascade-deleted.
    assert db.get(models.Assessment, a.id) is not None
    assert db.get(models.AssessmentSection, s.id) is not None
    assert db.get(models.AssessmentQuestion, q.id) is not None
    assert db.get(models.AssessmentAssignment, assignment.id) is not None


def test_delete_rejected_with_submitted_results(db):
    """A submitted attempt blocks deletion; answers and results survive."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    q = _question(db, s, marks=2)
    cand = _candidate_user(db, 10)
    started = datetime.utcnow() - timedelta(minutes=30)
    assignment = _assignment(
        db, a, cand, models.AssessmentAssignmentStatusEnum.submitted,
        started_at=started, submitted_at=started + timedelta(minutes=10),
    )
    _answer(db, assignment, q, selected=0, correct=True)

    before = get_result(a.id, assignment.id, owner, db)
    assert before.maximum_score == 2
    assert before.total_score == 2

    _expect_409(delete_assessment, a.id, owner, db)

    # Assessment and the historical answer both remain.
    assert db.get(models.Assessment, a.id) is not None
    assert (
        db.query(models.AssessmentAnswer)
        .filter(models.AssessmentAnswer.assignment_id == assignment.id)
        .count()
        == 1
    )
    after = get_result(a.id, assignment.id, owner, db)
    assert after.maximum_score == before.maximum_score == 2
    assert after.total_score == before.total_score == 2


def test_rejected_deletion_preserves_answers_and_results_with_mixed_attempts(db):
    """One submitted attempt is enough to protect the whole assessment, even
    when other candidates have only been assigned."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    q = _question(db, s)
    started = datetime.utcnow() - timedelta(minutes=30)

    done_cand = _candidate_user(db, 10)
    done = _assignment(
        db, a, done_cand, models.AssessmentAssignmentStatusEnum.submitted,
        started_at=started, submitted_at=started + timedelta(minutes=10),
    )
    _answer(db, done, q, selected=0, correct=True)

    pending_cand = _candidate_user(db, 11)
    _assignment(db, a, pending_cand, models.AssessmentAssignmentStatusEnum.assigned)

    _expect_409(delete_assessment, a.id, owner, db)

    assert db.get(models.Assessment, a.id) is not None
    assert (
        db.query(models.AssessmentAnswer)
        .filter(models.AssessmentAnswer.assignment_id == done.id)
        .count()
        == 1
    )


# ---------------------------------------------------------------------------
# Concurrency ordering (both directions) at the route level
# ---------------------------------------------------------------------------

def test_delete_wins_over_concurrent_start_no_partial_state(db):
    """Delete-first ordering: once the assessment is gone, a candidate start
    cannot recreate an attempt against it (404) and leaves no orphan rows."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    _question(db, s)
    cand = _candidate_user(db, 10)
    _assignment(db, a, cand, models.AssessmentAssignmentStatusEnum.assigned)

    delete_assessment(a.id, owner, db)

    _expect_404(start_my_assessment, a.id, cand, db)
    assert (
        db.query(models.AssessmentAssignment)
        .filter(models.AssessmentAssignment.assessment_id == a.id)
        .count()
        == 0
    )
    assert db.query(models.AssessmentAnswer).count() == 0


def test_submit_wins_over_delete(db):
    """Submit-first ordering: once an attempt is submitted, a delete is
    rejected so the recorded result can never be lost."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    q = _question(db, s)
    cand = _candidate_user(db, 10)
    assignment = _assignment(
        db, a, cand, models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=datetime.utcnow() - timedelta(minutes=1),
    )
    _answer(db, assignment, q, selected=0, correct=True)

    # The submission wins the race and commits.
    assignment.status = models.AssessmentAssignmentStatusEnum.submitted
    assignment.submitted_at = datetime.utcnow()
    db.commit()

    _expect_409(delete_assessment, a.id, owner, db)

    assert db.get(models.Assessment, a.id) is not None
    assert get_result(a.id, assignment.id, owner, db).total_score == 1

"""Assessment edit-integrity policy tests (Task 23).

Confirms that once any candidate has *started* or *submitted* an assessment,
the company can no longer mutate the content (sections / questions) that the
attempt was built from or that results are derived from, and that the
duration / availability window is frozen while an attempt is in progress.

Policy under test (documented here and mirrored by the route guards):

  * draft / unpublished / published-without-assignments        : fully editable
  * assigned-but-not-started candidates                        : fully editable
    (nobody has taken the exam yet, so nothing depends on the current content)
  * any in_progress OR submitted attempt                       : paper frozen
    (sections + questions: add / update / reorder / delete → 409)
  * any in_progress attempt                                    : window frozen
    (duration_minutes / starts_at / ends_at → 409; title etc. still allowed)

No migrations: the guard is purely request-time and scoped to the owning
company / admin (reusing the existing ownership guards).
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.routes.company_assessment_questions import (
    add_question,
    delete_question,
    reorder_questions,
    update_question,
)
from app.routes.company_assessment_results import get_result
from app.routes.company_assessments import (
    add_section,
    remove_section,
    reorder_sections,
    update_assessment,
    update_section,
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


# ---------------------------------------------------------------------------
# States where editing stays allowed
# ---------------------------------------------------------------------------

def test_draft_assessment_remains_fully_editable(db):
    """A draft (never published / assigned) can change content and window."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company, status=models.CompanyAssessmentStatusEnum.draft)
    s = _section(db, a)
    q = _question(db, s)

    # Content edits.
    update_question(
        a.id, s.id, q.id,
        schemas.AssessmentQuestionUpdate(marks=5, question_text="Edited"), owner, db,
    )
    assert db.get(models.AssessmentQuestion, q.id).marks == 5
    q2 = add_question(
        a.id,
        s.id,
        schemas.AssessmentQuestionCreate(
            question_type=models.AssessmentQuestionTypeEnum.mcq,
            question_text="More?",
            options=["x", "y"],
            correct_index=1,
        ),
        owner,
        db,
    )
    assert q2.id is not None
    update_section(
        a.id, s.id, schemas.AssessmentSectionUpdate(title="Renamed"), owner, db
    )
    remove_section(a.id, s.id, owner, db)
    assert db.get(models.AssessmentSection, s.id) is None

    # Window/duration edits.
    result = update_assessment(
        a.id,
        schemas.AssessmentUpdate(duration_minutes=45, ends_at=datetime(2040, 1, 1)),
        owner,
        db,
    )
    assert result.duration_minutes == 45


def test_published_without_assignments_remains_editable(db):
    """Publishing alone does not freeze the paper — edits before assignment."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    q = _question(db, s)

    update_question(
        a.id, s.id, q.id, schemas.AssessmentQuestionUpdate(marks=3), owner, db
    )
    assert db.get(models.AssessmentQuestion, q.id).marks == 3
    update_section(
        a.id, s.id, schemas.AssessmentSectionUpdate(marks=7), owner, db
    )
    update_assessment(
        a.id, schemas.AssessmentUpdate(duration_minutes=60), owner, db
    )
    assert db.get(models.Assessment, a.id).duration_minutes == 60


def test_assigned_but_not_started_remains_editable(db):
    """Assignment alone (nobody started) does not freeze content or window.

    Candidates have not fetched any question content yet, so the paper can
    still be corrected before the first start.
    """
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    q = _question(db, s)
    cand = _candidate_user(db, 10)
    _assignment(db, a, cand, models.AssessmentAssignmentStatusEnum.assigned)

    update_question(
        a.id, s.id, q.id, schemas.AssessmentQuestionUpdate(question_text="Fixed"), owner, db
    )
    assert db.get(models.AssessmentQuestion, q.id).question_text == "Fixed"
    update_section(
        a.id, s.id, schemas.AssessmentSectionUpdate(title="Renamed"), owner, db
    )
    reorder_sections(a.id, schemas.AssessmentSectionReorderIn(ordered_section_ids=[s.id]), owner, db)
    update_assessment(
        a.id, schemas.AssessmentUpdate(duration_minutes=120), owner, db
    )
    assert db.get(models.Assessment, a.id).duration_minutes == 120


# ---------------------------------------------------------------------------
# In-progress attempts: paper and window are frozen (issues 1, 3)
# ---------------------------------------------------------------------------

def test_in_progress_question_and_section_edits_rejected(db):
    """Editing questions/sections after a candidate started is blocked."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    q = _question(db, s)
    s2 = _section(db, a, order=2, section_type=models.AssessmentSectionTypeEnum.technical, title="Tech")
    q2 = _question(db, s2, order=1)
    cand = _candidate_user(db, 10)
    _assignment(
        db, a, cand, models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=datetime.utcnow() - timedelta(minutes=5),
    )

    # Question edits: text (exam content) and marks (scoring) are both frozen.
    _expect_409(
        update_question, a.id, s.id, q.id,
        schemas.AssessmentQuestionUpdate(question_text="Tampered"), owner, db,
    )
    _expect_409(
        update_question, a.id, s.id, q.id,
        schemas.AssessmentQuestionUpdate(marks=99), owner, db,
    )
    _expect_409(
        update_question, a.id, s.id, q.id,
        schemas.AssessmentQuestionUpdate(correct_index=1), owner, db,
    )
    # Section edits.
    _expect_409(
        update_section, a.id, s.id,
        schemas.AssessmentSectionUpdate(title="Tampered"), owner, db,
    )
    # Structural additions / removals / reordering.
    _expect_409(
        add_question,
        a.id,
        s.id,
        schemas.AssessmentQuestionCreate(
            question_type=models.AssessmentQuestionTypeEnum.mcq,
            question_text="Extra?",
            options=["a", "b"],
            correct_index=0,
        ),
        owner,
        db,
    )
    _expect_409(add_section, a.id, schemas.AssessmentSectionCreate(
        section_type=models.AssessmentSectionTypeEnum.hr, title="HR", section_order=3,
    ), owner, db)
    _expect_409(reorder_sections, a.id, schemas.AssessmentSectionReorderIn(
        ordered_section_ids=[s2.id, s.id],
    ), owner, db)
    _expect_409(reorder_questions, a.id, s2.id, schemas.AssessmentQuestionReorderIn(
        ordered_question_ids=[q2.id],
    ), owner, db)
    _expect_409(delete_question, a.id, s.id, q.id, owner, db)
    _expect_409(remove_section, a.id, s2.id, owner, db)

    # Nothing changed.
    assert db.get(models.AssessmentQuestion, q.id).marks == 1
    assert db.get(models.AssessmentQuestion, q.id).question_text == "Which option?"
    assert db.get(models.AssessmentSection, s2.id) is not None
    assert db.get(models.AssessmentQuestion, q2.id) is not None


def test_in_progress_duration_and_window_edits_rejected(db):
    """Changing duration / window while an attempt runs is blocked (deadline
    is derived from them live and would shift mid-attempt)."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    _question(db, s)
    cand = _candidate_user(db, 10)
    _assignment(
        db, a, cand, models.AssessmentAssignmentStatusEnum.in_progress,
        started_at=datetime.utcnow(),
    )

    _expect_409(
        update_assessment, a.id, schemas.AssessmentUpdate(duration_minutes=10), owner, db
    )
    _expect_409(
        update_assessment, a.id, schemas.AssessmentUpdate(ends_at=datetime.utcnow()), owner, db
    )
    _expect_409(
        update_assessment, a.id, schemas.AssessmentUpdate(starts_at=datetime(2019, 1, 1)), owner, db
    )
    assert db.get(models.Assessment, a.id).duration_minutes == 90

    # Non-window fields stay editable mid-attempt.
    result = update_assessment(
        a.id, schemas.AssessmentUpdate(title="Renamed mid-attempt"), owner, db
    )
    assert result.title == "Renamed mid-attempt"


# ---------------------------------------------------------------------------
# Submitted attempts: paper frozen (results depend on it) — issues 2, 4
# ---------------------------------------------------------------------------

def test_submitted_marks_edit_cannot_change_results(db):
    """Editing marks after submission is blocked so stored results cannot be
    silently rewritten."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    q = _question(db, s, marks=1)
    cand = _candidate_user(db, 10)
    started = datetime.utcnow() - timedelta(minutes=30)
    assignment = _assignment(
        db, a, cand, models.AssessmentAssignmentStatusEnum.submitted,
        started_at=started, submitted_at=started + timedelta(minutes=10),
    )
    _answer(db, assignment, q, selected=0, correct=True)

    before = get_result(a.id, assignment.id, owner, db)
    assert before.total_score == 1
    assert before.maximum_score == 1

    _expect_409(
        update_question, a.id, s.id, q.id,
        schemas.AssessmentQuestionUpdate(marks=5), owner, db,
    )
    _expect_409(
        update_question, a.id, s.id, q.id,
        schemas.AssessmentQuestionUpdate(correct_index=1), owner, db,
    )
    _expect_409(
        update_question, a.id, s.id, q.id,
        schemas.AssessmentQuestionUpdate(question_text="Rewritten"), owner, db,
    )

    after = get_result(a.id, assignment.id, owner, db)
    assert after.total_score == before.total_score == 1
    assert after.maximum_score == before.maximum_score == 1


def test_submitted_section_and_question_deletion_rejected(db):
    """Deleting sections/questions with answers is blocked so historical
    answers (and therefore results) are never cascade-deleted (issue 4)."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    q = _question(db, s)
    cand = _candidate_user(db, 10)
    started = datetime.utcnow() - timedelta(minutes=30)
    assignment = _assignment(
        db, a, cand, models.AssessmentAssignmentStatusEnum.submitted,
        started_at=started, submitted_at=started + timedelta(minutes=10),
    )
    _answer(db, assignment, q, selected=0, correct=True)

    _expect_409(delete_question, a.id, s.id, q.id, owner, db)
    _expect_409(remove_section, a.id, s.id, owner, db)

    # Answers and their result are still intact.
    assert db.query(models.AssessmentAnswer).filter(
        models.AssessmentAnswer.assignment_id == assignment.id
    ).count() == 1
    result = get_result(a.id, assignment.id, owner, db)
    assert result.maximum_score == 1
    assert result.total_score == 1


def test_submitted_only_window_and_duration_edits_allowed(db):
    """Once every attempt is submitted, the paper stays frozen but the window
    / duration can still be adjusted (they no longer affect any deadline or
    result)."""
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a = _assessment(db, company)
    s = _section(db, a)
    q = _question(db, s)
    cand = _candidate_user(db, 10)
    started = datetime.utcnow() - timedelta(minutes=30)
    assignment = _assignment(
        db, a, cand, models.AssessmentAssignmentStatusEnum.submitted,
        started_at=started, submitted_at=started + timedelta(minutes=10),
    )
    _answer(db, assignment, q, selected=0, correct=True)

    result = update_assessment(
        a.id, schemas.AssessmentUpdate(duration_minutes=45), owner, db
    )
    assert result.duration_minutes == 45

    # Paper edits remain frozen despite the window being editable.
    _expect_409(
        update_question, a.id, s.id, q.id,
        schemas.AssessmentQuestionUpdate(marks=2), owner, db,
    )
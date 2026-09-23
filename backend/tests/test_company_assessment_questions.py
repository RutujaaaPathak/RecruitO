"""Company Assessment Question Bank API tests.

Exercises the company-only question-management endpoints (/assessments/{id}
/sections/{sid}/questions) directly (payload, user, session) against an
in-memory SQLite engine with ``foreign_keys=ON`` over just the pipeline tables.
Covers create/list/get/update/delete/reorder, MCQ and coding contract
validation, section/assessment ownership, question-type vs section-type
validation, duplicate/invalid ordering, atomic reorder, company isolation,
admin access, candidate RBAC, and correct-answer privacy (candidate-facing
contracts never carry correct answers / hidden cases). No network, no external DB.
"""
from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.auth import RoleChecker
from app.routes.company_assessment_questions import (
    add_question,
    company_scoped,
    delete_question,
    get_question,
    list_questions,
    reorder_questions,
    update_question,
)
from app.routes.candidate_assessments import get_my_assessment, list_my_assessments
from app.routes.company_assessments import (
    add_section,
    create_assessment,
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


def _candidate_user(db, id):
    return _user(db, id, role=models.RoleEnum.user, name="Candidate")


def _company(db, user, name="Acme Recruiting", approved=True):
    c = models.Company(user_id=user.id, name=name, approved=approved)
    db.add(c)
    db.flush()
    return c


def _assessment(db, company, title="Backend Screening", owner=None):
    a = models.Assessment(company_id=company.id, title=title)
    db.add(a)
    db.flush()
    return a


def _section(db, assessment, section_type, order=1, title=None):
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


def _mcq_payload(**kw):
    data = dict(
        question_type=models.AssessmentQuestionTypeEnum.mcq,
        question_text="Which sorting algorithm is stable?",
        options=["Merge sort", "Quick sort", "Heap sort", "Selection sort"],
        correct_index=0,
        marks=5,
    )
    data.update(kw)
    return schemas.AssessmentQuestionCreate(**data)


def _coding_payload(**kw):
    data = dict(
        question_type=models.AssessmentQuestionTypeEnum.coding,
        question_text="Return the indices of two numbers that sum to target.",
        title="Two Sum",
        category="arrays",
        difficulty="easy",
        input_format="Line 1: N, line 2: N ints, line 3: target",
        output_format="Two space-separated indices",
        constraints="2 <= N <= 1000",
        sample_cases=[
            {"input": "4\n2 7 11 15\n9", "expected": "0 1"},
        ],
        hidden_cases=[
            {"input": "2\n3 3\n6", "expected": "0 1"},
        ],
    )
    data.update(kw)
    return schemas.AssessmentQuestionCreate(**data)


# ---------------------------------------------------------------------------
# Create — MCQ
# ---------------------------------------------------------------------------
def test_add_question_appends_order_and_returns_full_contract(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(
        db, assessment, models.AssessmentSectionTypeEnum.aptitude
    )

    out = add_question(assessment.id, section.id, _mcq_payload(), owner, db)

    assert out.id is not None
    assert out.section_id == section.id
    assert out.question_type == models.AssessmentQuestionTypeEnum.mcq
    assert out.question_order == 1
    assert out.question_text.startswith("Which sorting")
    assert out.options == ["Merge sort", "Quick sort", "Heap sort", "Selection sort"]
    assert out.correct_index == 0
    assert out.marks == 5
    assert out.created_at is not None


def test_add_question_appends_after_existing_orders(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.technical)
    add_question(assessment.id, section.id, _mcq_payload(), owner, db)
    add_question(
        assessment.id, section.id, _mcq_payload(question_text="Second"), owner, db
    )
    add_question(
        assessment.id,
        section.id,
        _mcq_payload(question_text="Third", question_order=5),
        owner,
        db,
    )

    listed = list_questions(assessment.id, section.id, owner, db)
    assert [q.question_text for q in listed] == [
        "Which sorting algorithm is stable?",
        "Second",
        "Third",
    ]
    assert [q.question_order for q in listed] == [1, 2, 5]


def test_add_mcq_validates_options_and_correct_index(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)

    with pytest.raises(ValidationError):
        _mcq_payload(options=None, correct_index=0)
    with pytest.raises(ValidationError):
        _mcq_payload(options=["Only one"], correct_index=0)
    with pytest.raises(ValidationError):
        _mcq_payload(options=["A", "B", "C", "D"], correct_index=None)
    with pytest.raises(ValidationError):
        _mcq_payload(options=["A", "B", "C", "D"], correct_index=4)
    with pytest.raises(ValidationError):
        _mcq_payload(options=["A", "B", "", "D"], correct_index=1)

    add_question(assessment.id, section.id, _mcq_payload(), owner, db)
    assert len(list_questions(assessment.id, section.id, owner, db)) == 1


def test_add_rejects_nonpositive_order(db):
    with pytest.raises(ValidationError):
        _mcq_payload(question_order=0)
    with pytest.raises(ValidationError):
        _mcq_payload(question_order=-1)


def test_add_mcq_duplicate_order_409(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    add_question(
        assessment.id,
        section.id,
        _mcq_payload(question_order=2),
        owner,
        db,
    )

    with pytest.raises(Exception) as exc:
        add_question(
            assessment.id,
            section.id,
            _mcq_payload(question_text="Other", question_order=2),
            owner,
            db,
        )
    assert exc.value.status_code == 409
    assert len(list_questions(assessment.id, section.id, owner, db)) == 1


# ---------------------------------------------------------------------------
# Create — Coding
# ---------------------------------------------------------------------------
def test_add_coding_question_defaults_and_contract(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.coding)

    out = add_question(assessment.id, section.id, _coding_payload(), owner, db)

    assert out.question_type == models.AssessmentQuestionTypeEnum.coding
    assert out.title == "Two Sum"
    assert out.category == "arrays"
    assert out.difficulty == "easy"
    assert out.hidden_cases == [{"input": "2\n3 3\n6", "expected": "0 1"}]
    assert out.sample_cases == [{"input": "4\n2 7 11 15\n9", "expected": "0 1"}]
    # Defaults mirror the existing coding engine.
    assert out.time_limit_seconds == 5
    assert out.supported_languages == ["python", "java", "cpp"]
    assert out.correct_index is None
    assert out.options is None


def test_add_coding_validates_test_cases(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.coding)

    with pytest.raises(ValidationError):
        _coding_payload(hidden_cases=None)
    with pytest.raises(ValidationError):
        _coding_payload(hidden_cases=[])
    with pytest.raises(ValidationError):
        _coding_payload(hidden_cases=[{"input": "1"}])
    with pytest.raises(ValidationError):
        _coding_payload(hidden_cases=[{"input": "1", "expected": "1", "extra": "x"}])
    with pytest.raises(ValidationError):
        _coding_payload(hidden_cases=[{"input": 1, "expected": "1"}])
    with pytest.raises(ValidationError):
        _coding_payload(
            hidden_cases=[{"input": "1", "expected": "1"}],
            sample_cases=[{"input": "1"}],
        )

    add_question(assessment.id, section.id, _coding_payload(), owner, db)
    assert len(list_questions(assessment.id, section.id, owner, db)) == 1


def test_add_coding_rejects_unsupported_languages(db):
    with pytest.raises(ValidationError):
        _coding_payload(supported_languages=["python", "rust"])
    with pytest.raises(ValidationError):
        _coding_payload(supported_languages=[])
    with pytest.raises(ValidationError):
        _coding_payload(time_limit_seconds=0)


# ---------------------------------------------------------------------------
# Question type vs section type
# ---------------------------------------------------------------------------
def test_rejects_question_type_mismatch_with_section(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    mcq_section = _section(
        db, assessment, models.AssessmentSectionTypeEnum.aptitude
    )
    coding_section = _section(
        db, assessment, models.AssessmentSectionTypeEnum.coding, order=2
    )

    # Coding question into an aptitude section...
    with pytest.raises(Exception) as exc:
        add_question(assessment.id, mcq_section.id, _coding_payload(), owner, db)
    assert exc.value.status_code == 400
    # ...and an MCQ question into a coding section.
    with pytest.raises(Exception) as exc:
        add_question(assessment.id, coding_section.id, _mcq_payload(), owner, db)
    assert exc.value.status_code == 400

    assert len(list_questions(assessment.id, mcq_section.id, owner, db)) == 0
    assert len(list_questions(assessment.id, coding_section.id, owner, db)) == 0


def test_rejects_unsupported_section_types(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    hr = _section(db, assessment, models.AssessmentSectionTypeEnum.hr, order=1)
    interview = _section(
        db, assessment, models.AssessmentSectionTypeEnum.technical_interview, order=2
    )

    for section in (hr, interview):
        with pytest.raises(Exception) as exc:
            add_question(assessment.id, section.id, _mcq_payload(), owner, db)
        assert exc.value.status_code == 400
        with pytest.raises(Exception) as exc:
            add_question(assessment.id, section.id, _coding_payload(), owner, db)
        assert exc.value.status_code == 400

    assert owner is not None  # (owner used — no question rows created)


# ---------------------------------------------------------------------------
# List / Get / Update / Delete
# ---------------------------------------------------------------------------
def test_list_questions_ordered(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.technical)
    q1 = add_question(assessment.id, section.id, _mcq_payload(), owner, db)
    q2 = add_question(
        assessment.id,
        section.id,
        _mcq_payload(question_text="Second", question_order=3),
        owner,
        db,
    )

    listed = list_questions(assessment.id, section.id, owner, db)
    assert [q.id for q in listed] == [q1.id, q2.id]
    assert [q.question_order for q in listed] == [1, 3]


def test_get_question_and_404s(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.coding)
    question = add_question(assessment.id, section.id, _coding_payload(), owner, db)

    out = get_question(assessment.id, section.id, question.id, owner, db)
    assert out.id == question.id
    assert out.question_text == question.question_text

    with pytest.raises(Exception) as exc:
        get_question(assessment.id, section.id, 9999, owner, db)
    assert exc.value.status_code == 404


def test_update_question_partial(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    question = add_question(assessment.id, section.id, _mcq_payload(), owner, db)

    out = update_question(
        assessment.id,
        section.id,
        question.id,
        schemas.AssessmentQuestionUpdate(
            question_text="Which is the fastest comparison sort?",
            correct_index=2,
            marks=10,
        ),
        owner,
        db,
    )
    assert out.question_text == "Which is the fastest comparison sort?"
    assert out.correct_index == 2
    assert out.marks == 10
    assert out.options == question.options


def test_update_question_revalidates_contract(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    question = add_question(assessment.id, section.id, _mcq_payload(), owner, db)

    # Degrading below two options must be rejected by the final-state guard.
    with pytest.raises(Exception) as exc:
        update_question(
            assessment.id,
            section.id,
            question.id,
            schemas.AssessmentQuestionUpdate(options=["Only one"], correct_index=0),
            owner,
            db,
        )
    assert exc.value.status_code == 400

    # Moving the correct index out of range likewise.
    with pytest.raises(Exception) as exc:
        update_question(
            assessment.id,
            section.id,
            question.id,
            schemas.AssessmentQuestionUpdate(correct_index=9),
            owner,
            db,
        )
    assert exc.value.status_code == 400


def test_update_question_rejects_wrong_type_and_duplicate_order(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    aptitude = _section(
        db, assessment, models.AssessmentSectionTypeEnum.aptitude, order=1
    )
    coding = _section(
        db, assessment, models.AssessmentSectionTypeEnum.coding, order=2
    )
    question = add_question(assessment.id, aptitude.id, _mcq_payload(), owner, db)
    other = add_question(
        assessment.id,
        aptitude.id,
        _mcq_payload(question_text="Second", question_order=2),
        owner,
        db,
    )

    # Retargeting the type to the section's unsupported type is rejected.
    with pytest.raises(Exception) as exc:
        update_question(
            assessment.id,
            aptitude.id,
            question.id,
            schemas.AssessmentQuestionUpdate(
                question_type=models.AssessmentQuestionTypeEnum.coding
            ),
            owner,
            db,
        )
    assert exc.value.status_code == 400

    # Colliding with an existing question order is rejected.
    with pytest.raises(Exception) as exc:
        update_question(
            assessment.id,
            aptitude.id,
            question.id,
            schemas.AssessmentQuestionUpdate(question_order=other.question_order),
            owner,
            db,
        )
    assert exc.value.status_code == 409


def test_delete_question(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    q1 = add_question(assessment.id, section.id, _mcq_payload(), owner, db)
    q2 = add_question(
        assessment.id,
        section.id,
        _mcq_payload(question_text="Second", question_order=2),
        owner,
        db,
    )

    result = delete_question(assessment.id, section.id, q1.id, owner, db)
    assert result is None
    remaining = list_questions(assessment.id, section.id, owner, db)
    assert [q.id for q in remaining] == [q2.id]

    with pytest.raises(Exception) as exc:
        get_question(assessment.id, section.id, q1.id, owner, db)
    assert exc.value.status_code == 404
    with pytest.raises(Exception) as exc:
        delete_question(assessment.id, section.id, q1.id, owner, db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Reorder (atomic)
# ---------------------------------------------------------------------------
def test_reorder_questions_applies_new_order(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.coding)
    q1 = add_question(
        assessment.id, section.id, _coding_payload(question_text="One"), owner, db
    )
    q2 = add_question(
        assessment.id, section.id, _coding_payload(question_text="Two"), owner, db
    )
    q3 = add_question(
        assessment.id, section.id, _coding_payload(question_text="Three"), owner, db
    )

    ordered = reorder_questions(
        assessment.id,
        section.id,
        schemas.AssessmentQuestionReorderIn(
            ordered_question_ids=[q3.id, q1.id, q2.id]
        ),
        owner,
        db,
    )
    assert [q.id for q in ordered] == [q3.id, q1.id, q2.id]
    assert [q.question_order for q in ordered] == [1, 2, 3]

    listed = list_questions(assessment.id, section.id, owner, db)
    assert [q.id for q in listed] == [q3.id, q1.id, q2.id]


def test_reorder_rejects_duplicate_ids(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.coding)
    q1 = add_question(assessment.id, section.id, _coding_payload(), owner, db)

    with pytest.raises(ValidationError):
        schemas.AssessmentQuestionReorderIn(ordered_question_ids=[q1.id, q1.id])


def test_reorder_rejects_missing_or_foreign_ids(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.coding)
    other_section = _section(
        db, assessment, models.AssessmentSectionTypeEnum.coding, order=2
    )
    q1 = add_question(assessment.id, section.id, _coding_payload(), owner, db)
    q2 = add_question(
        assessment.id,
        section.id,
        _coding_payload(question_text="Second question"),
        owner,
        db,
    )
    q3 = add_question(
        assessment.id,
        other_section.id,
        _coding_payload(question_text="Other section"),
        owner,
        db,
    )

    # Omitting one of the section's own ids is a 409.
    with pytest.raises(Exception) as exc:
        reorder_questions(
            assessment.id,
            section.id,
            schemas.AssessmentQuestionReorderIn(ordered_question_ids=[q1.id]),
            owner,
            db,
        )
    assert exc.value.status_code == 409

    # A question from a different section is also "foreign".
    with pytest.raises(Exception) as exc:
        reorder_questions(
            assessment.id,
            section.id,
            schemas.AssessmentQuestionReorderIn(
                ordered_question_ids=[q1.id, q2.id, q3.id]
            ),
            owner,
            db,
        )
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Ownership / isolation
# ---------------------------------------------------------------------------
def test_another_company_cannot_manage_questions(db):
    owner_a = _company_user(db, 1)
    company_a = _company(db, owner_a, name="Acme")
    assessment = _assessment(db, company_a)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    question = add_question(assessment.id, section.id, _mcq_payload(), owner_a, db)

    owner_b = _company_user(db, 2)
    company_b = _company(db, owner_b, name="Beta")

    # Another company cannot even reference the assessment/section.
    for fn, args in (
        (add_question, (assessment.id, section.id, _mcq_payload(), owner_b, db)),
        (list_questions, (assessment.id, section.id, owner_b, db)),
        (get_question, (assessment.id, section.id, question.id, owner_b, db)),
        (
            update_question,
            (assessment.id, section.id, question.id,
             schemas.AssessmentQuestionUpdate(question_text="Hijack"), owner_b, db),
        ),
        (delete_question, (assessment.id, section.id, question.id, owner_b, db)),
        (
            reorder_questions,
            (assessment.id, section.id,
             schemas.AssessmentQuestionReorderIn(ordered_question_ids=[question.id]),
             owner_b, db),
        ),
    ):
        with pytest.raises(Exception) as exc:
            fn(*args)
        assert exc.value.status_code == 403

    # Nothing changed.
    out = get_question(assessment.id, section.id, question.id, owner_a, db)
    assert out.question_text.startswith("Which sorting")
    assert company_b.id is not None


def test_admin_can_manage_any_company_questions(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.coding)
    admin = _admin_user(db, 9)

    out = add_question(assessment.id, section.id, _coding_payload(), admin, db)
    assert out.question_type == models.AssessmentQuestionTypeEnum.coding
    assert get_question(assessment.id, section.id, out.id, admin, db).id == out.id
    assert [q.id for q in list_questions(assessment.id, section.id, admin, db)] == [out.id]

    updated = update_question(
        assessment.id,
        section.id,
        out.id,
        schemas.AssessmentQuestionUpdate(title="Renamed by admin"),
        admin,
        db,
    )
    assert updated.title == "Renamed by admin"

    delete_question(assessment.id, section.id, out.id, admin, db)
    assert list_questions(assessment.id, section.id, admin, db) == []


def test_candidate_cannot_access_question_endpoints(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    candidate = _candidate_user(db, 10)

    with pytest.raises(Exception) as exc:
        company_scoped(current_user=candidate)
    assert exc.value.status_code == 403
    assert company_scoped(current_user=owner) is not None

    # A direct call also fails: candidates never pass company RBAC.
    with pytest.raises(Exception) as exc:
        add_question(assessment.id, section.id, _mcq_payload(), candidate, db)
    assert exc.value.status_code == 403
    with pytest.raises(Exception) as exc:
        list_questions(assessment.id, section.id, candidate, db)
    assert exc.value.status_code == 403


def test_section_belongs_to_assessment_validation(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    a1 = _assessment(db, company, title="One")
    a2 = _assessment(db, company, title="Two")
    section_of_a2 = _section(db, a2, models.AssessmentSectionTypeEnum.aptitude)

    # Pointing at assessment a1 with a section of a2 -> 404 Section not found.
    with pytest.raises(Exception) as exc:
        add_question(a1.id, section_of_a2.id, _mcq_payload(), owner, db)
    assert exc.value.status_code == 404
    with pytest.raises(Exception) as exc:
        list_questions(a1.id, section_of_a2.id, owner, db)
    assert exc.value.status_code == 404

    # A question row in a2's section is unreachable via a1.
    question = add_question(
        a2.id, section_of_a2.id, _mcq_payload(), owner, db
    )
    with pytest.raises(Exception) as exc:
        get_question(a1.id, section_of_a2.id, question.id, owner, db)
    assert exc.value.status_code == 404


def test_unknown_assessment_or_section_404(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)

    with pytest.raises(Exception) as exc:
        add_question(9999, section.id, _mcq_payload(), owner, db)
    assert exc.value.status_code == 404
    with pytest.raises(Exception) as exc:
        add_question(assessment.id, 9999, _mcq_payload(), owner, db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Correct-answer privacy
# ---------------------------------------------------------------------------
def test_candidate_facing_api_never_exposes_private_answer_data(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    candidate = _candidate_user(db, 10)
    assessment = _assessment(db, company)
    mcq_section = _section(
        db, assessment, models.AssessmentSectionTypeEnum.aptitude, order=1
    )
    coding_section = _section(
        db, assessment, models.AssessmentSectionTypeEnum.coding, order=2
    )
    add_question(assessment.id, mcq_section.id, _mcq_payload(), owner, db)
    add_question(assessment.id, coding_section.id, _coding_payload(), owner, db)

    db.add(
        models.AssessmentAssignment(
            assessment_id=assessment.id, candidate_id=candidate.id
        )
    )
    db.commit()

    detail = get_my_assessment(assessment.id, candidate, db)
    assert len(detail.sections) == 2

    # The candidate contract has no question/answer surface at all.
    section_dump = {s.title: s.model_dump() for s in detail.sections}
    for section_out in detail.sections:
        assert "questions" not in section_out.model_dump()
        assert "correct_index" not in section_out.model_dump()
        assert "hidden_cases" not in section_out.model_dump()
        assert "options" not in section_out.model_dump()
    assert "questions" not in detail.model_dump()

    # The candidate schemas themselves carry no private fields.
    for field in ("correct_index", "hidden_cases", "options", "questions"):
        assert field not in schemas.CandidateAssessmentSectionOut.model_fields
        assert field not in schemas.CandidateAssessmentAssignmentOut.model_fields

    # Company-side contracts DO carry them (for the owner company).
    listed = list_questions(assessment.id, mcq_section.id, owner, db)
    assert listed[0].correct_index == 0
    assert listed[0].options is not None
    coding = list_questions(assessment.id, coding_section.id, owner, db)
    assert coding[0].hidden_cases is not None


# ---------------------------------------------------------------------------
# Model / constraint contract
# ---------------------------------------------------------------------------
def test_duplicate_question_order_rejected_at_db(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.aptitude)
    add_question(assessment.id, section.id, _mcq_payload(question_order=1), owner, db)

    duplicate = models.AssessmentQuestion(
        section_id=section.id,
        question_type=models.AssessmentQuestionTypeEnum.mcq,
        question_text="Duplicate order",
        question_order=1,
        options=["A", "B", "C", "D"],
        correct_index=0,
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()


def test_delete_section_cascades_questions(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = _assessment(db, company)
    section = _section(db, assessment, models.AssessmentSectionTypeEnum.coding)
    add_question(assessment.id, section.id, _coding_payload(), owner, db)

    _ = assessment.sections, section.questions
    db.delete(section)
    db.commit()

    assert (
        db.query(models.AssessmentQuestion)
        .filter(models.AssessmentQuestion.section_id == section.id)
        .first()
        is None
    )


def test_migration_0014_matches_orm():
    import re
    from pathlib import Path

    versions = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    migration = versions / "0014_assessment_question_bank.py"
    assert migration.exists()

    src = migration.read_text(encoding="utf-8")
    assert 'revision = "0014_assessment_question_bank"' in src
    assert 'down_revision = "0013_company_assessments"' in src

    for table in ("assessment_questions",):
        assert f'"{table}"' in src
        assert table in {t.__tablename__ for t in (models.AssessmentQuestion,)}

    assert "assessmentquestiontypeenum" in src
    assert "uq_assessment_question_order" in src


def test_units_company_routes_still_unaffected(db):
    owner = _company_user(db, 1)
    company = _company(db, owner)
    assessment = create_assessment(schemas.AssessmentCreate(title="New"), owner, db)
    section = add_section(
        assessment.id,
        schemas.AssessmentSectionCreate(
            section_type=models.AssessmentSectionTypeEnum.aptitude, title="Aptitude"
        ),
        owner,
        db,
    )
    add_question(assessment.id, section.id, _mcq_payload(), owner, db)

    detail = get_assessment(assessment.id, owner, db)
    assert detail.sections[0].id == section.id
    assert [a.id for a in list_assessments(owner, db)] == [assessment.id]


def test_role_checker_rejects_candidate_and_allows_admin(db):
    owner = _company_user(db, 1)
    admin = _admin_user(db, 9)
    candidate = _candidate_user(db, 10)

    assert company_scoped(current_user=owner) is not None
    assert company_scoped(current_user=admin) is not None
    with pytest.raises(Exception) as exc:
        company_scoped(current_user=candidate)
    assert exc.value.status_code == 403
    assert RoleChecker(["company", "admin"])(current_user=admin) is not None
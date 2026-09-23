# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db
from app import models, schemas
from app.routes.company_assessments import (
    _owned_assessment,
    _owned_assignment,
    company_scoped,
)

router = APIRouter(
    prefix="/assessments", tags=["company-assessment-results"]
)


# ---------------------------------------------------------------------------
# Scoring (pure read-compute over persisted data, deterministic per request)
# ---------------------------------------------------------------------------

def _marks(question: models.AssessmentQuestion) -> int:
    """Effective maximum score of a question.

    The question's configured ``marks``, or 1 when unset — an unmarked
    question is still worth at least one mark so an assessment with no marks
    configured scores on a per-question basis.
    """
    return question.marks if question.marks is not None else 1


def _percentage(earned: int, maximum: int) -> int:
    """0-100 rounded percentage; 0 when there is nothing to score against."""
    if maximum <= 0:
        return 0
    return int(round((earned * 100) / maximum))


def _correct(
    question: models.AssessmentQuestion,
    answer: models.AssessmentAnswer | None,
) -> bool | None:
    """Whether the candidate's answer to a question was correct.

    MCQ uses the correctness snapshot persisted at answer time; coding uses
    the grading verdict (``passed`` = every hidden case passed). Unanswered
    questions have no correctness.
    """
    if answer is None:
        return None
    if question.question_type == models.AssessmentQuestionTypeEnum.mcq:
        return bool(answer.is_correct)
    return (answer.status or "error") == "passed"


def _earned(
    question: models.AssessmentQuestion,
    answer: models.AssessmentAnswer | None,
) -> int:
    """The marks a candidate earned on one question (0 when unanswered).

    MCQ: full marks when correct. Coding: marks scaled by the persisted
    per-question score (0-100), clamped so a corrupt score can never earn
    more than the question is worth.
    """
    if answer is None:
        return 0
    if question.question_type == models.AssessmentQuestionTypeEnum.mcq:
        return _marks(question) if answer.is_correct else 0
    proportional = int(round(_marks(question) * (answer.score or 0) / 100))
    return min(proportional, _marks(question))


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _paper(
    db: Session, assessment_id: int
) -> list[tuple[models.AssessmentSection, list[models.AssessmentQuestion]]]:
    """The scored paper: ordered sections, each with its questions in their
    configured order. Only sections holding at least one question participate
    in scoring (HR / interview sections have no question bank yet)."""
    sections = (
        db.query(models.AssessmentSection)
        .filter(models.AssessmentSection.assessment_id == assessment_id)
        .order_by(models.AssessmentSection.section_order)
        .all()
    )
    paper = []
    for section in sections:
        questions = (
            db.query(models.AssessmentQuestion)
            .filter(models.AssessmentQuestion.section_id == section.id)
            .order_by(models.AssessmentQuestion.question_order)
            .all()
        )
        if questions:
            paper.append((section, questions))
    return paper


def _answers_index(
    db: Session,
    assessment_id: int,
    assignment_ids: list[int] | None = None,
) -> dict[int, dict[int, models.AssessmentAnswer]]:
    """``assignment_id -> {question_id -> answer}`` for this assessment.

    Scoped by the assessment via the join, so answers can never leak from a
    different assessment's attempt. Loading the whole assessment in one query
    keeps the list endpoint single-pass regardless of candidate count.
    """
    query = (
        db.query(models.AssessmentAnswer)
        .join(
            models.AssessmentAssignment,
            models.AssessmentAnswer.assignment_id
            == models.AssessmentAssignment.id,
        )
        .filter(models.AssessmentAssignment.assessment_id == assessment_id)
    )
    if assignment_ids is not None:
        query = query.filter(models.AssessmentAssignment.id.in_(assignment_ids))
    by_assignment: dict[int, dict[int, models.AssessmentAnswer]] = {}
    for answer in query.all():
        by_assignment.setdefault(answer.assignment_id, {})[answer.question_id] = answer
    return by_assignment


def _question_result(
    section: models.AssessmentSection,
    question: models.AssessmentQuestion,
    answer: models.AssessmentAnswer | None,
) -> schemas.AssessmentQuestionResultOut:
    correct = _correct(question, answer)
    earned = _earned(question, answer)
    maximum = _marks(question)
    coding = question.question_type == models.AssessmentQuestionTypeEnum.coding
    return schemas.AssessmentQuestionResultOut(
        question_id=question.id,
        section_id=section.id,
        section_type=section.section_type,
        section_title=section.title,
        question_order=question.question_order,
        question_type=question.question_type,
        question_text=question.question_text,
        title=question.title,
        category=question.category,
        answered=answer is not None,
        selected_option=answer.selected_option if answer is not None else None,
        correct=correct,
        earned_score=earned,
        max_score=maximum,
        percentage=_percentage(earned, maximum),
        status=answer.status if (answer is not None and coding) else None,
        passed_cases=answer.passed_cases if (answer is not None and coding) else None,
        total_cases=answer.total_cases if (answer is not None and coding) else None,
        execution_time_ms=(
            answer.execution_time_ms if (answer is not None and coding) else None
        ),
        answered_at=answer.updated_at if answer is not None else None,
    )


def _section_result(
    section: models.AssessmentSection,
    questions: list[models.AssessmentQuestion],
    answers: dict[int, models.AssessmentAnswer],
) -> schemas.AssessmentSectionResultOut:
    answered = 0
    earned = 0
    maximum = 0
    for question in questions:
        answer = answers.get(question.id)
        if answer is not None:
            answered += 1
        earned += _earned(question, answer)
        maximum += _marks(question)
    return schemas.AssessmentSectionResultOut(
        section_id=section.id,
        section_type=section.section_type,
        title=section.title,
        section_order=section.section_order,
        total_questions=len(questions),
        answered_questions=answered,
        total_score=earned,
        maximum_score=maximum,
        percentage=_percentage(earned, maximum),
    )


def _result_out(
    db: Session,
    assessment: models.Assessment,
    assignment: models.AssessmentAssignment,
    answers: dict[int, models.AssessmentAnswer],
    include_questions: bool = False,
) -> schemas.AssessmentResultOut | schemas.AssessmentResultDetailOut:
    paper = _paper(db, assessment.id)
    total_questions = sum(len(questions) for _, questions in paper)
    section_results: list[schemas.AssessmentSectionResultOut] = []
    questions_out: list[schemas.AssessmentQuestionResultOut] = []
    answered_questions = 0
    total_score = 0
    maximum_score = 0
    for section, questions in paper:
        section_answers = {q.id: answers.get(q.id) for q in questions}
        section_result = _section_result(section, questions, section_answers)
        answered_questions += section_result.answered_questions
        total_score += section_result.total_score
        maximum_score += section_result.maximum_score
        section_results.append(section_result)
        if include_questions:
            questions_out.extend(
                _question_result(section, question, answers.get(question.id))
                for question in questions
            )

    candidate = assignment.candidate
    base = schemas.AssessmentResultOut(
        assignment_id=assignment.id,
        assessment_id=assessment.id,
        assessment_title=assessment.title,
        candidate_id=candidate.id,
        candidate_name=candidate.name,
        candidate_email=candidate.email,
        status=assignment.status,
        assigned_at=assignment.assigned_at,
        started_at=assignment.started_at,
        submitted_at=assignment.submitted_at,
        total_questions=total_questions,
        answered_questions=answered_questions,
        total_score=total_score,
        maximum_score=maximum_score,
        percentage=_percentage(total_score, maximum_score),
        sections=section_results,
    )
    if include_questions:
        return schemas.AssessmentResultDetailOut(
            **base.model_dump(), questions=questions_out
        )
    return base


# ---------------------------------------------------------------------------
# Endpoints (company / admin only — the owning company or any admin)
# ---------------------------------------------------------------------------

@router.get(
    "/{assessment_id}/results",
    response_model=list[schemas.AssessmentResultOut],
)
def list_results(
    assessment_id: int,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """List the submission results for every assigned candidate of the
    company's assessment, in stable assignment order.

    Unassigned candidates never appear (results are built from the
    assessment's own assignments), so nothing about unassigned users or
    unknown assignments is discoverable. Results are derived read-only —
    viewing never mutates state.
    """
    assessment = _owned_assessment(db, current_user, assessment_id)
    assignments = (
        db.query(models.AssessmentAssignment)
        .filter(models.AssessmentAssignment.assessment_id == assessment.id)
        .order_by(models.AssessmentAssignment.id)
        .all()
    )
    answers_by_assignment = _answers_index(db, assessment.id)
    return [
        _result_out(
            db,
            assessment,
            assignment,
            answers_by_assignment.get(assignment.id, {}),
        )
        for assignment in assignments
    ]


@router.get(
    "/{assessment_id}/results/{assignment_id}",
    response_model=schemas.AssessmentResultDetailOut,
)
def get_result(
    assessment_id: int,
    assignment_id: int,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """The full per-question result of one candidate's attempt.

    Question-level performance shows whether the answer was correct and the
    score earned — but never the hidden coding test cases, per-case execution
    output, or the MCQ answer key.
    """
    assessment = _owned_assessment(db, current_user, assessment_id)
    assignment = _owned_assignment(db, assessment, assignment_id)
    answers = _answers_index(
        db, assessment.id, [assignment.id]
    ).get(assignment.id, {})
    return _result_out(db, assessment, assignment, answers, include_questions=True)
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db
from app import models, schemas
from app.routes.company_assessments import (
    _owned_assessment,
    _owned_section,
    company_scoped,
)
from app.services.coding_tests import SUPPORTED_LANGUAGES, time_limit_seconds

router = APIRouter(prefix="/assessments", tags=["company-assessment-questions"])


# ---------------------------------------------------------------------------
# Section -> allowed question type mapping
# ---------------------------------------------------------------------------

def _allowed_question_type(
    section: models.AssessmentSection,
) -> models.AssessmentQuestionTypeEnum | None:
    """The single question type a section can hold, or None for sections with
    no question bank (hr / technical_interview are interview-based)."""
    if section.section_type == models.AssessmentSectionTypeEnum.coding:
        return models.AssessmentQuestionTypeEnum.coding
    if section.section_type in (
        models.AssessmentSectionTypeEnum.aptitude,
        models.AssessmentSectionTypeEnum.technical,
    ):
        return models.AssessmentQuestionTypeEnum.mcq
    return None


# ---------------------------------------------------------------------------
# Ownership guards
# ---------------------------------------------------------------------------

def _question_orders(db: Session, section_id: int) -> list[int]:
    """The question orders currently used by a section."""
    return [
        q.question_order
        for q in (
            db.query(models.AssessmentQuestion)
            .filter(models.AssessmentQuestion.section_id == section_id)
            .all()
        )
    ]


def _owned_question(
    db: Session, section: models.AssessmentSection, question_id: int
) -> models.AssessmentQuestion:
    """Return the question only if it belongs to the (already owned) section."""
    question = (
        db.query(models.AssessmentQuestion)
        .filter(
            models.AssessmentQuestion.id == question_id,
            models.AssessmentQuestion.section_id == section.id,
        )
        .first()
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return question


def _validate_or_400(question: models.AssessmentQuestion) -> None:
    """Re-validate a row against its question type (final-state guard for
    updates, where the pydantic schema cannot see the stored fields)."""
    try:
        schemas.validate_question_contract(
            question.question_type,
            options=question.options,
            correct_index=question.correct_index,
            hidden_cases=question.hidden_cases,
            sample_cases=question.sample_cases,
            time_limit_seconds=question.time_limit_seconds,
            supported_languages=question.supported_languages,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )


# ---------------------------------------------------------------------------
# Question CRUD
# ---------------------------------------------------------------------------

@router.post(
    "/{assessment_id}/sections/{section_id}/questions",
    response_model=schemas.AssessmentQuestionOut,
    status_code=201,
)
def add_question(
    assessment_id: int,
    section_id: int,
    payload: schemas.AssessmentQuestionCreate,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Add a question to one of the company's assessment sections, preventing
    duplicate question ordering."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    section = _owned_section(db, assessment, section_id)
    allowed = _allowed_question_type(section)
    if allowed is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This section type does not support question bank entries",
        )
    if payload.question_type != allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Question type '{payload.question_type.value}' does not match "
                f"the '{section.section_type.value}' section type"
            ),
        )

    orders = _question_orders(db, section.id)
    question_order = (
        payload.question_order
        if payload.question_order is not None
        else ((max(orders) + 1) if orders else 1)
    )
    if question_order in orders:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A question with this question_order already exists",
        )

    question = models.AssessmentQuestion(
        section_id=section.id,
        question_type=payload.question_type,
        question_text=payload.question_text,
        question_order=question_order,
        options=payload.options,
        correct_index=payload.correct_index,
        marks=payload.marks,
        explanation=payload.explanation,
        title=payload.title,
        category=payload.category,
        difficulty=payload.difficulty,
        input_format=payload.input_format,
        output_format=payload.output_format,
        constraints=payload.constraints,
        sample_cases=payload.sample_cases,
        hidden_cases=payload.hidden_cases,
        time_limit_seconds=payload.time_limit_seconds,
        supported_languages=payload.supported_languages,
    )
    if payload.question_type == models.AssessmentQuestionTypeEnum.coding:
        if question.time_limit_seconds is None:
            question.time_limit_seconds = time_limit_seconds()
        if question.supported_languages is None:
            question.supported_languages = list(SUPPORTED_LANGUAGES)
    _validate_or_400(question)

    db.add(question)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A question with this question_order already exists",
        )
    db.refresh(question)
    return schemas.AssessmentQuestionOut.model_validate(question)


@router.get(
    "/{assessment_id}/sections/{section_id}/questions",
    response_model=list[schemas.AssessmentQuestionOut],
)
def list_questions(
    assessment_id: int,
    section_id: int,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """List the questions of one of the company's assessment sections, in
    their configured order."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    section = _owned_section(db, assessment, section_id)
    questions = (
        db.query(models.AssessmentQuestion)
        .filter(models.AssessmentQuestion.section_id == section.id)
        .order_by(models.AssessmentQuestion.question_order)
        .all()
    )
    return [schemas.AssessmentQuestionOut.model_validate(q) for q in questions]


# Declared before "/questions/{question_id}" so the literal "reorder" suffix
# matches reliably.
@router.put(
    "/{assessment_id}/sections/{section_id}/questions/reorder",
    response_model=list[schemas.AssessmentQuestionOut],
)
def reorder_questions(
    assessment_id: int,
    section_id: int,
    payload: schemas.AssessmentQuestionReorderIn,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Reorder a section's questions (each question exactly once)."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    section = _owned_section(db, assessment, section_id)
    questions = (
        db.query(models.AssessmentQuestion)
        .filter(models.AssessmentQuestion.section_id == section.id)
        .all()
    )
    by_id = {q.id: q for q in questions}
    if set(by_id) != set(payload.ordered_question_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reorder must include exactly the questions of this section, once each",
        )
    ordered = [by_id[question_id] for question_id in payload.ordered_question_ids]
    # Two-phase reassignment: move every question to a unique temporary
    # (negative) order first, then to its final slot. A single batched flush
    # would hit the (section_id, question_order) unique constraint mid-
    # permutation; the temporary step guarantees every intermediate state is
    # conflict-free.
    for index, question in enumerate(ordered):
        question.question_order = -(index + 1)
    db.flush()
    for index, question in enumerate(ordered):
        question.question_order = index + 1
    db.commit()
    return [schemas.AssessmentQuestionOut.model_validate(q) for q in ordered]


@router.get(
    "/{assessment_id}/sections/{section_id}/questions/{question_id}",
    response_model=schemas.AssessmentQuestionOut,
)
def get_question(
    assessment_id: int,
    section_id: int,
    question_id: int,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Get one question of the company's assessment section."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    section = _owned_section(db, assessment, section_id)
    question = _owned_question(db, section, question_id)
    return schemas.AssessmentQuestionOut.model_validate(question)


@router.put(
    "/{assessment_id}/sections/{section_id}/questions/{question_id}",
    response_model=schemas.AssessmentQuestionOut,
)
def update_question(
    assessment_id: int,
    section_id: int,
    question_id: int,
    payload: schemas.AssessmentQuestionUpdate,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Update a question, preventing collisions on question_order and keeping
    the row valid for its question type."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    section = _owned_section(db, assessment, section_id)
    question = _owned_question(db, section, question_id)

    data = payload.model_dump(exclude_unset=True)
    new_type = data.get("question_type")
    if new_type is not None and new_type != _allowed_question_type(section):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Question type '{new_type.value}' does not match "
                f"the '{section.section_type.value}' section type"
            ),
        )
    new_order = data.get("question_order")
    if (
        new_order is not None
        and question.question_order != new_order
        and new_order in _question_orders(db, section.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A question with this question_order already exists",
        )

    for field, value in data.items():
        setattr(question, field, value)
    _validate_or_400(question)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A question with this question_order already exists",
        )
    db.refresh(question)
    return schemas.AssessmentQuestionOut.model_validate(question)


@router.delete(
    "/{assessment_id}/sections/{section_id}/questions/{question_id}",
    status_code=204,
)
def delete_question(
    assessment_id: int,
    section_id: int,
    question_id: int,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Remove a question from a section."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    section = _owned_section(db, assessment, section_id)
    question = _owned_question(db, section, question_id)
    db.delete(question)
    db.commit()
    return None
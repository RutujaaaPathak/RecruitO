# pyrefly: ignore [missing-import]
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth import RoleChecker
from app import models, schemas
from app.services.mock_interview import resolve_interview_context
from app.services.mcq_assessment import (
    build_question_row,
    expires_at,
    finalize_assessment,
    generate_questions,
    is_expired,
    pass_threshold,
    question_count,
    record_answer,
    time_limit_minutes,
)

router = APIRouter(prefix="/mcq-assessments", tags=["mcq-assessments"])

candidate_only = RoleChecker(["user"])


# ---------------------------------------------------------------------------
# Ownership guards
# ---------------------------------------------------------------------------

def _owned_application(
    db: Session, user: models.User, application_id: int
) -> models.Application:
    """Return the application only if it exists and belongs to the candidate."""
    app_ = (
        db.query(models.Application)
        .filter(models.Application.id == application_id)
        .first()
    )
    if app_ is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if app_.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this application",
        )
    return app_


def _owned_assessment(
    db: Session, user: models.User, assessment_id: int
) -> models.McqAssessment:
    """Return the assessment only if it exists and belongs to the candidate."""
    assessment = (
        db.query(models.McqAssessment)
        .filter(models.McqAssessment.id == assessment_id)
        .first()
    )
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this assessment",
        )
    return assessment


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _selected_map(assessment: models.McqAssessment) -> dict:
    """question_id -> the candidate's saved selected option."""
    return {
        answer.question_id: answer.selected_option
        for answer in (assessment.answers or [])
    }


def _question_out(
    q: models.McqQuestion,
    selected_map: dict,
) -> schemas.McqQuestionOut:
    """Serialize a question WITHOUT its correct answer key.

    Only the four options and the candidate's own saved selection are returned.
    """
    return schemas.McqQuestionOut(
        id=q.id,
        question_index=q.question_index,
        category=q.category,
        question_text=q.question_text,
        options=list(q.options or []),
        generated_by=("llm" if q.generated_by == "llm" else "fallback"),
        notice=q.notice,
        selected_option=selected_map.get(q.id),
    )


def _results_out(
    assessment: models.McqAssessment,
) -> schemas.McqResultsOut | None:
    if (
        assessment.status != models.AssessmentStatusEnum.completed
        or assessment.percentage is None
    ):
        return None
    return schemas.McqResultsOut(
        score=assessment.score or 0,
        total=assessment.total_scored or assessment.total_questions or 0,
        percentage=assessment.percentage or 0,
        correct_count=assessment.correct_count or 0,
        incorrect_count=assessment.incorrect_count or 0,
        unanswered_count=assessment.unanswered_count or 0,
        passed=bool(assessment.passed),
        pass_percentage=assessment.pass_percentage
        or pass_threshold(),
        category_performance=[
            schemas.McqCategoryPerformanceOut(**c)
            for c in (assessment.category_performance or [])
        ],
        expired=bool(assessment.expired),
        model_used=assessment.model_used or "none",
        generated_by=(assessment.generated_by or "fallback").lower(),
        used_fallback=bool(assessment.used_fallback),
        notice=assessment.result_notice,
    )


def _job_label(assessment: models.McqAssessment) -> tuple:
    application = assessment.application
    job = application.job if application is not None else None
    return (
        job.title if job else None,
        job.company.name if job and job.company else None,
    )


def _detail(assessment: models.McqAssessment) -> schemas.McqAssessmentDetailOut:
    selected_map = _selected_map(assessment)
    questions = list(assessment.questions or [])
    questions = sorted(questions, key=lambda q: q.question_index)
    job_title, company_name = _job_label(assessment)

    return schemas.McqAssessmentDetailOut(
        id=assessment.id,
        application_id=assessment.application_id,
        user_id=assessment.user_id,
        job_title=job_title,
        company_name=company_name,
        status=assessment.status,
        total_questions=assessment.total_questions,
        answered_count=len(assessment.answers or []),
        time_limit_minutes=assessment.time_limit_minutes,
        started_at=assessment.started_at,
        expires_at=(
            expires_at(assessment)
            if assessment.status == models.AssessmentStatusEnum.in_progress
            else None
        ),
        questions=[_question_out(q, selected_map) for q in questions],
        results=_results_out(assessment),
        generated_by=(assessment.generated_by or "fallback").lower(),
        used_fallback=bool(assessment.used_fallback),
        model_used=assessment.model_used or "none",
        completed_at=assessment.completed_at,
        created_at=assessment.created_at,
        updated_at=assessment.updated_at,
    )


def _list_out(assessment: models.McqAssessment) -> schemas.McqAssessmentListOut:
    job_title, company_name = _job_label(assessment)
    return schemas.McqAssessmentListOut(
        id=assessment.id,
        application_id=assessment.application_id,
        job_title=job_title,
        company_name=company_name,
        status=assessment.status,
        total_questions=assessment.total_questions,
        answered_count=len(assessment.answers or []),
        time_limit_minutes=assessment.time_limit_minutes,
        score=assessment.score,
        percentage=assessment.percentage,
        passed=assessment.passed,
        started_at=assessment.started_at,
        completed_at=assessment.completed_at,
        created_at=assessment.created_at,
        updated_at=assessment.updated_at,
    )


# ---------------------------------------------------------------------------
# Enforcement helpers
# ---------------------------------------------------------------------------

def _ensure_answerable(
    assessment: models.McqAssessment,
    now: datetime | None = None,
) -> None:
    """Raise when answers may no longer be recorded for this assessment."""
    if assessment.status != models.AssessmentStatusEnum.in_progress:
        raise HTTPException(
            status_code=400, detail="This assessment is not in progress"
        )
    if is_expired(assessment, now=now):
        raise HTTPException(
            status_code=400,
            detail=(
                "The time limit for this assessment has expired. Open the "
                "assessment to see your results."
            ),
        )


def _finalize_if_expired(
    assessment: models.McqAssessment,
    now: datetime | None = None,
) -> bool:
    """Auto-finalize an in-progress assessment whose timer has expired."""
    if (
        assessment.status == models.AssessmentStatusEnum.in_progress
        and is_expired(assessment, now=now)
    ):
        finalize_assessment(assessment, expired=True)
        return True
    return False


# ---------------------------------------------------------------------------
# Start an assessment
# ---------------------------------------------------------------------------

@router.post("", response_model=schemas.McqAssessmentDetailOut, status_code=201)
def start_mcq_assessment(
    payload: schemas.McqAssessmentStartIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Start a timed 20-question MCQ assessment for one of the candidate's
    applications. Generates the full question set (LLM or fallback bank) and
    returns the questions WITHOUT their correct answers."""
    application = _owned_application(db, current_user, payload.application_id)

    existing = (
        db.query(models.McqAssessment)
        .filter(
            models.McqAssessment.application_id == application.id,
            models.McqAssessment.user_id == current_user.id,
            models.McqAssessment.status
            == models.AssessmentStatusEnum.in_progress,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "An MCQ assessment is already in progress for this application "
                f"(assessment {existing.id}). Resume it instead of starting a new one."
            ),
        )

    ctx = resolve_interview_context(db, current_user, application)
    total = question_count()
    generation = generate_questions(ctx, total)

    assessment = models.McqAssessment(
        user_id=current_user.id,
        application_id=application.id,
        status=models.AssessmentStatusEnum.in_progress,
        total_questions=total,
        time_limit_minutes=time_limit_minutes(),
        pass_percentage=pass_threshold(),
        generated_by=generation["generated_by"],
        model_used=ctx.model_used,
        used_fallback=generation["used_fallback"],
    )
    db.add(assessment)
    db.flush()

    for question in generation["questions"]:
        db.add(build_question_row(assessment.id, question))
    db.commit()
    db.refresh(assessment)
    return _detail(assessment)


# ---------------------------------------------------------------------------
# Record / update an answer (upsert — never a duplicate row)
# ---------------------------------------------------------------------------

@router.post(
    "/{assessment_id}/answer",
    response_model=schemas.McqAssessmentDetailOut,
)
def answer_mcq_assessment_question(
    assessment_id: int,
    payload: schemas.McqAnswerIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Save the candidate's selected option for one question. Re-answering the
    same question updates the single stored row (no duplicate submissions).
    Correct answers are never returned."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    _ensure_answerable(assessment)

    question = next(
        (
            q
            for q in (assessment.questions or [])
            if q.question_index == payload.question_index
        ),
        None,
    )
    if question is None:
        raise HTTPException(
            status_code=404, detail="Question not found for this assessment"
        )

    record_answer(assessment, question, payload.selected_option)
    db.commit()
    db.refresh(assessment)
    return _detail(assessment)


# ---------------------------------------------------------------------------
# Submit the test (finalizes + scores; idempotent, backend-enforced deadline)
# ---------------------------------------------------------------------------

@router.post("/{assessment_id}/submit", response_model=schemas.McqResultsOut)
def submit_mcq_assessment(
    assessment_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Compute and store final results. An expired test is auto-scored from the
    answers saved before the deadline; a completed test returns its stored
    results without re-scoring or creating duplicate rows."""
    assessment = _owned_assessment(db, current_user, assessment_id)

    if assessment.status == models.AssessmentStatusEnum.completed:
        results = _results_out(assessment)
        if results is not None:
            return results
        raise HTTPException(
            status_code=500, detail="Stored assessment results are missing"
        )

    expired = is_expired(assessment)
    finalize_assessment(assessment, expired=expired)
    db.commit()
    db.refresh(assessment)

    results = _results_out(assessment)
    if results is None:
        raise HTTPException(status_code=500, detail="Failed to compute results")
    return results


# ---------------------------------------------------------------------------
# List / detail / results / delete
# ---------------------------------------------------------------------------

@router.get("", response_model=list[schemas.McqAssessmentListOut])
def list_mcq_assessments(
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """List the candidate's MCQ assessments, newest first."""
    assessments = (
        db.query(models.McqAssessment)
        .filter(models.McqAssessment.user_id == current_user.id)
        .order_by(models.McqAssessment.created_at.desc())
        .all()
    )
    return [_list_out(a) for a in assessments]


@router.get("/{assessment_id}", response_model=schemas.McqAssessmentDetailOut)
def get_mcq_assessment(
    assessment_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Return the assessment. If an in-progress test has passed its deadline it
    is auto-finalized here, so a refresh always lands on results once the
    timer has run out."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    if _finalize_if_expired(assessment):
        db.commit()
        db.refresh(assessment)
    return _detail(assessment)


@router.get("/{assessment_id}/results", response_model=schemas.McqResultsOut)
def get_mcq_assessment_results(
    assessment_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Return the final results of a completed MCQ assessment."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    if _finalize_if_expired(assessment):
        db.commit()
        db.refresh(assessment)
    results = _results_out(assessment)
    if results is None:
        raise HTTPException(
            status_code=404,
            detail="Results are not available until the assessment is submitted",
        )
    return results


@router.delete("/{assessment_id}", status_code=204)
def delete_mcq_assessment(
    assessment_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Delete the assessment, its questions and its answers."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    db.delete(assessment)
    db.commit()
    return None
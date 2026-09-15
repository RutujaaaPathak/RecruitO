# pyrefly: ignore [missing-import]
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth import RoleChecker
from app import models, schemas
from app.services.mock_interview import resolve_interview_context
from app.services.aptitude_test import (
    build_question_row,
    expires_at,
    finalize_test,
    generate_questions,
    is_expired,
    pass_threshold,
    question_count,
    record_answer,
    time_limit_minutes,
)

router = APIRouter(prefix="/aptitude-tests", tags=["aptitude-tests"])

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


def _owned_test(
    db: Session, user: models.User, test_id: int
) -> models.AptitudeTest:
    """Return the aptitude test only if it exists and belongs to the candidate."""
    test = (
        db.query(models.AptitudeTest)
        .filter(models.AptitudeTest.id == test_id)
        .first()
    )
    if test is None:
        raise HTTPException(status_code=404, detail="Aptitude test not found")
    if test.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this aptitude test",
        )
    return test


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _selected_map(test: models.AptitudeTest) -> dict:
    """question_id -> the candidate's saved selected option."""
    return {
        answer.question_id: answer.selected_option
        for answer in (test.answers or [])
    }


def _question_out(
    q: models.AptitudeQuestion,
    selected_map: dict,
) -> schemas.AptitudeQuestionOut:
    """Serialize a question WITHOUT its correct answer key.

    Only the four options and the candidate's own saved selection are returned.
    """
    return schemas.AptitudeQuestionOut(
        id=q.id,
        question_index=q.question_index,
        category=q.category,
        question_text=q.question_text,
        options=list(q.options or []),
        generated_by=("llm" if q.generated_by == "llm" else "fallback"),
        notice=q.notice,
        selected_option=selected_map.get(q.id),
    )


def _results_out(test: models.AptitudeTest) -> schemas.AptitudeResultsOut | None:
    if (
        test.status != models.AssessmentStatusEnum.completed
        or test.percentage is None
    ):
        return None
    return schemas.AptitudeResultsOut(
        score=test.score or 0,
        total=test.total_scored or test.total_questions or 0,
        percentage=test.percentage or 0,
        correct_count=test.correct_count or 0,
        incorrect_count=test.incorrect_count or 0,
        unanswered_count=test.unanswered_count or 0,
        passed=bool(test.passed),
        pass_percentage=test.pass_percentage or pass_threshold(),
        category_performance=[
            schemas.AptitudeCategoryPerformanceOut(**c)
            for c in (test.category_performance or [])
        ],
        expired=bool(test.expired),
        model_used=test.model_used or "none",
        generated_by=(test.generated_by or "fallback").lower(),
        used_fallback=bool(test.used_fallback),
        notice=test.result_notice,
    )


def _job_label(test: models.AptitudeTest) -> tuple:
    application = test.application
    job = application.job if application is not None else None
    return (
        job.title if job else None,
        job.company.name if job and job.company else None,
    )


def _detail(test: models.AptitudeTest) -> schemas.AptitudeTestDetailOut:
    selected_map = _selected_map(test)
    questions = list(test.questions or [])
    questions = sorted(questions, key=lambda q: q.question_index)
    job_title, company_name = _job_label(test)

    return schemas.AptitudeTestDetailOut(
        id=test.id,
        application_id=test.application_id,
        user_id=test.user_id,
        job_title=job_title,
        company_name=company_name,
        status=test.status,
        total_questions=test.total_questions,
        answered_count=len(test.answers or []),
        time_limit_minutes=test.time_limit_minutes,
        started_at=test.started_at,
        expires_at=(
            expires_at(test)
            if test.status == models.AssessmentStatusEnum.in_progress
            else None
        ),
        questions=[_question_out(q, selected_map) for q in questions],
        results=_results_out(test),
        generated_by=(test.generated_by or "fallback").lower(),
        used_fallback=bool(test.used_fallback),
        model_used=test.model_used or "none",
        completed_at=test.completed_at,
        created_at=test.created_at,
        updated_at=test.updated_at,
    )


def _list_out(test: models.AptitudeTest) -> schemas.AptitudeTestListOut:
    job_title, company_name = _job_label(test)
    return schemas.AptitudeTestListOut(
        id=test.id,
        application_id=test.application_id,
        job_title=job_title,
        company_name=company_name,
        status=test.status,
        total_questions=test.total_questions,
        answered_count=len(test.answers or []),
        time_limit_minutes=test.time_limit_minutes,
        score=test.score,
        percentage=test.percentage,
        passed=test.passed,
        started_at=test.started_at,
        completed_at=test.completed_at,
        created_at=test.created_at,
        updated_at=test.updated_at,
    )


# ---------------------------------------------------------------------------
# Enforcement helpers
# ---------------------------------------------------------------------------

def _ensure_answerable(
    test: models.AptitudeTest,
    now: datetime | None = None,
) -> None:
    """Raise when answers may no longer be recorded for this test."""
    if test.status != models.AssessmentStatusEnum.in_progress:
        raise HTTPException(
            status_code=400, detail="This aptitude test is not in progress"
        )
    if is_expired(test, now=now):
        raise HTTPException(
            status_code=400,
            detail=(
                "The time limit for this aptitude test has expired. Open the "
                "test to see your results."
            ),
        )


def _finalize_if_expired(
    test: models.AptitudeTest,
    now: datetime | None = None,
) -> bool:
    """Auto-finalize an in-progress test whose timer has expired."""
    if (
        test.status == models.AssessmentStatusEnum.in_progress
        and is_expired(test, now=now)
    ):
        finalize_test(test, expired=True)
        return True
    return False


# ---------------------------------------------------------------------------
# Start an aptitude test
# ---------------------------------------------------------------------------

@router.post("", response_model=schemas.AptitudeTestDetailOut, status_code=201)
def start_aptitude_test(
    payload: schemas.AptitudeTestStartIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Start a timed 20-question aptitude test for one of the candidate's
    applications. Generates the full question set (LLM or fallback bank) and
    returns the questions WITHOUT their correct answers."""
    application = _owned_application(db, current_user, payload.application_id)

    existing = (
        db.query(models.AptitudeTest)
        .filter(
            models.AptitudeTest.application_id == application.id,
            models.AptitudeTest.user_id == current_user.id,
            models.AptitudeTest.status
            == models.AssessmentStatusEnum.in_progress,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "An aptitude test is already in progress for this application "
                f"(test {existing.id}). Resume it instead of starting a new one."
            ),
        )

    ctx = resolve_interview_context(db, current_user, application)
    total = question_count()
    generation = generate_questions(ctx, total)

    test = models.AptitudeTest(
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
    db.add(test)
    db.flush()

    for question in generation["questions"]:
        db.add(build_question_row(test.id, question))
    db.commit()
    db.refresh(test)
    return _detail(test)


# ---------------------------------------------------------------------------
# Record / update an answer (upsert — never a duplicate row)
# ---------------------------------------------------------------------------

@router.post(
    "/{test_id}/answer",
    response_model=schemas.AptitudeTestDetailOut,
)
def answer_aptitude_test_question(
    test_id: int,
    payload: schemas.AptitudeAnswerIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Save the candidate's selected option for one question. Re-answering the
    same question updates the single stored row (no duplicate submissions).
    Correct answers are never returned."""
    test = _owned_test(db, current_user, test_id)
    _ensure_answerable(test)

    question = next(
        (
            q
            for q in (test.questions or [])
            if q.question_index == payload.question_index
        ),
        None,
    )
    if question is None:
        raise HTTPException(
            status_code=404, detail="Question not found for this aptitude test"
        )

    record_answer(test, question, payload.selected_option)
    db.commit()
    db.refresh(test)
    return _detail(test)


# ---------------------------------------------------------------------------
# Submit the test (finalizes + scores; idempotent, backend-enforced deadline)
# ---------------------------------------------------------------------------

@router.post("/{test_id}/submit", response_model=schemas.AptitudeResultsOut)
def submit_aptitude_test(
    test_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Compute and store final results. An expired test is auto-scored from the
    answers saved before the deadline; a completed test returns its stored
    results without re-scoring or creating duplicate rows."""
    test = _owned_test(db, current_user, test_id)

    if test.status == models.AssessmentStatusEnum.completed:
        results = _results_out(test)
        if results is not None:
            return results
        raise HTTPException(
            status_code=500, detail="Stored aptitude test results are missing"
        )

    expired = is_expired(test)
    finalize_test(test, expired=expired)
    db.commit()
    db.refresh(test)

    results = _results_out(test)
    if results is None:
        raise HTTPException(status_code=500, detail="Failed to compute results")
    return results


# ---------------------------------------------------------------------------
# List / detail / results / delete
# ---------------------------------------------------------------------------

@router.get("", response_model=list[schemas.AptitudeTestListOut])
def list_aptitude_tests(
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """List the candidate's aptitude tests, newest first."""
    tests = (
        db.query(models.AptitudeTest)
        .filter(models.AptitudeTest.user_id == current_user.id)
        .order_by(models.AptitudeTest.created_at.desc())
        .all()
    )
    return [_list_out(t) for t in tests]


@router.get("/{test_id}", response_model=schemas.AptitudeTestDetailOut)
def get_aptitude_test(
    test_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Return the aptitude test. If an in-progress test has passed its deadline
    it is auto-finalized here, so a refresh always lands on results once the
    timer has run out."""
    test = _owned_test(db, current_user, test_id)
    if _finalize_if_expired(test):
        db.commit()
        db.refresh(test)
    return _detail(test)


@router.get("/{test_id}/results", response_model=schemas.AptitudeResultsOut)
def get_aptitude_test_results(
    test_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Return the final results of a completed aptitude test."""
    test = _owned_test(db, current_user, test_id)
    if _finalize_if_expired(test):
        db.commit()
        db.refresh(test)
    results = _results_out(test)
    if results is None:
        raise HTTPException(
            status_code=404,
            detail="Results are not available until the aptitude test is submitted",
        )
    return results


@router.delete("/{test_id}", status_code=204)
def delete_aptitude_test(
    test_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Delete the aptitude test, its questions and its answers."""
    test = _owned_test(db, current_user, test_id)
    db.delete(test)
    db.commit()
    return None
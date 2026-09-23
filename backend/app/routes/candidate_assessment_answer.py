# pyrefly: ignore [missing-import]
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db
from app import models, schemas
from app.routes.candidate_assessments import _my_assignment, candidate_only
from app.routes.candidate_assessment_start import _deadline_at, _sections_out
from app.services.code_executor import execute_code, validate_code
from app.services.coding_tests import SUPPORTED_LANGUAGES, time_limit_seconds
from app.services.notifications import create_notification

router = APIRouter(
    prefix="/me/assessments", tags=["candidate-assessment-answers"]
)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def _owned_question(
    db: Session,
    assignment: models.AssessmentAssignment,
    question_id: int,
) -> models.AssessmentQuestion:
    """Return the question only if it belongs to the assessment being tried.

    A question from another assessment (or an unknown id) is rejected up front,
    so a candidate can never answer a question outside their own attempt.
    """
    question = (
        db.query(models.AssessmentQuestion)
        .join(
            models.AssessmentSection,
            models.AssessmentQuestion.section_id == models.AssessmentSection.id,
        )
        .filter(
            models.AssessmentQuestion.id == question_id,
            models.AssessmentSection.assessment_id
            == assignment.assessment_id,
        )
        .first()
    )
    if question is None:
        raise HTTPException(
            status_code=400,
            detail="Question does not belong to this assessment",
        )
    return question


def _finalize_if_expired(
    db: Session, assignment: models.AssessmentAssignment
) -> bool:
    """Auto-submit an in-progress attempt whose deadline has passed.

    Returns ``True`` only when this call performed the auto-submit transition
    (the attempt was still in progress and its deadline elapsed). The
    transition is atomic (conditional update) so concurrent requests cannot
    double-finalize. ``submitted_at`` records the actual deadline, not the
    moment the check happened.
    """
    if assignment.status != models.AssessmentAssignmentStatusEnum.in_progress:
        return False
    if assignment.started_at is None:
        return False
    deadline = _deadline_at(assignment.assessment, assignment.started_at)
    if deadline is None or datetime.utcnow() <= deadline:
        return False
    db.execute(
        update(models.AssessmentAssignment)
        .where(
            models.AssessmentAssignment.id == assignment.id,
            models.AssessmentAssignment.status
            == models.AssessmentAssignmentStatusEnum.in_progress,
        )
        .values(
            status=models.AssessmentAssignmentStatusEnum.submitted,
            submitted_at=deadline,
        )
        .execution_options(synchronize_session=False)
    )
    # The atomic transition above can win exactly once, so the company-facing
    # auto-submit notification is created exactly once too (retries never
    # duplicate it). Built and committed with the transition itself.
    _notify_company_submission(db, assignment, auto=True)
    db.commit()
    db.refresh(assignment)
    return True


def _ensure_accepting_answers(assignment: models.AssessmentAssignment) -> None:
    """Reject save requests against an attempt that must not change."""
    if assignment.status == models.AssessmentAssignmentStatusEnum.assigned:
        raise HTTPException(
            status_code=400, detail="Assessment has not been started"
        )
    if assignment.status == models.AssessmentAssignmentStatusEnum.submitted:
        raise HTTPException(
            status_code=409, detail="Assessment has already been submitted"
        )


# ---------------------------------------------------------------------------
# Persistence (idempotent upsert per (attempt, question))
# ---------------------------------------------------------------------------

def _upsert_answer(
    db: Session,
    assignment: models.AssessmentAssignment,
    question: models.AssessmentQuestion,
    data: dict,
) -> models.AssessmentAnswer:
    """Write the latest answer for (assignment, question), creating or
    overwriting the single row. IntegrityError (a concurrent request winning
    the insert) retries as an update so duplicates can never accumulate."""
    answer = (
        db.query(models.AssessmentAnswer)
        .filter(
            models.AssessmentAnswer.assignment_id == assignment.id,
            models.AssessmentAnswer.question_id == question.id,
        )
        .first()
    )
    if answer is None:
        answer = models.AssessmentAnswer(
            assignment_id=assignment.id, question_id=question.id, **data
        )
        db.add(answer)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            answer = (
                db.query(models.AssessmentAnswer)
                .filter(
                    models.AssessmentAnswer.assignment_id == assignment.id,
                    models.AssessmentAnswer.question_id == question.id,
                )
                .first()
            )
            for field, value in data.items():
                setattr(answer, field, value)
            db.commit()
    else:
        for field, value in data.items():
            setattr(answer, field, value)
        db.commit()
    db.refresh(answer)
    return answer


def _answer_out(
    answer: models.AssessmentAnswer, question: models.AssessmentQuestion
) -> schemas.AssessmentAnswerOut:
    """Serialize an answer without leaking private evaluation data: per-case
    results carry only index/pass/status/time (no hidden-case I/O)."""
    results = [
        schemas.CodingTestCaseResultOut(
            case_index=int(r.get("case_index", 0) or 0),
            passed=bool(r.get("passed", False)),
            status=r.get("status", "error"),
            stdout="",
            stderr="",
            time_ms=int(r.get("time_ms", 0) or 0),
        )
        for r in (answer.results or [])
    ]
    return schemas.AssessmentAnswerOut(
        question_id=question.id,
        question_type=question.question_type,
        selected_option=answer.selected_option,
        language=answer.language,
        status=answer.status,
        passed_cases=answer.passed_cases,
        total_cases=answer.total_cases,
        score=answer.score,
        execution_time_ms=answer.execution_time_ms,
        error_message=(
            answer.error_message[:2000] if answer.error_message else None
        ),
        results=results,
        created_at=answer.created_at,
        updated_at=answer.updated_at,
    )


def _submit_out(
    db: Session, assignment: models.AssessmentAssignment
) -> schemas.CandidateAssessmentSubmitOut:
    answered = (
        db.query(models.AssessmentAnswer)
        .filter(models.AssessmentAnswer.assignment_id == assignment.id)
        .count()
    )
    return schemas.CandidateAssessmentSubmitOut(
        attempt_id=assignment.id,
        assessment_id=assignment.assessment_id,
        status=assignment.status,
        submitted_at=assignment.submitted_at,
        answered_count=answered,
    )


def _notify_company_submission(
    db: Session,
    assignment: models.AssessmentAssignment,
    *,
    auto: bool,
) -> None:
    """Queue (without committing) the company-facing submission notification.

    Called only by a request that actually performed the in_progress →
    submitted transition (explicit submit or deadline auto-submit), which is
    atomic and can win exactly once, so a retry or a concurrent request can
    never create a duplicate. The recipient is the owning company's user (from
    the assessment's company row — never from the client), so a notification
    can never land in another company's inbox. The message carries only the
    assessment title and candidate name: never answers, hidden cases, code or
    scores.
    """
    company = assignment.assessment.company
    if company is None:
        return
    candidate_name = assignment.candidate.name if assignment.candidate else None
    display = candidate_name or "A candidate"
    if auto:
        title = "Assessment Auto-submitted"
        message = (
            f"{display}'s attempt at '{assignment.assessment.title}' was "
            "auto-submitted after the deadline."
        )
    else:
        title = "Assessment Submitted"
        message = f"{display} submitted '{assignment.assessment.title}'."
    create_notification(
        db,
        company.user_id,
        type=models.NotificationType.assessment,
        title=title,
        message=message,
        link=f"/company/assessments/{assignment.assessment_id}",
    )


# ---------------------------------------------------------------------------
# Re-entry: the candidate's own attempt content + saved answers
# ---------------------------------------------------------------------------

@router.get(
    "/{assessment_id}/attempt",
    response_model=schemas.CandidateAssessmentAttemptOut,
)
def get_my_attempt(
    assessment_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Re-fetch the candidate's own attempt without re-starting the clock.

    Frontend refresh / re-entry needs the full test content (sections +
    questions) plus the candidate's own saved answers; ``start`` returns the
    content only once (it 409s on an already-started attempt) and the answer
    save endpoint persists one question at a time. This endpoint restores that
    exact state from the backend.

    An attempt that was never started is a 400 (candidates must ``start``
    first). An expired in-progress attempt is finalized here — the same atomic
    auto-submit used by the answer/submit paths — and returned as
    ``submitted``. Everything is candidate-safe: only the candidate's own
    answers (never ``is_correct``, ``correct_index``, hidden-case I/O or the
    stored code draft) and never another candidate's data.
    """
    assignment = _my_assignment(db, current_user, assessment_id)
    _finalize_if_expired(db, assignment)

    if assignment.status == models.AssessmentAssignmentStatusEnum.assigned:
        raise HTTPException(
            status_code=400, detail="Assessment has not been started"
        )

    assessment = assignment.assessment
    answer_rows = (
        db.query(models.AssessmentAnswer, models.AssessmentQuestion)
        .join(
            models.AssessmentQuestion,
            models.AssessmentAnswer.question_id == models.AssessmentQuestion.id,
        )
        .filter(models.AssessmentAnswer.assignment_id == assignment.id)
        .all()
    )
    answers = [_answer_out(answer, question) for answer, question in answer_rows]

    return schemas.CandidateAssessmentAttemptOut(
        attempt_id=assignment.id,
        assessment_id=assessment.id,
        title=assessment.title,
        description=assessment.description,
        instructions=assessment.instructions,
        company_name=assessment.company.name,
        status=assignment.status,
        duration_minutes=assessment.duration_minutes,
        started_at=assignment.started_at,
        deadline_at=_deadline_at(assessment, assignment.started_at),
        starts_at=assessment.starts_at,
        ends_at=assessment.ends_at,
        sections=_sections_out(db, assessment.id),
        answers=answers,
        submitted_at=assignment.submitted_at,
    )


# ---------------------------------------------------------------------------
# Save / update one answer
# ---------------------------------------------------------------------------

@router.post("/{assessment_id}/answers", response_model=schemas.AssessmentAnswerOut)
def save_assessment_answer(
    assessment_id: int,
    payload: schemas.AssessmentAnswerSaveIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Save (or overwrite) the candidate's latest answer to one question.

    MCQ/aptitude/technical: ``selected_option``. Coding: ``code`` +
    ``language``, evaluated server-side against the hidden cases via the shared
    Docker sandbox. Saving is an idempotent upsert — one row per question.
    """
    assignment = _my_assignment(db, current_user, assessment_id)
    if _finalize_if_expired(db, assignment):
        raise HTTPException(
            status_code=409, detail="Assessment deadline has passed"
        )
    _ensure_accepting_answers(assignment)
    question = _owned_question(db, assignment, payload.question_id)

    if payload.selected_option is not None:
        if question.question_type != models.AssessmentQuestionTypeEnum.mcq:
            raise HTTPException(
                status_code=400,
                detail="Selected-option answers require an MCQ question",
            )
        options = question.options or []
        if not 0 <= payload.selected_option < len(options):
            raise HTTPException(
                status_code=400, detail="selected_option is out of range"
            )
        answer = _upsert_answer(
            db,
            assignment,
            question,
            {
                "selected_option": payload.selected_option,
                "is_correct": question.correct_index == payload.selected_option,
                # Clear any previous coding fields.
                "language": None,
                "code": None,
                "status": None,
                "passed_cases": None,
                "total_cases": None,
                "score": None,
                "execution_time_ms": None,
                "error_message": None,
                "results": None,
            },
        )
    else:
        if question.question_type != models.AssessmentQuestionTypeEnum.coding:
            raise HTTPException(
                status_code=400,
                detail="Code answers require a coding question",
            )
        supported = question.supported_languages or SUPPORTED_LANGUAGES
        if payload.language not in supported:
            raise HTTPException(
                status_code=400,
                detail=f"Language must be one of {supported}",
            )
        try:
            validate_code(payload.code, payload.language)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        cases = list(question.hidden_cases or [])
        if not cases:
            result = None
            passed_cases, total_cases = 0, 0
            compile_error = True
            compile_detail = "This problem has no hidden test cases configured."
        else:
            result = execute_code(
                payload.language,
                payload.code,
                cases,
                time_limit=question.time_limit_seconds or time_limit_seconds(),
            )
            passed_cases = sum(1 for r in result.test_results if r.passed)
            total_cases = len(result.test_results)
            compile_error = result.compile_error
            compile_detail = result.compile_stderr

        if result is None or compile_error:
            status_val = "error"
            score = 0
            error_message = (
                compile_detail[:2000] or "Compilation failed"
            )
        else:
            score = (
                int(round((passed_cases / total_cases) * 100))
                if total_cases
                else 0
            )
            status_val = (
                "passed" if passed_cases == total_cases else "failed"
            )
            error_message = None

        per_case = (
            [
                {
                    "case_index": r.case_index,
                    "passed": r.passed,
                    "status": r.status,
                    "time_ms": r.time_ms,
                }
                for r in result.test_results
            ]
            if result
            else []
        )
        answer = _upsert_answer(
            db,
            assignment,
            question,
            {
                "language": payload.language,
                "code": payload.code,
                "status": status_val,
                "passed_cases": passed_cases,
                "total_cases": total_cases,
                "score": score,
                "execution_time_ms": result.total_time_ms if result else None,
                "error_message": error_message,
                "results": per_case,
                # Clear any previous MCQ fields.
                "selected_option": None,
                "is_correct": None,
            },
        )

    return _answer_out(answer, question)


# ---------------------------------------------------------------------------
# Submit the whole assessment
# ---------------------------------------------------------------------------

@router.post(
    "/{assessment_id}/submit",
    response_model=schemas.CandidateAssessmentSubmitOut,
)
def submit_assessment(
    assessment_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Submit the candidate's attempt.

    Deadline-expired attempts are finalized here too (auto-submit). The
    in_progress → submitted transition is atomic (conditional update) so two
    simultaneous submits cannot double-finalize; submitting an already
    submitted attempt is a harmless idempotent re-read of the same state.
    """
    assignment = _my_assignment(db, current_user, assessment_id)
    _finalize_if_expired(db, assignment)

    if assignment.status == models.AssessmentAssignmentStatusEnum.assigned:
        raise HTTPException(
            status_code=400, detail="Assessment has not been started"
        )
    if assignment.status == models.AssessmentAssignmentStatusEnum.submitted:
        return _submit_out(db, assignment)

    result = db.execute(
        update(models.AssessmentAssignment)
        .where(
            models.AssessmentAssignment.id == assignment.id,
            models.AssessmentAssignment.status
            == models.AssessmentAssignmentStatusEnum.in_progress,
        )
        .values(
            status=models.AssessmentAssignmentStatusEnum.submitted,
            submitted_at=datetime.utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        db.rollback()
        db.expire_all()
        assignment = db.get(models.AssessmentAssignment, assignment.id)
        if assignment is None:
            raise HTTPException(status_code=404, detail="Assessment not found")
        if assignment.status == models.AssessmentAssignmentStatusEnum.assigned:
            raise HTTPException(
                status_code=400, detail="Assessment has not been started"
            )
        return _submit_out(db, assignment)

    # The atomic transition above can win exactly once, so the explicit-submit
    # notification is created exactly once too (re-submits / retries never
    # duplicate it). Built and committed with the transition itself.
    _notify_company_submission(db, assignment, auto=False)
    db.commit()
    db.refresh(assignment)
    return _submit_out(db, assignment)
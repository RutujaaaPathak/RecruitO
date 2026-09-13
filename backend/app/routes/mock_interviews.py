# pyrefly: ignore [missing-import]
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth import RoleChecker
from app import models, schemas
from app.services.mock_interview import (
    _snapshot_sources,
    apply_evaluation,
    apply_report,
    build_qa_pairs,
    build_question_row,
    category_for_index,
    evaluate_answer,
    generate_question,
    generate_report,
    max_questions,
    resolve_interview_context,
)

router = APIRouter(prefix="/mock-interviews", tags=["mock-interviews"])

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


def _owned_interview(
    db: Session, user: models.User, interview_id: int
) -> models.MockInterview:
    """Return the mock interview only if it exists and belongs to the candidate."""
    interview = (
        db.query(models.MockInterview)
        .filter(models.MockInterview.id == interview_id)
        .first()
    )
    if interview is None:
        raise HTTPException(status_code=404, detail="Mock interview not found")
    if interview.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this mock interview",
        )
    return interview


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _question_out(q: models.MockInterviewQuestion) -> schemas.MockInterviewQuestionOut:
    return schemas.MockInterviewQuestionOut(
        id=q.id,
        question_index=q.question_index,
        category=q.category,
        question_text=q.question_text,
        generated_by=("llm" if q.generated_by == "llm" else "fallback"),
        notice=q.notice,
        sources=[schemas.ChunkSource(**s) for s in (q.question_sources or [])],
    )


def _evaluation_out(q: models.MockInterviewQuestion) -> schemas.EvaluationOut:
    return schemas.EvaluationOut(
        score=q.score if q.score is not None else 0,
        correctness=q.correctness or "",
        strengths=q.strengths or [],
        weaknesses=q.weaknesses or [],
        missing_points=q.missing_points or [],
        feedback=q.feedback or "",
        generated_by=(
            "llm" if q.evaluation_generated_by == "llm" else "fallback"
        ),
        notice=q.evaluation_notice,
    )


def _answered_out(q: models.MockInterviewQuestion) -> schemas.AnsweredQuestionOut:
    return schemas.AnsweredQuestionOut(
        question=_question_out(q),
        answer=q.answer_text or "",
        evaluation=_evaluation_out(q),
    )


def _report_out(
    interview: models.MockInterview,
) -> schemas.MockInterviewReportOut | None:
    if interview.status != models.MockInterviewStatusEnum.completed:
        return None
    if not interview.report:
        return None
    return schemas.MockInterviewReportOut(
        overall_score=interview.overall_score or 0,
        category_scores=[
            schemas.CategoryScoreOut(**c) for c in (interview.category_scores or [])
        ],
        strengths=interview.strengths or [],
        weaknesses=interview.weaknesses or [],
        recommended_topics=interview.recommended_topics or [],
        summary=interview.summary or "",
        generated_by=(
            "llm" if interview.report_generated_by == "llm" else "fallback"
        ),
        notice=interview.report_notice,
    )


def _job_label(interview: models.MockInterview) -> tuple:
    application = interview.application
    job = application.job if application is not None else None
    return (
        job.title if job else None,
        job.company.name if job and job.company else None,
    )


def _detail(
    interview: models.MockInterview,
) -> schemas.MockInterviewDetailOut:
    questions = list(interview.questions or [])
    answered = [q for q in questions if q.answer_text is not None]
    current = next((q for q in questions if q.answer_text is None), None)
    job_title, company_name = _job_label(interview)
    skill_gap = interview.skill_gap or {}

    return schemas.MockInterviewDetailOut(
        id=interview.id,
        application_id=interview.application_id,
        user_id=interview.user_id,
        job_title=job_title,
        company_name=company_name,
        status=interview.status,
        max_questions=interview.max_questions,
        current_question=_question_out(current) if current else None,
        answered=[_answered_out(q) for q in answered],
        matched_skills=skill_gap.get("matched", []),
        missing_skills=skill_gap.get("missing", []),
        model_used=interview.model_used or "none",
        used_fallback=interview.used_fallback or False,
        report=_report_out(interview),
        started_at=interview.started_at,
        completed_at=interview.completed_at,
        created_at=interview.created_at,
        updated_at=interview.updated_at,
    )


# ---------------------------------------------------------------------------
# Start a mock interview
# ---------------------------------------------------------------------------

@router.post("", response_model=schemas.MockInterviewDetailOut, status_code=201)
def start_mock_interview(
    payload: schemas.MockInterviewStartIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Start a text-based AI mock interview for one of the candidate's
    applications. Creates the session, captures the grounded context (resume +
    job + RAG chunks + skill-gap snapshot) and generates the first question."""
    application = _owned_application(db, current_user, payload.application_id)

    resume = (
        db.query(models.Resume)
        .filter(models.Resume.user_id == current_user.id)
        .order_by(models.Resume.uploaded_at.desc())
        .first()
    )
    if resume is None or not (resume.parsed_text or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Upload a resume before starting a mock interview",
        )

    existing = (
        db.query(models.MockInterview)
        .filter(
            models.MockInterview.application_id == application.id,
            models.MockInterview.user_id == current_user.id,
            models.MockInterview.status
            == models.MockInterviewStatusEnum.in_progress,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "A mock interview is already in progress for this application "
                f"(session {existing.id}). Resume it instead of starting a new one."
            ),
        )

    ctx = resolve_interview_context(db, current_user, application)
    total = max_questions()
    sources = _snapshot_sources(ctx)
    first_category = category_for_index(0)
    question_result = generate_question(ctx, first_category, 0, total)

    interview = models.MockInterview(
        user_id=current_user.id,
        application_id=application.id,
        status=models.MockInterviewStatusEnum.in_progress,
        max_questions=total,
        skill_gap={"matched": ctx.matched_skills, "missing": ctx.missing_skills},
        sources=sources,
        model_used=ctx.model_used,
        used_fallback=ctx.used_fallback,
    )
    db.add(interview)
    db.flush()

    question = build_question_row(
        interview.id,
        0,
        first_category,
        question_result,
        sources,
    )
    db.add(question)
    db.commit()
    db.refresh(interview)
    return _detail(interview)


# ---------------------------------------------------------------------------
# Answer the current question
# ---------------------------------------------------------------------------

@router.post(
    "/{interview_id}/answer",
    response_model=schemas.MockInterviewAnswerResponse,
)
def answer_mock_interview_question(
    interview_id: int,
    payload: schemas.MockInterviewAnswerIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Answer the current question. Evaluates the answer, persists the
    evaluation, then either generates the next (adaptive) question or, after
    the final question, generates the report and completes the interview."""
    interview = _owned_interview(db, current_user, interview_id)
    if interview.status != models.MockInterviewStatusEnum.in_progress:
        raise HTTPException(
            status_code=400, detail="This interview is not in progress"
        )

    question = next(
        (q for q in (interview.questions or []) if q.answer_text is None),
        None,
    )
    if question is None:
        raise HTTPException(
            status_code=400, detail="There are no pending questions for this interview"
        )

    application = _owned_application(db, current_user, interview.application_id)
    ctx = resolve_interview_context(db, current_user, application)

    evaluation = evaluate_answer(
        ctx, question.question_text, question.category, payload.answer_text
    )
    apply_evaluation(question, payload.answer_text, evaluation)

    answered_count = sum(
        1 for q in (interview.questions or []) if q.answer_text is not None
    )

    next_question = None
    report = None
    if answered_count < interview.max_questions:
        next_index = question.question_index + 1
        category = category_for_index(next_index)
        question_result = generate_question(
            ctx,
            category,
            next_index,
            interview.max_questions,
            previous_answer=payload.answer_text,
        )
        row = build_question_row(
            interview.id,
            next_index,
            category,
            question_result,
            _snapshot_sources(ctx),
        )
        db.add(row)
        db.flush()
        next_question = _question_out(row)
    else:
        qa_pairs = build_qa_pairs(list(interview.questions or []))
        report_dict = generate_report(ctx, qa_pairs)
        apply_report(
            interview, report_dict, completed_at=datetime.utcnow()
        )
        interview.status = models.MockInterviewStatusEnum.completed
        report = _report_out(interview)

    db.commit()
    db.refresh(interview)

    return schemas.MockInterviewAnswerResponse(
        interview=_detail(interview),
        evaluation=_evaluation_out(question),
        next_question=next_question,
        report=report,
    )


# ---------------------------------------------------------------------------
# End the interview early (generates the report from answered questions)
# ---------------------------------------------------------------------------

@router.post("/{interview_id}/end", response_model=schemas.MockInterviewReportOut)
def end_mock_interview(
    interview_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """End the interview and produce the final report. If the interview is
    already completed the stored report is returned unchanged."""
    interview = _owned_interview(db, current_user, interview_id)

    if interview.status == models.MockInterviewStatusEnum.completed:
        existing_report = _report_out(interview)
        if existing_report is not None:
            return existing_report
        raise HTTPException(
            status_code=500, detail="Stored interview report is missing"
        )

    application = _owned_application(db, current_user, interview.application_id)
    ctx = resolve_interview_context(db, current_user, application)
    qa_pairs = build_qa_pairs(list(interview.questions or []))

    report_dict = generate_report(ctx, qa_pairs)
    apply_report(interview, report_dict, completed_at=datetime.utcnow())
    interview.status = models.MockInterviewStatusEnum.completed

    db.commit()
    db.refresh(interview)

    report = _report_out(interview)
    if report is None:
        raise HTTPException(status_code=500, detail="Failed to build interview report")
    return report


# ---------------------------------------------------------------------------
# List / detail / report / delete
# ---------------------------------------------------------------------------

@router.get("", response_model=list[schemas.MockInterviewListOut])
def list_mock_interviews(
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """List the candidate's mock interviews, newest first."""
    sessions = (
        db.query(models.MockInterview)
        .filter(models.MockInterview.user_id == current_user.id)
        .order_by(models.MockInterview.created_at.desc())
        .all()
    )
    result = []
    for session in sessions:
        answered_count = sum(
            1 for q in (session.questions or []) if q.answer_text is not None
        )
        job_title, company_name = _job_label(session)
        result.append(
            schemas.MockInterviewListOut(
                id=session.id,
                application_id=session.application_id,
                job_title=job_title,
                company_name=company_name,
                status=session.status,
                max_questions=session.max_questions,
                answered_count=answered_count,
                overall_score=session.overall_score,
                started_at=session.started_at,
                completed_at=session.completed_at,
                created_at=session.created_at,
                updated_at=session.updated_at,
            )
        )
    return result


@router.get("/{interview_id}", response_model=schemas.MockInterviewDetailOut)
def get_mock_interview(
    interview_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Return the session including the current (unanswered) question, so an
    in-progress interview can be resumed after a page refresh."""
    interview = _owned_interview(db, current_user, interview_id)
    return _detail(interview)


@router.get("/{interview_id}/report", response_model=schemas.MockInterviewReportOut)
def get_mock_interview_report(
    interview_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Return the final report of a completed mock interview."""
    interview = _owned_interview(db, current_user, interview_id)
    report = _report_out(interview)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Report is not available until the interview is completed",
        )
    return report


@router.delete("/{interview_id}", status_code=204)
def delete_mock_interview(
    interview_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Delete the mock interview and all of its questions."""
    interview = _owned_interview(db, current_user, interview_id)
    db.delete(interview)
    db.commit()
    return None
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth import RoleChecker
from app import models, schemas
from app.services.video_interview import (
    apply_device_state,
    end_session,
)
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
from app.routes.mock_interviews import (
    _answered_out,
    _evaluation_out,
    _question_out,
)

router = APIRouter(prefix="/video-interviews", tags=["video-interviews"])

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


def _owned_session(
    db: Session, user: models.User, session_id: int
) -> models.VideoInterview:
    """Return the video interview session only if it exists and belongs to the
    candidate."""
    session = (
        db.query(models.VideoInterview)
        .filter(models.VideoInterview.id == session_id)
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=404, detail="Video interview session not found"
        )
    if session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this video interview",
        )
    return session


# ---------------------------------------------------------------------------
# Question helpers (questions live on the shared mock_interview_questions
# table, anchored via video_interview_id — same rows, same AI engine)
# ---------------------------------------------------------------------------

def _questions(session: models.VideoInterview) -> list:
    """All questions of the session, ordered by index (never None)."""
    return sorted(
        getattr(session, "questions", None) or [],
        key=lambda q: getattr(q, "question_index", 0),
    )


def _current_question(session: models.VideoInterview):
    """The first unanswered question of the session, or None."""
    return next(
        (q for q in _questions(session) if getattr(q, "answer_text", None) is None),
        None,
    )


def _answered(session: models.VideoInterview) -> list:
    return [
        q for q in _questions(session) if getattr(q, "answer_text", None) is not None
    ]


def _answered_count(session: models.VideoInterview) -> int:
    return len(_answered(session))


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _job_label(session: models.VideoInterview) -> tuple:
    application = session.application
    job = application.job if application is not None else None
    return (
        job.title if job else None,
        job.company.name if job and job.company else None,
    )


def _report_out(
    session: models.VideoInterview,
) -> schemas.MockInterviewReportOut | None:
    """The session's final report, or None when the interview is not complete."""
    if getattr(session, "status", None) != models.AssessmentStatusEnum.completed:
        return None
    if not getattr(session, "report", None):
        return None
    return schemas.MockInterviewReportOut(
        overall_score=getattr(session, "overall_score", None) or 0,
        category_scores=[
            schemas.CategoryScoreOut(**c)
            for c in (getattr(session, "category_scores", None) or [])
        ],
        strengths=getattr(session, "strengths", None) or [],
        weaknesses=getattr(session, "weaknesses", None) or [],
        recommended_topics=getattr(session, "recommended_topics", None) or [],
        summary=getattr(session, "summary", None) or "",
        generated_by=(
            "llm" if getattr(session, "report_generated_by", None) == "llm" else "fallback"
        ),
        notice=getattr(session, "report_notice", None),
    )


def _detail(session: models.VideoInterview) -> schemas.VideoInterviewDetailOut:
    job_title, company_name = _job_label(session)
    current = _current_question(session)
    report = _report_out(session)
    return schemas.VideoInterviewDetailOut(
        id=session.id,
        application_id=session.application_id,
        user_id=session.user_id,
        interview_type=getattr(session, "interview_type", None) or "technical",
        job_title=job_title,
        company_name=company_name,
        status=session.status,
        camera_enabled=bool(session.camera_enabled),
        microphone_enabled=bool(session.microphone_enabled),
        max_questions=max_questions(),
        answered_count=_answered_count(session),
        current_question=_question_out(current) if current else None,
        answered=[_answered_out(q) for q in _answered(session)],
        overall_score=report.overall_score if report else None,
        category_scores=report.category_scores if report else [],
        strengths=report.strengths if report else [],
        weaknesses=report.weaknesses if report else [],
        recommended_topics=report.recommended_topics if report else [],
        summary=report.summary if report else "",
        report_generated_by=report.generated_by if report else "fallback",
        report_notice=report.notice if report else None,
        started_at=session.started_at,
        ended_at=session.ended_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _list_out(session: models.VideoInterview) -> schemas.VideoInterviewListOut:
    job_title, company_name = _job_label(session)
    return schemas.VideoInterviewListOut(
        id=session.id,
        application_id=session.application_id,
        interview_type=getattr(session, "interview_type", None) or "technical",
        job_title=job_title,
        company_name=company_name,
        status=session.status,
        camera_enabled=bool(session.camera_enabled),
        microphone_enabled=bool(session.microphone_enabled),
        overall_score=(
            getattr(session, "overall_score", None)
            if getattr(session, "report", None)
            else None
        ),
        started_at=session.started_at,
        ended_at=session.ended_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


# ---------------------------------------------------------------------------
# Enforcement helpers
# ---------------------------------------------------------------------------

def _ensure_live(session: models.VideoInterview) -> None:
    """Raise when the session no longer accepts device-state changes."""
    if session.status != models.AssessmentStatusEnum.in_progress:
        raise HTTPException(
            status_code=400, detail="This video interview session is not in progress"
        )


# ---------------------------------------------------------------------------
# Start a video interview session
# ---------------------------------------------------------------------------

@router.post("", response_model=schemas.VideoInterviewDetailOut, status_code=201)
def start_video_interview(
    payload: schemas.VideoInterviewStartIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Open a live video interview room for one of the candidate's applications.

    ``interview_type`` selects the flavour (technical by default, or ``hr`` for
    the HR mock interview). The session state (status, camera/mic enablement,
    start timestamp) is persisted so an interrupted session can be resumed
    later. The first question of the chosen type is generated with the shared
    AI mock-interview engine and persisted against the session.
    """
    application = _owned_application(db, current_user, payload.application_id)

    existing = (
        db.query(models.VideoInterview)
        .filter(
            models.VideoInterview.application_id == application.id,
            models.VideoInterview.user_id == current_user.id,
            models.VideoInterview.interview_type == payload.interview_type,
            models.VideoInterview.status
            == models.AssessmentStatusEnum.in_progress,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A {payload.interview_type} video interview is already in "
                f"progress for this application (session {existing.id}). Resume "
                "it instead of starting a new one."
            ),
        )

    ctx = resolve_interview_context(db, current_user, application)
    total = max_questions()

    session = models.VideoInterview(
        user_id=current_user.id,
        application_id=application.id,
        status=models.AssessmentStatusEnum.in_progress,
        interview_type=payload.interview_type,
        camera_enabled=payload.camera_enabled,
        microphone_enabled=payload.microphone_enabled,
    )
    db.add(session)
    db.flush()

    first_category = category_for_index(0, payload.interview_type)
    question_result = generate_question(
        ctx, first_category, 0, total, interview_type=payload.interview_type
    )
    question = build_question_row(
        None,
        0,
        first_category,
        question_result,
        _snapshot_sources(ctx),
        video_interview_id=session.id,
    )
    db.add(question)
    db.commit()
    db.refresh(session)
    return _detail(session)


# ---------------------------------------------------------------------------
# Sync the candidate's camera/mic toggles during a live session
# ---------------------------------------------------------------------------

@router.post(
    "/{session_id}/device-state",
    response_model=schemas.VideoInterviewDetailOut,
)
def update_video_interview_device_state(
    session_id: int,
    payload: schemas.VideoInterviewDeviceStateIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Persist the current camera/microphone toggle state synced from the room."""
    session = _owned_session(db, current_user, session_id)
    _ensure_live(session)
    apply_device_state(
        session,
        camera_enabled=payload.camera_enabled,
        microphone_enabled=payload.microphone_enabled,
    )
    db.commit()
    db.refresh(session)
    return _detail(session)


# ---------------------------------------------------------------------------
# Answer the current technical question
# ---------------------------------------------------------------------------

@router.post(
    "/{session_id}/answer",
    response_model=schemas.VideoInterviewAnswerResponse,
)
def answer_video_interview_question(
    session_id: int,
    payload: schemas.VideoInterviewAnswerIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Answer the current question of the session (technical or HR flavour).
    Evaluates the answer with the shared AI mock-interview engine, persists it,
    then generates the next (adaptive) question for the session."""
    session = _owned_session(db, current_user, session_id)
    _ensure_live(session)

    question = _current_question(session)
    if question is None:
        raise HTTPException(
            status_code=400,
            detail="There are no pending questions for this video interview",
        )

    application = _owned_application(db, current_user, session.application_id)
    ctx = resolve_interview_context(db, current_user, application)

    evaluation = evaluate_answer(
        ctx,
        question.question_text,
        question.category,
        payload.answer_text,
        interview_type=session.interview_type or "technical",
    )
    apply_evaluation(question, payload.answer_text, evaluation)

    total = max_questions()
    next_question = None
    if _answered_count(session) < total:
        next_index = question.question_index + 1
        category = category_for_index(next_index, session.interview_type or "technical")
        question_result = generate_question(
            ctx,
            category,
            next_index,
            total,
            previous_answer=payload.answer_text,
            interview_type=session.interview_type or "technical",
        )
        row = build_question_row(
            None,
            next_index,
            category,
            question_result,
            _snapshot_sources(ctx),
            video_interview_id=session.id,
        )
        db.add(row)
        db.flush()
        next_question = _question_out(row)

    db.commit()
    db.refresh(session)

    return schemas.VideoInterviewAnswerResponse(
        session=_detail(session),
        evaluation=_evaluation_out(question),
        next_question=next_question,
    )


# ---------------------------------------------------------------------------
# End the video interview session (idempotent)
# ---------------------------------------------------------------------------

@router.post("/{session_id}/end", response_model=schemas.VideoInterviewDetailOut)
def end_video_interview(
    session_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """End the session and close the room. Safe to call more than once: an
    already-completed session keeps its original end timestamp.

    The first time the session is ended, the shared AI report engine produces a
    final report from the answered questions and stores it on the session."""
    session = _owned_session(db, current_user, session_id)

    if session.status == models.AssessmentStatusEnum.completed:
        db.commit()
        db.refresh(session)
        return _detail(session)

    end_session(session)

    application = _owned_application(db, current_user, session.application_id)
    ctx = resolve_interview_context(db, current_user, application)
    report = generate_report(
        ctx,
        build_qa_pairs(_answered(session)),
        interview_type=session.interview_type or "technical",
    )
    apply_report(session, report)

    db.commit()
    db.refresh(session)
    return _detail(session)


# ---------------------------------------------------------------------------
# List / detail / delete
# ---------------------------------------------------------------------------

@router.get("", response_model=list[schemas.VideoInterviewListOut])
def list_video_interviews(
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """List the candidate's video interview sessions, newest first."""
    sessions = (
        db.query(models.VideoInterview)
        .filter(models.VideoInterview.user_id == current_user.id)
        .order_by(models.VideoInterview.created_at.desc())
        .all()
    )
    return [_list_out(s) for s in sessions]


@router.get("/{session_id}", response_model=schemas.VideoInterviewDetailOut)
def get_video_interview(
    session_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Return a single video interview session for the candidate."""
    session = _owned_session(db, current_user, session_id)
    return _detail(session)


@router.delete("/{session_id}", status_code=204)
def delete_video_interview(
    session_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Delete the video interview session record."""
    session = _owned_session(db, current_user, session_id)
    db.delete(session)
    db.commit()
    return None
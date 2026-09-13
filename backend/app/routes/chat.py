# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth import RoleChecker
from app import models, schemas
from app.services.rag_chat import (
    run_chat_turn,
    resolve_chat_context,
    title_from_message,
)

router = APIRouter(prefix="/chat", tags=["chat"])

candidate_only = RoleChecker(["user"])


def _owned_application(
    db: Session, user: models.User, application_id: int
) -> models.Application:
    """Return the application only if it exists and belongs to `user`."""
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
) -> models.ChatSession:
    """Return the chat session only if it exists and belongs to `user`."""
    session = (
        db.query(models.ChatSession)
        .filter(models.ChatSession.id == session_id)
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this chat session",
        )
    return session


def _message_out(message: models.ChatMessage) -> schemas.ChatMessageOut:
    return schemas.ChatMessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        sources=[schemas.ChunkSource(**s) for s in (message.sources or [])],
        model_used=message.model_used,
        generated_by=message.generated_by,
        created_at=message.created_at,
    )


@router.post("", response_model=schemas.ChatReplyOut)
def send_chat_message(
    payload: schemas.ChatSendIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Send one candidate message and get a RAG-grounded assistant reply.

    Both the user question and the assistant reply are persisted. When
    ``application_id`` is given it must belong to the authenticated candidate;
    responses are grounded in that application's job and the candidate's latest
    resume (retrieved via the RAG index). If ``session_id`` is given the turn is
    appended to that owned session, otherwise a new session is created.
    """
    session = None
    if payload.session_id is not None:
        session = _owned_session(db, current_user, payload.session_id)

    application = None
    application_id = payload.application_id
    if application_id is None and session is not None:
        application_id = session.application_id
    if application_id is not None:
        application = _owned_application(db, current_user, application_id)

    ctx = resolve_chat_context(db, current_user, application)

    if session is None:
        session = models.ChatSession(
            user_id=current_user.id,
            application_id=application.id if application else None,
            title=None,
        )
        db.add(session)
        db.flush()

    assistant_row, _user_row, result = run_chat_turn(
        db, session, payload.message, ctx
    )
    if session.title is None:
        session.title = title_from_message(payload.message)
    db.commit()
    db.refresh(session)
    db.refresh(assistant_row)

    message = _message_out(assistant_row)
    return schemas.ChatReplyOut(
        session_id=session.id,
        application_id=session.application_id,
        message=message,
        sources=message.sources,
        generated_by=result["generated_by"],
        notice=result["notice"],
        model_used=result["model_used"],
    )


@router.get("/sessions", response_model=list[schemas.ChatSessionOut])
def list_chat_sessions(
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """List the authenticated candidate's chat sessions, newest first."""
    sessions = (
        db.query(models.ChatSession)
        .filter(models.ChatSession.user_id == current_user.id)
        .order_by(models.ChatSession.updated_at.desc())
        .all()
    )
    return [
        schemas.ChatSessionOut(
            id=s.id,
            application_id=s.application_id,
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


@router.get(
    "/sessions/{session_id}/messages", response_model=list[schemas.ChatMessageOut]
)
def get_chat_messages(
    session_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Return the persisted messages of one of the candidate's sessions."""
    session = _owned_session(db, current_user, session_id)
    return [_message_out(m) for m in (session.messages or [])]


@router.delete("/sessions/{session_id}", status_code=204)
def delete_chat_session(
    session_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Delete one of the candidate's chat sessions and its messages."""
    session = _owned_session(db, current_user, session_id)
    db.delete(session)
    db.commit()
    return None
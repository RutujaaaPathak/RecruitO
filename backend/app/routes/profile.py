# pyrefly: ignore [missing-import]
import os
import uuid
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth import get_current_user, RoleChecker
from app import models, schemas
from app.services.resume_parser import (
    MAX_FILE_BYTES,
    ResumeParseError,
    extract_text_from_bytes,
)
from app.services.resume_retriever import index_resume_chunks

router = APIRouter(tags=["profile"])

any_auth = RoleChecker(["user", "company", "admin"])

# Where uploaded resumes are stored on disk.
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "resumes"
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "txt"}


@router.get("/profile", response_model=schemas.UserOut)
def get_profile(
    current_user: models.User = Depends(any_auth),
    db: Session = Depends(get_db),
):
    """Return the currently authenticated user's own profile."""
    return current_user


@router.put("/profile", response_model=schemas.UserOut)
def update_profile(
    payload: schemas.ProfileUpdate,
    current_user: models.User = Depends(any_auth),
    db: Session = Depends(get_db),
):
    """Update the current user's profile fields."""
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/resume", response_model=schemas.ResumeOut)
def get_my_resume(
    current_user: models.User = Depends(RoleChecker(["user"])),
    db: Session = Depends(get_db),
):
    resume = (
        db.query(models.Resume)
        .filter(models.Resume.user_id == current_user.id)
        .order_by(models.Resume.uploaded_at.desc())
        .first()
    )
    if resume is None:
        raise HTTPException(status_code=404, detail="No resume uploaded yet")
    return resume


@router.post("/resume", response_model=schemas.ResumeOut, status_code=201)
def upload_resume(
    file: UploadFile = File(...),
    current_user: models.User = Depends(RoleChecker(["user"])),
    db: Session = Depends(get_db),
):
    """Candidate uploads a resume file. Newest upload replaces older scans."""
    original_filename = file.filename or "resume"
    extension = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = file.file.read()
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_BYTES // (1024 * 1024)} MB.",
        )

    # Extract and normalize the resume text. Invalid/empty files are rejected
    # before anything is written to disk.
    try:
        parsed_text = extract_text_from_bytes(content, extension)
    except ResumeParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stored_name = f"{current_user.id}_{uuid.uuid4().hex}.{extension}"
    stored_path = os.path.join(UPLOAD_DIR, stored_name)

    with open(stored_path, "wb") as f:
        f.write(content)

    resume = models.Resume(
        user_id=current_user.id,
        original_filename=original_filename,
        stored_path=stored_path,
        extension=extension,
        parsed_text=parsed_text,
    )
    db.add(resume)
    # Flush to get resume.id, then build the RAG index (chunk + embed). Indexing
    # is best-effort: if embedding/vector storage fails the upload still succeeds
    # and retrieval simply falls back to keyword scoring for these chunks.
    try:
        db.flush()
        index_resume_chunks(db, resume)
    except Exception as exc:
        logging.getLogger("recruito").warning(
            "Resume indexing failed (chunks skipped): %s", exc
        )
    db.commit()
    db.refresh(resume)
    return resume


def _delete_resume_file(resume: models.Resume) -> None:
    """Best-effort removal of a resume file from disk; never raises."""
    try:
        if resume.stored_path and os.path.exists(resume.stored_path):
            os.remove(resume.stored_path)
    except OSError:
        pass


@router.delete("/resume", status_code=204)
def delete_resume(
    current_user: models.User = Depends(RoleChecker(["user"])),
    db: Session = Depends(get_db),
):
    """Delete the candidate's most recent resume: file and database record.

    Ownership is enforced by scoping the query to the current user's id.
    """
    resume = (
        db.query(models.Resume)
        .filter(models.Resume.user_id == current_user.id)
        .order_by(models.Resume.uploaded_at.desc())
        .first()
    )
    if resume is None:
        raise HTTPException(status_code=404, detail="No resume uploaded yet")

    _delete_resume_file(resume)
    db.delete(resume)
    db.commit()
    return None

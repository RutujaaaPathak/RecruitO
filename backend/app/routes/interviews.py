# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db, get_company_for_user, require_company_approved
from app.auth import get_current_user, RoleChecker
from app import models, schemas
from app.services.notifications import create_notification

router = APIRouter(prefix="/interviews", tags=["interviews"])

company_scoped = RoleChecker(["company", "admin"])
candidate_scoped = RoleChecker(["user", "admin"])
any_auth = RoleChecker(["user", "company", "admin"])


def _enrich(interview: models.Interview) -> schemas.InterviewOut:
    job = interview.job
    applicant = interview.user
    company = job.company if job else None
    return schemas.InterviewOut(
        id=interview.id,
        application_id=interview.application_id,
        job_id=interview.job_id,
        user_id=interview.user_id,
        scheduled_at=interview.scheduled_at,
        status=interview.status,
        notes=interview.notes,
        score=interview.score,
        created_at=interview.created_at,
        job_title=job.title if job else None,
        company_name=company.name if company else None,
        applicant_name=applicant.name if applicant else None,
        applicant_email=applicant.email if applicant else None,
        applicant_phone=applicant.phone if applicant else None,
    )


def _company_can_access(
    db: Session, user: models.User, application_id: int
) -> bool:
    """True if the company user owns the job associated with this application."""
    if user.role == models.RoleEnum.admin:
        return True
    if user.role != models.RoleEnum.company:
        return False
    company = (
        db.query(models.Company)
        .filter(models.Company.user_id == user.id)
        .first()
    )
    if company is None:
        return False
    application = (
        db.query(models.Application)
        .filter(models.Application.id == application_id)
        .first()
    )
    if application is None:
        return False
    return application.job.company_id == company.id


def _candidate_can_access(
    db: Session, user: models.User, application_id: int
) -> bool:
    """True if the candidate owns the application for this interview."""
    if user.role == models.RoleEnum.admin:
        return True
    if user.role != models.RoleEnum.user:
        return False
    application = (
        db.query(models.Application)
        .filter(
            models.Application.id == application_id,
            models.Application.user_id == user.id,
        )
        .first()
    )
    return application is not None


# ── Company: schedule interview ──────────────────────────────────────────


@router.post("", response_model=schemas.InterviewOut, status_code=201)
def create_interview(
    payload: schemas.InterviewCreate,
    current_user: models.User = Depends(RoleChecker(["company"])),
    db: Session = Depends(get_db),
):
    """Company schedules an interview for a candidate's application."""
    if current_user.role == models.RoleEnum.company:
        company = (
            db.query(models.Company)
            .filter(models.Company.user_id == current_user.id)
            .first()
        )
        if company is not None:
            require_company_approved(company)

    application = (
        db.query(models.Application)
        .filter(models.Application.id == payload.application_id)
        .first()
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    if not _company_can_access(db, current_user, payload.application_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to schedule interviews for this application",
        )

    existing = (
        db.query(models.Interview)
        .filter(models.Interview.application_id == payload.application_id)
        .first()
    )
    if existing is not None:
        if existing.status == models.InterviewStatusEnum.cancelled:
            # Allow rescheduling: delete the cancelled interview first
            db.delete(existing)
            db.flush()
        else:
            raise HTTPException(
                status_code=409,
                detail="An interview already exists for this application",
            )

    interview = models.Interview(
        application_id=application.id,
        job_id=application.job_id,
        user_id=application.user_id,
        scheduled_at=payload.scheduled_at,
        status=models.InterviewStatusEnum.scheduled,
        notes=payload.notes,
    )
    db.add(interview)

    # Update application status to shortlisted when interview is scheduled
    application.status = models.ApplicationStatusEnum.shortlisted

    # Notify the candidate that their interview has been scheduled.
    job = (
        db.query(models.Job).filter(models.Job.id == interview.job_id).first()
    )
    create_notification(
        db,
        application.user_id,
        type=models.NotificationType.interview,
        title="Interview Scheduled",
        message=(
            f"Your interview for {job.title if job else 'this position'} has "
            "been scheduled."
        ),
        link="/dashboard/interview",
    )

    db.commit()
    db.refresh(interview)
    return _enrich(interview)


# ── Company: list interviews for their jobs ───────────────────────────────


@router.get("", response_model=list[schemas.InterviewOut])
def list_interviews(
    current_user: models.User = Depends(any_auth),
    db: Session = Depends(get_db),
):
    if current_user.role == models.RoleEnum.company:
        company = (
            db.query(models.Company)
            .filter(models.Company.user_id == current_user.id)
            .first()
        )
        if company is None:
            return []
        job_ids = [j.id for j in company.jobs]
        interviews = (
            db.query(models.Interview)
            .filter(models.Interview.job_id.in_(job_ids))
            .order_by(models.Interview.created_at.desc())
            .all()
        )
    elif current_user.role == models.RoleEnum.user:
        interviews = (
            db.query(models.Interview)
            .filter(models.Interview.user_id == current_user.id)
            .order_by(models.Interview.created_at.desc())
            .all()
        )
    else:
        interviews = (
            db.query(models.Interview)
            .order_by(models.Interview.created_at.desc())
            .all()
        )
    return [_enrich(i) for i in interviews]


# ── Get interview detail ──────────────────────────────────────────────────


@router.get("/{interview_id}", response_model=schemas.InterviewOut)
def get_interview(
    interview_id: int,
    current_user: models.User = Depends(any_auth),
    db: Session = Depends(get_db),
):
    interview = (
        db.query(models.Interview)
        .filter(models.Interview.id == interview_id)
        .first()
    )
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    if current_user.role == models.RoleEnum.company:
        if not _company_can_access(db, current_user, interview.application_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this interview",
            )
    elif current_user.role == models.RoleEnum.user:
        if not _candidate_can_access(db, current_user, interview.application_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this interview",
            )

    return _enrich(interview)


# ── Company/Admin: update interview ──────────────────────────────────────


@router.put("/{interview_id}", response_model=schemas.InterviewOut)
def update_interview(
    interview_id: int,
    payload: schemas.InterviewUpdate,
    current_user: models.User = Depends(RoleChecker(["company", "admin"])),
    db: Session = Depends(get_db),
):
    interview = (
        db.query(models.Interview)
        .filter(models.Interview.id == interview_id)
        .first()
    )
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    if current_user.role != models.RoleEnum.admin:
        if not _company_can_access(db, current_user, interview.application_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update this interview",
            )

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(interview, field, value)

    # Update application status when interview is completed or cancelled
    application = (
        db.query(models.Application)
        .filter(models.Application.id == interview.application_id)
        .first()
    )
    if application is not None:
        if interview.status == models.InterviewStatusEnum.completed:
            application.status = models.ApplicationStatusEnum.interviewed
        elif interview.status == models.InterviewStatusEnum.cancelled:
            application.status = models.ApplicationStatusEnum.applied

    # Notify the candidate when the interview is completed or cancelled.
    if (
        application is not None
        and interview.status
        in (models.InterviewStatusEnum.completed, models.InterviewStatusEnum.cancelled)
    ):
        job = (
            db.query(models.Job)
            .filter(models.Job.id == interview.job_id)
            .first()
        )
        create_notification(
            db,
            application.user_id,
            type=models.NotificationType.interview,
            title=(
                "Interview Completed"
                if interview.status == models.InterviewStatusEnum.completed
                else "Interview Cancelled"
            ),
            message=(
                f"Your interview for {job.title if job else 'this position'} "
                "has been completed."
                if interview.status == models.InterviewStatusEnum.completed
                else f"Your interview for {job.title if job else 'this position'} "
                "has been cancelled."
            ),
            link="/dashboard/interview",
        )

    db.commit()
    db.refresh(interview)
    return _enrich(interview)

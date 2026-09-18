# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth import get_current_user, RoleChecker
from app import models, schemas

router = APIRouter(prefix="/admin", tags=["admin"])

admin_scoped = RoleChecker(["admin"])


class UserAdminUpdate(schemas.BaseModel):
    is_active: bool | None = None
    role: models.RoleEnum | None = None
    name: str | None = None


# -----------------------------
# Users
# -----------------------------
@router.get("/users", response_model=list[schemas.UserOut])
def list_users(
    current_user: models.User = Depends(admin_scoped),
    db: Session = Depends(get_db),
):
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@router.put("/users/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: UserAdminUpdate,
    current_user: models.User = Depends(admin_scoped),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump(exclude_unset=True)
    new_role = data.get("role", user.role)
    new_active = data.get("is_active", user.is_active)
    removes_active_admin = (
        user.role == models.RoleEnum.admin
        and user.is_active is True
        and not (new_role == models.RoleEnum.admin and new_active is True)
    )
    if removes_active_admin:
        remaining_active_admins = (
            db.query(models.User)
            .filter(models.User.role == models.RoleEnum.admin)
            .filter(models.User.is_active.is_(True))
            .filter(models.User.id != user_id)
            .count()
        )
        if remaining_active_admins == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot demote or deactivate the last active admin",
            )

    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


# -----------------------------
# Companies
# -----------------------------
@router.get("/companies", response_model=list[schemas.CompanyOut])
def list_companies(
    current_user: models.User = Depends(admin_scoped),
    db: Session = Depends(get_db),
):
    return db.query(models.Company).order_by(models.Company.created_at.desc()).all()


@router.put("/companies/{company_id}/approval")
def set_company_approval(
    company_id: int,
    approved: bool,
    current_user: models.User = Depends(admin_scoped),
    db: Session = Depends(get_db),
):
    company = (
        db.query(models.Company).filter(models.Company.id == company_id).first()
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    company.approved = approved
    db.commit()
    db.refresh(company)
    return schemas.CompanyOut.model_validate(company)


# -----------------------------
# Jobs
# -----------------------------
@router.get("/jobs")
def list_all_jobs(
    current_user: models.User = Depends(admin_scoped),
    db: Session = Depends(get_db),
):
    jobs = db.query(models.Job).order_by(models.Job.posted_on.desc()).all()
    return [
        {
            "id": j.id,
            "title": j.title,
            "company_name": j.company.name if j.company else None,
            "status": j.status.value,
            "applicants": len(j.applications),
            "posted_on": j.posted_on,
        }
        for j in jobs
    ]


# -----------------------------
# Applications
# -----------------------------
@router.get("/applications")
def list_all_applications(
    current_user: models.User = Depends(admin_scoped),
    db: Session = Depends(get_db),
):
    applications = (
        db.query(models.Application)
        .order_by(models.Application.created_at.desc())
        .all()
    )
    return [
        {
            "id": a.id,
            "job_title": a.job.title if a.job else None,
            "applicant_name": a.user.name if a.user else None,
            "status": a.status.value,
            "match_score": a.match_score,
            "created_at": a.created_at,
        }
        for a in applications
    ]


# -----------------------------
# Statistics
# -----------------------------
@router.get("/stats")
def system_stats(
    current_user: models.User = Depends(admin_scoped),
    db: Session = Depends(get_db),
):
    return {
        "total_users": db.query(models.User).count(),
        "total_companies": db.query(models.Company).count(),
        "total_jobs": db.query(models.Job).count(),
        "open_jobs": db.query(models.Job)
        .filter(models.Job.status == models.JobStatusEnum.open)
        .count(),
        "total_applications": db.query(models.Application).count(),
        "total_resumes": db.query(models.Resume).count(),
        "total_interviews": db.query(models.Interview).count(),
    }

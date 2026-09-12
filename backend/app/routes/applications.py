# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth import get_current_user, RoleChecker
from app import models, schemas
from app.services.resume_parser import compute_match_score
from app.services.skill_gap import analyze_skill_gap
from app.services.semantic_matcher import compute_semantic_score
from app.services.career_recommendations import generate_career_recommendations
from app.services.resume_retriever import retrieve_chunks_for_job

router = APIRouter(prefix="/applications", tags=["applications"])

company_scoped = RoleChecker(["company", "admin"])
any_auth = RoleChecker(["user", "company", "admin"])


def _enrich(application: models.Application) -> schemas.ApplicationOut:
    job = application.job
    applicant = application.user
    return schemas.ApplicationOut(
        id=application.id,
        job_id=application.job_id,
        user_id=application.user_id,
        status=application.status,
        match_score=application.match_score,
        created_at=application.created_at,
        job_title=job.title if job else None,
        company_name=job.company.name if job and job.company else None,
        applicant_name=applicant.name if applicant else None,
        applicant_email=applicant.email if applicant else None,
        applicant_phone=applicant.phone if applicant else None,
        applicant_skills=applicant.skills if applicant else None,
    )


def _can_manage(db: Session, app_: models.Application, user: models.User) -> bool:
    """True if the user (admin, or owning company) may manage this application."""
    if user.role == models.RoleEnum.admin:
        return True
    if user.role == models.RoleEnum.company:
        company = (
            db.query(models.Company)
            .filter(models.Company.user_id == user.id)
            .first()
        )
        return company is not None and app_.job.company_id == company.id
    # Candidate can manage (withdraw) their own application
    return app_.user_id == user.id


@router.post("", response_model=schemas.ApplicationOut, status_code=201)
def create_application(
    payload: schemas.ApplicationCreate,
    current_user: models.User = Depends(RoleChecker(["user"])),
    db: Session = Depends(get_db),
):
    """Candidate applies to a job."""
    job = db.query(models.Job).filter(models.Job.id == payload.job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != models.JobStatusEnum.open:
        raise HTTPException(status_code=400, detail="This job is no longer open")

    duplicate = (
        db.query(models.Application)
        .filter(
            models.Application.job_id == job.id,
            models.Application.user_id == current_user.id,
        )
        .first()
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409, detail="You have already applied to this job"
        )

    # Compute the rule-based ATS match score from the candidate's most recent
    # resume text compared against the job's required skills and description.
    match_score = None
    resume = (
        db.query(models.Resume)
        .filter(models.Resume.user_id == current_user.id)
        .order_by(models.Resume.uploaded_at.desc())
        .first()
    )
    if resume is not None and resume.parsed_text:
        match_score = compute_match_score(
            resume.parsed_text,
            job.skills or [],
            job.description,
        )

    application = models.Application(
        job_id=job.id,
        user_id=current_user.id,
        status=models.ApplicationStatusEnum.applied,
        match_score=match_score,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return _enrich(application)


@router.get("", response_model=list[schemas.ApplicationOut])
def list_applications(
    current_user: models.User = Depends(any_auth),
    db: Session = Depends(get_db),
):
    if current_user.role == models.RoleEnum.user:
        query = db.query(models.Application).filter(
            models.Application.user_id == current_user.id
        )
    elif current_user.role == models.RoleEnum.company:
        company = (
            db.query(models.Company)
            .filter(models.Company.user_id == current_user.id)
            .first()
        )
        if company is None:
            return []
        job_ids = [j.id for j in company.jobs]
        query = db.query(models.Application).filter(
            models.Application.job_id.in_(job_ids)
        ) if job_ids else db.query(models.Application).filter(False)
    else:
        query = db.query(models.Application)

    applications = query.order_by(models.Application.created_at.desc()).all()
    return [_enrich(a) for a in applications]


@router.get("/{application_id}", response_model=schemas.ApplicationOut)
def get_application(
    application_id: int,
    current_user: models.User = Depends(any_auth),
    db: Session = Depends(get_db),
):
    app_ = (
        db.query(models.Application)
        .filter(models.Application.id == application_id)
        .first()
    )
    if app_ is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if not _can_manage(db, app_, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this application",
        )
    return _enrich(app_)


@router.get("/{application_id}/skill-gap", response_model=schemas.SkillGapReport)
def get_application_skill_gap(
    application_id: int,
    current_user: models.User = Depends(any_auth),
    db: Session = Depends(get_db),
):
    """Rule-based skill gap report for an application (no LLM).

    Compares the candidate's most recent resume against the job's required
    skills using the same vocabulary/normalization as the ATS matcher. The
    report is available to the candidate who owns the application and to the
    hiring company / admin who manages it.
    """
    app_ = (
        db.query(models.Application)
        .filter(models.Application.id == application_id)
        .first()
    )
    if app_ is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if not _can_manage(db, app_, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this application",
        )

    resume = (
        db.query(models.Resume)
        .filter(models.Resume.user_id == app_.user_id)
        .order_by(models.Resume.uploaded_at.desc())
        .first()
    )
    if resume is None or not resume.parsed_text:
        raise HTTPException(
            status_code=404, detail="No resume available for skill gap analysis"
        )

    report = analyze_skill_gap(resume.parsed_text, app_.job.skills or [], app_.job.description)

    return schemas.SkillGapReport(
        application_id=app_.id,
        job_id=app_.job_id,
        job_title=app_.job.title if app_.job else None,
        company_name=(
            app_.job.company.name if app_.job and app_.job.company else None
        ),
        required_skills=report.required_skills,
        matched_skills=report.matched_skills,
        missing_skills=[
            schemas.SkillGapItem(skill=i.skill, recommendation=i.recommendation)
            for i in report.missing_skills
        ],
        matched_count=report.matched_count,
        missing_count=report.missing_count,
        coverage_percent=report.coverage_percent,
        summary=report.summary,
    )


@router.get("/{application_id}/semantic-match", response_model=schemas.SemanticMatchOut)
def get_application_semantic_match(
    application_id: int,
    current_user: models.User = Depends(any_auth),
    db: Session = Depends(get_db),
):
    """Semantic (embedding) similarity between a resume and a job description.

    Uses Sentence Transformers embeddings + cosine similarity to complement the
    rule-based ATS score. The existing `match_score` is returned UNCHANGED; the
    new `semantic_score` is an independent signal. Available to the candidate
    who owns the application and to the hiring company / admin who manages it.
    """
    app_ = (
        db.query(models.Application)
        .filter(models.Application.id == application_id)
        .first()
    )
    if app_ is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if not _can_manage(db, app_, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this application",
        )

    resume = (
        db.query(models.Resume)
        .filter(models.Resume.user_id == app_.user_id)
        .order_by(models.Resume.uploaded_at.desc())
        .first()
    )
    if resume is None or not resume.parsed_text:
        raise HTTPException(
            status_code=404, detail="No resume available for semantic matching"
        )

    result = compute_semantic_score(resume.parsed_text, app_.job.description)

    return schemas.SemanticMatchOut(
        application_id=app_.id,
        job_id=app_.job_id,
        job_title=app_.job.title if app_.job else None,
        company_name=(
            app_.job.company.name if app_.job and app_.job.company else None
        ),
        candidate_name=app_.user.name if app_.user else None,
        match_score=app_.match_score,
        semantic_score=result.score,
        cosine_similarity=result.cosine_similarity,
        embedding_model=result.embedding_model,
        used_fallback=result.used_fallback,
        explanation=result.explanation,
    )


@router.get("/{application_id}/retrieved-chunks", response_model=schemas.RetrievedChunksOut)
def get_application_retrieved_chunks(
    application_id: int,
    current_user: models.User = Depends(any_auth),
    db: Session = Depends(get_db),
):
    """Retrieve the resume chunks most relevant to an application's job.

    Uses pgvector cosine-distance retrieval over the candidate's latest resume.
    Falls back silently to keyword scoring when embeddings are unavailable
    (model offline / chunks not indexed). Access is scoped to the candidate who
    owns the application and the hiring company / admin who manages it.
    """
    app_ = (
        db.query(models.Application)
        .filter(models.Application.id == application_id)
        .first()
    )
    if app_ is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if not _can_manage(db, app_, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this application",
        )

    resume = (
        db.query(models.Resume)
        .filter(models.Resume.user_id == app_.user_id)
        .order_by(models.Resume.uploaded_at.desc())
        .first()
    )
    if resume is None or not resume.parsed_text:
        raise HTTPException(
            status_code=404, detail="No resume available for retrieval"
        )

    chunks, model_used, used_fallback = retrieve_chunks_for_job(
        db, resume, app_.job.description or ""
    )

    return schemas.RetrievedChunksOut(
        application_id=app_.id,
        job_id=app_.job_id,
        job_title=app_.job.title if app_.job else None,
        company_name=(
            app_.job.company.name if app_.job and app_.job.company else None
        ),
        model_used=model_used,
        used_fallback=used_fallback,
        chunks=[
            schemas.RetrievedChunkOut(
                chunk_id=c.chunk_id,
                chunk_index=c.chunk_index,
                section=c.section,
                score=c.score,
                content=c.content,
            )
            for c in chunks
        ],
    )


@router.get("/{application_id}/career-recommendations", response_model=schemas.CareerRecommendationsOut)
def get_career_recommendations(
    application_id: int,
    current_user: models.User = Depends(any_auth),
    db: Session = Depends(get_db),
):
    """Personalized AI career recommendations for an application.

    Combines the existing rule-based analysis (matched/missing skills from the
    skill-gap analyzer, the stored ATS score, and a freshly computed semantic
    score) with a backend-only LLM call to produce a structured career plan.

    The LLM API key is read from the backend environment and is never exposed.
    If the LLM is unavailable, the endpoint returns a validated rule-based
    fallback plan (generated_by="fallback") so callers always get structured
    JSON. Available to the candidate who owns the application and to the hiring
    company / admin who manages it.
    """
    app_ = (
        db.query(models.Application)
        .filter(models.Application.id == application_id)
        .first()
    )
    if app_ is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if not _can_manage(db, app_, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this application",
        )

    resume = (
        db.query(models.Resume)
        .filter(models.Resume.user_id == app_.user_id)
        .order_by(models.Resume.uploaded_at.desc())
        .first()
    )
    if resume is None or not resume.parsed_text:
        raise HTTPException(
            status_code=404, detail="No resume available for career recommendations"
        )

    semantic_score = None
    if app_.job.description:
        semantic_score = compute_semantic_score(
            resume.parsed_text, app_.job.description
        ).score

    retrieved_chunks, _, _ = retrieve_chunks_for_job(
        db, resume, app_.job.description or ""
    )

    plan = generate_career_recommendations(
        resume_text=resume.parsed_text,
        job_skills=app_.job.skills or [],
        job_description=app_.job.description,
        job_title=app_.job.title if app_.job else None,
        ats_score=app_.match_score,
        semantic_score=semantic_score,
        retrieved_chunks=retrieved_chunks,
    )

    return schemas.CareerRecommendationsOut(
        application_id=app_.id,
        job_id=app_.job_id,
        job_title=app_.job.title if app_.job else None,
        company_name=(
            app_.job.company.name if app_.job and app_.job.company else None
        ),
        ats_score=app_.match_score,
        semantic_score=semantic_score,
        matched_skills=plan.get("matched_skills", []),
        missing_skills=plan.get("missing_skills", []),
        summary=plan.get("summary", ""),
        priority_skills=plan.get("priority_skills", []),
        learning_path=plan.get("learning_path", []),
        project_ideas=plan.get("project_ideas", []),
        resume_improvements=plan.get("resume_improvements", []),
        generated_by=plan.get("generated_by", "fallback"),
        notice=plan.get("notice"),
        sources=[schemas.ChunkSource(**s) for s in plan.get("sources", [])],
    )


@router.put("/{application_id}", response_model=schemas.ApplicationOut)
def update_application(
    application_id: int,
    payload: schemas.ApplicationUpdate,
    current_user: models.User = Depends(any_auth),
    db: Session = Depends(get_db),
):
    app_ = (
        db.query(models.Application)
        .filter(models.Application.id == application_id)
        .first()
    )
    if app_ is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if not _can_manage(db, app_, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this application",
        )

    # A candidate may only withdraw their own application.
    if (
        current_user.role == models.RoleEnum.user
        and payload.status != models.ApplicationStatusEnum.withdrawn
    ):
        raise HTTPException(
            status_code=403,
            detail="Candidates may only withdraw their own application",
        )

    app_.status = payload.status
    db.commit()
    db.refresh(app_)
    return _enrich(app_)

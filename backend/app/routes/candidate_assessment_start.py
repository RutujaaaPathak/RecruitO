# pyrefly: ignore [missing-import]
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.deps import get_db
from app import models, schemas
from app.routes.candidate_assessments import _my_assignment, candidate_only

router = APIRouter(prefix="/me/assessments", tags=["candidate-assessment-start"])


def _deadline_at(
    assessment: models.Assessment, started_at: datetime
) -> datetime | None:
    """The moment the candidate's attempt ends: the earlier of the configured
    window end and start + duration."""
    deadline = (
        started_at + timedelta(minutes=assessment.duration_minutes)
        if assessment.duration_minutes
        else None
    )
    if assessment.ends_at is not None and (
        deadline is None or assessment.ends_at < deadline
    ):
        return assessment.ends_at
    return deadline


def _question_out(
    q: models.AssessmentQuestion,
) -> schemas.CandidateAssessmentQuestionOut:
    """Serialize one question to its candidate-safe form.

    correct_index, hidden_cases, marks and explanation are deliberately never
    copied onto the candidate contract.
    """
    return schemas.CandidateAssessmentQuestionOut(
        id=q.id,
        question_type=q.question_type,
        question_text=q.question_text,
        question_order=q.question_order,
        options=q.options,
        title=q.title,
        category=q.category,
        difficulty=q.difficulty,
        input_format=q.input_format,
        output_format=q.output_format,
        constraints=q.constraints,
        sample_cases=q.sample_cases,
        time_limit_seconds=q.time_limit_seconds,
        supported_languages=q.supported_languages,
    )


def _sections_out(
    db: Session, assessment_id: int
) -> list[schemas.CandidateAssessmentSectionDetailOut]:
    """Ordered sections, each with its questions in their configured order."""
    sections = (
        db.query(models.AssessmentSection)
        .filter(models.AssessmentSection.assessment_id == assessment_id)
        .order_by(models.AssessmentSection.section_order)
        .all()
    )
    out: list[schemas.CandidateAssessmentSectionDetailOut] = []
    for section in sections:
        questions = (
            db.query(models.AssessmentQuestion)
            .filter(models.AssessmentQuestion.section_id == section.id)
            .order_by(models.AssessmentQuestion.question_order)
            .all()
        )
        out.append(
            schemas.CandidateAssessmentSectionDetailOut(
                id=section.id,
                section_type=section.section_type,
                title=section.title,
                section_order=section.section_order,
                questions=[_question_out(q) for q in questions],
            )
        )
    return out


@router.post(
    "/{assessment_id}/start",
    response_model=schemas.CandidateAssessmentStartOut,
)
def start_my_assessment(
    assessment_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Start the candidate's assigned assessment.

    The existing ``assessment_assignments`` row is the attempt/session: it is
    atomically transitioned ``assigned → in_progress`` (started_at recorded)
    only if it is still ``assigned``, so two simultaneous start requests can
    never create two active attempts — exactly one wins. The response carries
    the candidate-safe assessment content (title, instructions, ordered
    sections/questions, duration, start/deadline).
    """
    assignment = _my_assignment(db, current_user, assessment_id)
    assessment = assignment.assessment

    if assessment.status != models.CompanyAssessmentStatusEnum.published:
        raise HTTPException(
            status_code=400,
            detail="Assessment is not currently available",
        )

    now = datetime.utcnow()
    if assessment.starts_at is not None and now < assessment.starts_at:
        raise HTTPException(
            status_code=400,
            detail="Assessment has not started yet",
        )
    if assessment.ends_at is not None and now > assessment.ends_at:
        raise HTTPException(
            status_code=400,
            detail="Assessment window has ended",
        )
    if (
        assessment.duration_minutes is not None
        and assessment.ends_at is not None
        and now + timedelta(minutes=assessment.duration_minutes)
        > assessment.ends_at
    ):
        raise HTTPException(
            status_code=400,
            detail="Not enough time remaining to complete the assessment",
        )

    if assignment.status == models.AssessmentAssignmentStatusEnum.submitted:
        raise HTTPException(
            status_code=409, detail="Assessment has already been submitted"
        )
    if assignment.status == models.AssessmentAssignmentStatusEnum.in_progress:
        raise HTTPException(
            status_code=409, detail="Assessment has already been started"
        )

    # Atomic guard: the transition succeeds only if the row is still 'assigned'.
    # A concurrent request that already started/submitted the assessment makes
    # this update match zero rows, so a duplicate attempt can never be created.
    started_at = now
    result = db.execute(
        update(models.AssessmentAssignment)
        .where(
            models.AssessmentAssignment.id == assignment.id,
            models.AssessmentAssignment.status
            == models.AssessmentAssignmentStatusEnum.assigned,
        )
        .values(
            status=models.AssessmentAssignmentStatusEnum.in_progress,
            started_at=started_at,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        db.rollback()
        db.expire_all()
        current = db.get(models.AssessmentAssignment, assignment.id)
        if current is None:
            raise HTTPException(status_code=404, detail="Assessment not found")
        if current.status == models.AssessmentAssignmentStatusEnum.submitted:
            raise HTTPException(
                status_code=409, detail="Assessment has already been submitted"
            )
        raise HTTPException(
            status_code=409, detail="Assessment has already been started"
        )
    db.commit()
    db.refresh(assignment)

    return schemas.CandidateAssessmentStartOut(
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
    )
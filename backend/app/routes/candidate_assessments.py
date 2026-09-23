# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth import RoleChecker
from app import models, schemas

router = APIRouter(prefix="/me/assessments", tags=["candidate-assessments"])

candidate_only = RoleChecker(["user"])


def _my_assignment(
    db: Session, user: models.User, assessment_id: int
) -> models.AssessmentAssignment:
    """Return the candidate's own assignment for an assessment.

    Scoped to the authenticated candidate: an unknown, unassigned, deleted or
    another candidate's assessment is all indistinguishable (404), so another
    candidate's assignment can never be reached by changing an id.
    """
    assignment = (
        db.query(models.AssessmentAssignment)
        .filter(
            models.AssessmentAssignment.assessment_id == assessment_id,
            models.AssessmentAssignment.candidate_id == user.id,
        )
        .first()
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return assignment


def _candidate_out(
    assignment: models.AssessmentAssignment,
    assessment: models.Assessment,
    company: models.Company,
) -> schemas.CandidateAssessmentAssignmentOut:
    return schemas.CandidateAssessmentAssignmentOut(
        id=assignment.id,
        assessment_id=assignment.assessment_id,
        title=assessment.title,
        description=assessment.description,
        instructions=assessment.instructions,
        company_name=company.name,
        duration_minutes=assessment.duration_minutes,
        starts_at=assessment.starts_at,
        ends_at=assessment.ends_at,
        status=assignment.status,
        assigned_at=assignment.assigned_at,
        started_at=assignment.started_at,
        submitted_at=assignment.submitted_at,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _sections_out(
    db: Session, assessment_id: int
) -> list[schemas.CandidateAssessmentSectionOut]:
    sections = (
        db.query(models.AssessmentSection)
        .filter(models.AssessmentSection.assessment_id == assessment_id)
        .order_by(models.AssessmentSection.section_order)
        .all()
    )
    return [
        schemas.CandidateAssessmentSectionOut(
            id=s.id,
            section_type=s.section_type,
            title=s.title,
            section_order=s.section_order,
        )
        for s in sections
    ]


@router.get("", response_model=list[schemas.CandidateAssessmentAssignmentOut])
def list_my_assessments(
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """List the candidate's assigned company assessments, newest first."""
    rows = (
        db.query(models.AssessmentAssignment, models.Assessment, models.Company)
        .join(
            models.Assessment,
            models.AssessmentAssignment.assessment_id == models.Assessment.id,
        )
        .join(models.Company, models.Assessment.company_id == models.Company.id)
        .filter(models.AssessmentAssignment.candidate_id == current_user.id)
        .order_by(models.AssessmentAssignment.assigned_at.desc())
        .all()
    )
    return [_candidate_out(a, assessment, company) for a, assessment, company in rows]


@router.get(
    "/{assessment_id}/assignment",
    response_model=schemas.CandidateAssessmentAssignmentOut,
)
def get_my_assignment(
    assessment_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """The candidate's own assignment status + timestamps for one assessment."""
    assignment = _my_assignment(db, current_user, assessment_id)
    return _candidate_out(assignment, assignment.assessment, assignment.assessment.company)


@router.get(
    "/{assessment_id}",
    response_model=schemas.CandidateAssessmentAssignmentDetailOut,
)
def get_my_assessment(
    assessment_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Details of one assigned assessment: description, instructions, company,
    duration, scheduled window, assignment status/timestamps, and sections in
    their configured order."""
    assignment = _my_assignment(db, current_user, assessment_id)
    return schemas.CandidateAssessmentAssignmentDetailOut(
        **_candidate_out(
            assignment, assignment.assessment, assignment.assessment.company
        ).model_dump(),
        sections=_sections_out(db, assessment_id),
    )
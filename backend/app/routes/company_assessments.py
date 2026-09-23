# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db, get_company_for_user, require_company_approved
from app.auth import RoleChecker
from app import models, schemas
from app.services.notifications import create_notification

router = APIRouter(prefix="/assessments", tags=["company-assessments"])

company_scoped = RoleChecker(["company", "admin"])


# ---------------------------------------------------------------------------
# Ownership guards
# ---------------------------------------------------------------------------

def _owned_assessment(
    db: Session, user: models.User, assessment_id: int
) -> models.Assessment:
    """Return the assessment only if it exists and belongs to the company.

    company_id is always derived from the authenticated user (never from the
    client). Admins may manage any company's assessment.
    """
    assessment = (
        db.query(models.Assessment)
        .filter(models.Assessment.id == assessment_id)
        .first()
    )
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if user.role != models.RoleEnum.admin:
        company = (
            db.query(models.Company)
            .filter(models.Company.user_id == user.id)
            .first()
        )
        if company is None or assessment.company_id != company.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this assessment",
            )
    return assessment


def _owned_section(
    db: Session, assessment: models.Assessment, section_id: int
) -> models.AssessmentSection:
    """Return the section only if it belongs to the (already owned) assessment."""
    section = (
        db.query(models.AssessmentSection)
        .filter(
            models.AssessmentSection.id == section_id,
            models.AssessmentSection.assessment_id == assessment.id,
        )
        .first()
    )
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    return section


def _section_orders(
    db: Session, assessment_id: int
) -> list[int]:
    """The section orders currently used by an assessment."""
    return [
        s.section_order
        for s in (
            db.query(models.AssessmentSection)
            .filter(models.AssessmentSection.assessment_id == assessment_id)
            .all()
        )
    ]


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _out(assessment: models.Assessment) -> schemas.AssessmentOut:
    return schemas.AssessmentOut(
        id=assessment.id,
        company_id=assessment.company_id,
        title=assessment.title,
        description=assessment.description,
        instructions=assessment.instructions,
        status=assessment.status,
        duration_minutes=assessment.duration_minutes,
        starts_at=assessment.starts_at,
        ends_at=assessment.ends_at,
        created_at=assessment.created_at,
        updated_at=assessment.updated_at,
    )


def _detail_out(
    db: Session, assessment: models.Assessment
) -> schemas.AssessmentDetailOut:
    sections = (
        db.query(models.AssessmentSection)
        .filter(models.AssessmentSection.assessment_id == assessment.id)
        .order_by(models.AssessmentSection.section_order)
        .all()
    )
    assignments = (
        db.query(models.AssessmentAssignment)
        .filter(models.AssessmentAssignment.assessment_id == assessment.id)
        .order_by(models.AssessmentAssignment.id)
        .all()
    )
    return schemas.AssessmentDetailOut(
        **_out(assessment).model_dump(),
        sections=[schemas.AssessmentSectionOut.model_validate(s) for s in sections],
        assignments=[
            schemas.AssessmentAssignmentOut.model_validate(a) for a in assignments
        ],
    )


# ---------------------------------------------------------------------------
# Assessment CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=schemas.AssessmentOut, status_code=201)
def create_assessment(
    payload: schemas.AssessmentCreate,
    current_user: models.User = Depends(RoleChecker(["company"])),
    db: Session = Depends(get_db),
):
    """Company creates an assessment (draft by default)."""
    company = get_company_for_user(db, current_user)
    require_company_approved(company)
    assessment = models.Assessment(
        company_id=company.id,
        title=payload.title,
        description=payload.description,
        instructions=payload.instructions,
        status=payload.status or models.CompanyAssessmentStatusEnum.draft,
        duration_minutes=payload.duration_minutes,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return _out(assessment)


@router.get("", response_model=list[schemas.AssessmentOut])
def list_assessments(
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """List the authenticated company's assessments (admins see all)."""
    query = db.query(models.Assessment)
    if current_user.role != models.RoleEnum.admin:
        company = (
            db.query(models.Company)
            .filter(models.Company.user_id == current_user.id)
            .first()
        )
        if company is None:
            return []
        query = query.filter(models.Assessment.company_id == company.id)
    assessments = query.order_by(models.Assessment.created_at.desc()).all()
    return [_out(a) for a in assessments]


@router.get("/{assessment_id}", response_model=schemas.AssessmentDetailOut)
def get_assessment(
    assessment_id: int,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Get one of the company's assessments including its ordered sections."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    return _detail_out(db, assessment)


@router.put("/{assessment_id}", response_model=schemas.AssessmentOut)
def update_assessment(
    assessment_id: int,
    payload: schemas.AssessmentUpdate,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Update an assessment the company owns."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(assessment, field, value)
    db.commit()
    db.refresh(assessment)
    return _out(assessment)


@router.delete("/{assessment_id}", status_code=204)
def delete_assessment(
    assessment_id: int,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Delete an assessment the company owns (sections/assignments cascade)."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    db.delete(assessment)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Section management
# ---------------------------------------------------------------------------

@router.post(
    "/{assessment_id}/sections",
    response_model=schemas.AssessmentSectionOut,
    status_code=201,
)
def add_section(
    assessment_id: int,
    payload: schemas.AssessmentSectionCreate,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Add a section to an assessment, preventing duplicate section ordering."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    orders = _section_orders(db, assessment.id)
    section_order = payload.section_order if payload.section_order is not None else (
        (max(orders) + 1) if orders else 1
    )
    if section_order in orders:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A section with this section_order already exists",
        )
    section = models.AssessmentSection(
        assessment_id=assessment.id,
        section_type=payload.section_type,
        title=payload.title,
        section_order=section_order,
        marks=payload.marks,
        settings=payload.settings,
    )
    db.add(section)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A section with this section_order already exists",
        )
    db.refresh(section)
    return schemas.AssessmentSectionOut.model_validate(section)


# Declared before "/sections/{section_id}" so the literal "reorder" suffix
# matches reliably.
@router.put(
    "/{assessment_id}/sections/reorder",
    response_model=list[schemas.AssessmentSectionOut],
)
def reorder_sections(
    assessment_id: int,
    payload: schemas.AssessmentSectionReorderIn,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Reorder an assessment's sections (each section exactly once)."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    sections = (
        db.query(models.AssessmentSection)
        .filter(models.AssessmentSection.assessment_id == assessment.id)
        .all()
    )
    by_id = {s.id: s for s in sections}
    if set(by_id) != set(payload.ordered_section_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reorder must include exactly the sections of this assessment, once each",
        )
    ordered = [by_id[section_id] for section_id in payload.ordered_section_ids]
    # Two-phase reassignment: move every section to a unique temporary
    # (negative) order first, then to its final slot. With a single batched
    # flush the swap would run into the (assessment_id, section_order) unique
    # constraint mid-permutation; the temporary step guarantees every
    # intermediate state is conflict-free.
    for index, section in enumerate(ordered):
        section.section_order = -(index + 1)
    db.flush()
    for index, section in enumerate(ordered):
        section.section_order = index + 1
    db.commit()
    return [schemas.AssessmentSectionOut.model_validate(s) for s in ordered]


@router.put(
    "/{assessment_id}/sections/{section_id}",
    response_model=schemas.AssessmentSectionOut,
)
def update_section(
    assessment_id: int,
    section_id: int,
    payload: schemas.AssessmentSectionUpdate,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Update a section, preventing collisions on section_order."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    section = _owned_section(db, assessment, section_id)
    data = payload.model_dump(exclude_unset=True)
    new_order = data.get("section_order")
    if (
        new_order is not None
        and section.section_order != new_order
        and new_order in _section_orders(db, assessment.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A section with this section_order already exists",
        )
    for field, value in data.items():
        setattr(section, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A section with this section_order already exists",
        )
    db.refresh(section)
    return schemas.AssessmentSectionOut.model_validate(section)


@router.delete("/{assessment_id}/sections/{section_id}", status_code=204)
def remove_section(
    assessment_id: int,
    section_id: int,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Remove a section from an assessment."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    section = _owned_section(db, assessment, section_id)
    db.delete(section)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Candidate assignment management
# ---------------------------------------------------------------------------

def _validated_candidates(
    db: Session, candidate_ids: list[int]
) -> list[models.User]:
    """Return the candidate users for an assignment request.

    Every id must resolve to an existing, active candidate (``user`` role)
    account. Any missing / wrong-role / suspended id fails the whole request
    before anything is written.
    """
    users = (
        db.query(models.User)
        .filter(models.User.id.in_(candidate_ids))
        .all()
    )
    if len(users) != len(candidate_ids):
        raise HTTPException(
            status_code=404, detail="One or more candidate users were not found"
        )
    by_id = {u.id: u for u in users}
    for candidate_id in candidate_ids:
        user = by_id[candidate_id]
        if user.role != models.RoleEnum.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only candidate (user) accounts can be assigned",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot assign a suspended candidate",
            )
    return users


def _owned_assignment(
    db: Session, assessment: models.Assessment, assignment_id: int
) -> models.AssessmentAssignment:
    """Return the assignment only if it belongs to the (already owned) assessment."""
    assignment = (
        db.query(models.AssessmentAssignment)
        .filter(
            models.AssessmentAssignment.id == assignment_id,
            models.AssessmentAssignment.assessment_id == assessment.id,
        )
        .first()
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return assignment


def _assignment_out(
    assignment: models.AssessmentAssignment,
    assessment: models.Assessment,
    users_by_id: dict[int, models.User],
) -> schemas.AssessmentAssignmentDetailOut:
    candidate = users_by_id.get(assignment.candidate_id)
    return schemas.AssessmentAssignmentDetailOut(
        id=assignment.id,
        assessment_id=assignment.assessment_id,
        candidate_id=assignment.candidate_id,
        status=assignment.status,
        assigned_at=assignment.assigned_at,
        started_at=assignment.started_at,
        submitted_at=assignment.submitted_at,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
        candidate_name=candidate.name if candidate else None,
        candidate_email=candidate.email if candidate else None,
        assessment_title=assessment.title if assessment else None,
    )


def _assignment_outs(
    db: Session,
    assessment: models.Assessment,
    assignments: list[models.AssessmentAssignment],
) -> list[schemas.AssessmentAssignmentDetailOut]:
    if not assignments:
        return []
    candidate_ids = {a.candidate_id for a in assignments}
    users = (
        db.query(models.User).filter(models.User.id.in_(candidate_ids)).all()
    )
    users_by_id = {u.id: u for u in users}
    return [
        _assignment_out(a, assessment, users_by_id) for a in assignments
    ]


@router.post(
    "/{assessment_id}/assignments",
    response_model=list[schemas.AssessmentAssignmentDetailOut],
    status_code=201,
)
def assign_candidates(
    assessment_id: int,
    payload: schemas.AssessmentAssignIn,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Assign one or more candidates to the company's assessment.

    Applied atomically: every id is validated (exists / candidate role /
    active) and checked against existing assignments before anything is
    written, so an invalid or already-assigned candidate never leaves a
    partially applied set.
    """
    assessment = _owned_assessment(db, current_user, assessment_id)
    candidates = _validated_candidates(db, payload.candidate_ids)

    existing = (
        db.query(models.AssessmentAssignment)
        .filter(
            models.AssessmentAssignment.assessment_id == assessment.id,
            models.AssessmentAssignment.candidate_id.in_(payload.candidate_ids),
        )
        .all()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Candidate(s) already assigned to this assessment",
        )

    assignments = [
        models.AssessmentAssignment(
            assessment_id=assessment.id, candidate_id=candidate.id
        )
        for candidate in candidates
    ]
    db.add_all(assignments)

    # Notify each newly assigned candidate, atomically with the assignments:
    # a failed or duplicate request rolls everything back, so a notification
    # can never be persisted without its assignment or duplicated by a retry.
    for candidate in candidates:
        create_notification(
            db,
            candidate.id,
            type=models.NotificationType.assessment,
            title="Assessment Assigned",
            message=(
                f"You've been assigned '{assessment.title}' by "
                f"{assessment.company.name}."
            ),
            link="/dashboard/company-assessments",
        )

    try:
        db.commit()
    except IntegrityError:
        # A concurrent request duplicated an assignment between our check and
        # the commit; roll back so no partial set remains.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Candidate(s) already assigned to this assessment",
        )
    for assignment in assignments:
        db.refresh(assignment)
    users_by_id = {u.id: u for u in candidates}
    return [
        _assignment_out(a, assessment, users_by_id) for a in assignments
    ]


@router.get(
    "/{assessment_id}/assignments",
    response_model=list[schemas.AssessmentAssignmentDetailOut],
)
def list_assignments(
    assessment_id: int,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """List the candidates assigned to the company's assessment."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    assignments = (
        db.query(models.AssessmentAssignment)
        .filter(models.AssessmentAssignment.assessment_id == assessment.id)
        .order_by(models.AssessmentAssignment.assigned_at.desc())
        .all()
    )
    return _assignment_outs(db, assessment, assignments)


@router.get(
    "/{assessment_id}/assignments/{assignment_id}",
    response_model=schemas.AssessmentAssignmentDetailOut,
)
def get_assignment(
    assessment_id: int,
    assignment_id: int,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Get one assignment/status detail of the company's assessment."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    assignment = _owned_assignment(db, assessment, assignment_id)
    return _assignment_outs(db, assessment, [assignment])[0]


@router.delete(
    "/{assessment_id}/assignments/{assignment_id}", status_code=204
)
def remove_assignment(
    assessment_id: int,
    assignment_id: int,
    current_user: models.User = Depends(company_scoped),
    db: Session = Depends(get_db),
):
    """Remove an assignment only before the candidate has started it."""
    assessment = _owned_assessment(db, current_user, assessment_id)
    assignment = _owned_assignment(db, assessment, assignment_id)
    if assignment.status != models.AssessmentAssignmentStatusEnum.assigned:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot remove an assignment once the candidate has started it",
        )
    db.delete(assignment)
    db.commit()
    return None
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth import RoleChecker
from app import models, schemas
from app.services.code_executor import execute_code
from app.services.coding_tests import (
    create_test_problems,
    finalize_test,
    get_problem_by_index,
    get_submission,
    is_test_answerable,
    pass_threshold,
    problem_count,
    time_limit_seconds,
)

router = APIRouter(prefix="/coding-tests", tags=["coding-tests"])

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


def _owned_test(
    db: Session, user: models.User, test_id: int
) -> models.CodingTest:
    """Return the test only if it exists and belongs to the candidate."""
    test = (
        db.query(models.CodingTest)
        .filter(models.CodingTest.id == test_id)
        .first()
    )
    if test is None:
        raise HTTPException(status_code=404, detail="Coding test not found")
    if test.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this coding test",
        )
    return test


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _submission_out(sub: models.CodingSubmission) -> schemas.CodingSubmissionOut:
    """Serialize a submission WITHOUT exposing hidden-case inputs/outputs.

    Per-case results only carry index + status + time (never the I/O or the
    expected output of hidden test cases).
    """
    results = [
        schemas.CodingTestCaseResultOut(
            case_index=r.get("case_index", 0),
            passed=bool(r.get("passed", False)),
            status=r.get("status", "error"),
            stdout="",
            stderr="",
            time_ms=int(r.get("time_ms", 0) or 0),
        )
        for r in (sub.results or [])
    ]
    return schemas.CodingSubmissionOut(
        problem_index=sub.problem.problem_index
        if sub.problem is not None
        else 0,
        language=sub.language,
        status=sub.status,
        passed_cases=sub.passed_cases,
        total_cases=sub.total_cases,
        score=sub.score,
        execution_time_ms=sub.execution_time_ms,
        error_message=(
            sub.error_message[:2000] if sub.error_message else None
        ),
        results=results,
        created_at=sub.created_at,
    )


def _problem_out(
    problem: models.CodingProblem,
    submission: models.CodingSubmission | None = None,
) -> schemas.CodingProblemOut:
    """Serialize a problem WITHOUT its hidden test cases."""
    return schemas.CodingProblemOut(
        id=problem.id,
        problem_index=problem.problem_index,
        title=problem.title,
        category=problem.category,
        difficulty=problem.difficulty,
        description=problem.description,
        input_format=problem.input_format,
        output_format=problem.output_format,
        constraints=problem.constraints,
        sample_cases=list(problem.sample_cases or []),
        supported_languages=list(problem.supported_languages or []),
        submission=_submission_out(submission) if submission else None,
    )


def _job_label(test: models.CodingTest) -> tuple:
    application = test.application
    job = application.job if application is not None else None
    return (
        job.title if job else None,
        job.company.name if job and job.company else None,
    )


def _detail(test: models.CodingTest) -> schemas.CodingTestDetailOut:
    problems = sorted(test.problems or [], key=lambda p: p.problem_index)
    submission_by_problem_id = {
        s.problem_id: s for s in (test.submissions or [])
    }
    job_title, company_name = _job_label(test)

    return schemas.CodingTestDetailOut(
        id=test.id,
        application_id=test.application_id,
        user_id=test.user_id,
        job_title=job_title,
        company_name=company_name,
        status=test.status,
        total_problems=test.total_problems,
        solved_count=test.solved_count,
        score=test.score,
        passed=test.passed,
        pass_percentage=test.pass_percentage,
        problems=[
            _problem_out(p, submission_by_problem_id.get(p.id))
            for p in problems
        ],
        started_at=test.started_at,
        completed_at=test.completed_at,
        created_at=test.created_at,
        updated_at=test.updated_at,
    )


def _list_out(test: models.CodingTest) -> schemas.CodingTestListOut:
    job_title, company_name = _job_label(test)
    return schemas.CodingTestListOut(
        id=test.id,
        application_id=test.application_id,
        job_title=job_title,
        company_name=company_name,
        status=test.status,
        total_problems=test.total_problems,
        solved_count=test.solved_count,
        score=test.score,
        passed=test.passed,
        pass_percentage=test.pass_percentage,
        started_at=test.started_at,
        completed_at=test.completed_at,
        created_at=test.created_at,
        updated_at=test.updated_at,
    )


# ---------------------------------------------------------------------------
# Enforcement helpers
# ---------------------------------------------------------------------------

def _ensure_answerable(test: models.CodingTest) -> None:
    """Raise when the test may no longer accept code runs/subs."""
    if not is_test_answerable(test):
        raise HTTPException(
            status_code=400, detail="This coding test is not in progress"
        )


def _ensure_code_valid(payload: schemas.CodingRunIn) -> None:
    """Raise for empty / oversized / unsupported code before execution."""
    if not payload.code.strip():
        raise HTTPException(status_code=400, detail="Code cannot be empty")
    if len(payload.code) > 256 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Code exceeds the maximum allowed length (256 KB)",
        )


# ---------------------------------------------------------------------------
# Start a test
# ---------------------------------------------------------------------------

@router.post("", response_model=schemas.CodingTestDetailOut, status_code=201)
def start_coding_test(
    payload: schemas.CodingTestStartIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Create a coding test for one of the candidate's applications using the
    deterministic question bank. Hidden grading cases stay server-side."""
    application = _owned_application(db, current_user, payload.application_id)

    existing = (
        db.query(models.CodingTest)
        .filter(
            models.CodingTest.application_id == application.id,
            models.CodingTest.user_id == current_user.id,
            models.CodingTest.status
            == models.CodingTestStatusEnum.in_progress,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "A coding test is already in progress for this application "
                f"(test {existing.id}). Resume it instead of starting a new one."
            ),
        )

    total = problem_count()
    test = models.CodingTest(
        user_id=current_user.id,
        application_id=application.id,
        status=models.CodingTestStatusEnum.in_progress,
        total_problems=total,
        solved_count=0,
        pass_percentage=pass_threshold(),
    )
    db.add(test)
    db.flush()

    for problem in create_test_problems(test.id, total):
        db.add(problem)
    db.commit()
    db.refresh(test)
    return _detail(test)


# ---------------------------------------------------------------------------
# Run code against the problem's public sample cases (ephemeral)
# ---------------------------------------------------------------------------

@router.post("/{test_id}/run", response_model=schemas.CodingRunOut)
def run_coding_code(
    test_id: int,
    payload: schemas.CodingRunIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Compile + run candidate code against the SAMPLE cases only. Nothing is
    persisted — this is the candidate's "try it" loop."""
    test = _owned_test(db, current_user, test_id)
    _ensure_answerable(test)
    _ensure_code_valid(payload)

    problem = get_problem_by_index(test, payload.problem_index)
    if problem is None:
        raise HTTPException(
            status_code=404, detail="Problem not found for this coding test"
        )

    cases = list(problem.sample_cases or [])
    result = execute_code(
        payload.language,
        payload.code,
        cases,
        time_limit=problem.time_limit_seconds or time_limit_seconds(),
    )

    return schemas.CodingRunOut(
        problem_index=problem.problem_index,
        language=payload.language,
        compile_error=result.compile_error,
        compile_stderr=result.compile_stderr[:2000],
        test_results=[
            schemas.CodingTestCaseResultOut(
                case_index=r.case_index,
                passed=r.passed,
                status=r.status,
                stdout=r.stdout,
                stderr=r.stderr,
                time_ms=r.time_ms,
            )
            for r in result.test_results
        ],
    )


# ---------------------------------------------------------------------------
# Submit code (evaluated against hidden cases, persisted, scoring)
# ---------------------------------------------------------------------------

@router.post("/{test_id}/submit", response_model=schemas.CodingSubmissionOut)
def submit_coding_code(
    test_id: int,
    payload: schemas.CodingSubmitIn,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Grade the candidate's code against the problem's HIDDEN cases and
    persist the attempt. Hidden-case inputs/outputs are never returned; only
    the overall verdict, pass counts, score, and per-case statuses are."""
    test = _owned_test(db, current_user, test_id)
    _ensure_answerable(test)
    _ensure_code_valid(payload)

    problem = get_problem_by_index(test, payload.problem_index)
    if problem is None:
        raise HTTPException(
            status_code=404, detail="Problem not found for this coding test"
        )

    cases = list(problem.hidden_cases or [])
    if not cases:
        result = None
        passed_cases = 0
        total_cases = 0
        compile_error = True
        compile_detail = "This problem has no hidden test cases configured."
    else:
        result = execute_code(
            payload.language,
            payload.code,
            cases,
            time_limit=problem.time_limit_seconds or time_limit_seconds(),
        )
        passed_cases = sum(1 for r in result.test_results if r.passed)
        total_cases = len(result.test_results)
        compile_error = result.compile_error
        compile_detail = result.compile_stderr

    if result is None or compile_error:
        status_val = "error"
        score = 0
        error_message = (
            compile_detail[:2000] or "Compilation failed"
        )
    else:
        score = (
            int(round((passed_cases / total_cases) * 100))
            if total_cases
            else 0
        )
        status_val = "passed" if passed_cases == total_cases else "failed"
        error_message = None

    per_case = (
        [
            {
                "case_index": r.case_index,
                "passed": r.passed,
                "status": r.status,
                "time_ms": r.time_ms,
            }
            for r in result.test_results
        ]
        if result
        else []
    )

    # Upsert: one submission per (test, problem).
    existing = get_submission(test, problem.id)
    if existing is None:
        submission = models.CodingSubmission(
            coding_test_id=test.id,
            problem_id=problem.id,
            user_id=current_user.id,
            language=payload.language,
            code=payload.code,
            status=status_val,
            passed_cases=passed_cases,
            total_cases=total_cases,
            score=score,
            execution_time_ms=result.total_time_ms if result else None,
            error_message=error_message,
            results=per_case,
        )
        db.add(submission)
        db.flush()
    else:
        existing.language = payload.language
        existing.code = payload.code
        existing.status = status_val
        existing.passed_cases = passed_cases
        existing.total_cases = total_cases
        existing.score = score
        existing.execution_time_ms = (
            result.total_time_ms if result else None
        )
        existing.error_message = error_message
        existing.results = per_case
        submission = existing

    db.commit()
    db.refresh(submission)
    submission.problem = problem
    return _submission_out(submission)


# ---------------------------------------------------------------------------
# Finish / finalize / list / detail / delete
# ---------------------------------------------------------------------------

@router.post("/{test_id}/finish", response_model=schemas.CodingTestDetailOut)
def finish_coding_test(
    test_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Finalize the test and compute the aggregate score. Idempotent: a
    completed test returns its stored results without re-finalizing."""
    test = _owned_test(db, current_user, test_id)

    if test.status == models.CodingTestStatusEnum.in_progress:
        finalize_test(test)
        db.commit()
        db.refresh(test)

    return _detail(test)


@router.get("", response_model=list[schemas.CodingTestListOut])
def list_coding_tests(
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """List the candidate's coding tests, newest first."""
    tests = (
        db.query(models.CodingTest)
        .filter(models.CodingTest.user_id == current_user.id)
        .order_by(models.CodingTest.created_at.desc())
        .all()
    )
    return [_list_out(t) for t in tests]


@router.get("/{test_id}", response_model=schemas.CodingTestDetailOut)
def get_coding_test(
    test_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Return the test detail with its problems and per-problem submissions."""
    test = _owned_test(db, current_user, test_id)
    return _detail(test)


@router.delete("/{test_id}", status_code=204)
def delete_coding_test(
    test_id: int,
    current_user: models.User = Depends(candidate_only),
    db: Session = Depends(get_db),
):
    """Delete the test, its problems and its submissions."""
    test = _owned_test(db, current_user, test_id)
    db.delete(test)
    db.commit()
    return None
"""Task 25: assignment vs. deletion race.

The company can assign candidates to a published assessment and can delete an
assessment. Deleting cascades to assignments; assigning only requires the
assessment to be published/in-window. Neither operation took a lock on the
assessment row, so on PostgreSQL the two could interleave:

  * delete commits between assign's existence read and assign's INSERT
    -> INSERT raises an FK violation, which the route maps to a *misleading*
       409 ("Candidate(s) already assigned") for an assessment that is gone;
  * assign commits just before delete
    -> the not-started assignment is cascade-deleted right after assign
       reported success.

The fix serializes the two by locking the assessment row (``FOR UPDATE``)
first, in a consistent order (assessment row before assignment rows), and
re-checks existence / published / window after the lock. A losing assignment
request now gets a clear ``404``.

The concurrency tests in this module require a real PostgreSQL server
(``DATABASE_URL``); they are skipped when only SQLite is available, because
SQLite ``SELECT ... FOR UPDATE`` is a no-op and cannot prove row-lock
behaviour. The deterministic tests at the bottom always run on SQLite and pin
the (non-concurrent) policy/ordering invariants.
"""
import os
import threading
import time
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.routes.company_assessments import assign_candidates, delete_assessment


# ---------------------------------------------------------------------------
# PostgreSQL capability detection
# ---------------------------------------------------------------------------

def _postgres_url():
    raw = os.getenv("DATABASE_URL", "")
    if not raw.startswith("postgres"):
        return None
    try:
        url = make_url(raw)
        admin = create_engine(
            url.set(database="postgres"), isolation_level="AUTOCOMMIT"
        )
        with admin.connect():
            pass
        admin.dispose()
        return url
    except Exception:
        return None


PG_URL = _postgres_url()
requires_pg = pytest.mark.skipif(
    PG_URL is None, reason="PostgreSQL not available for concurrency verification"
)


def _tables():
    return [
        models.User.__table__,
        models.Company.__table__,
        models.Assessment.__table__,
        models.AssessmentSection.__table__,
        models.AssessmentAssignment.__table__,
        models.AssessmentQuestion.__table__,
        models.AssessmentAnswer.__table__,
        models.Notification.__table__,
    ]


@pytest.fixture(scope="module")
def pg_engine():
    if PG_URL is None:
        yield None
        return
    dbname = f"recruito_t25_{uuid.uuid4().hex[:8]}"
    admin = create_engine(PG_URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{dbname}"'))
    admin.dispose()
    engine = create_engine(PG_URL.set(database=dbname))
    models.Base.metadata.create_all(engine, tables=_tables())
    try:
        yield engine
    finally:
        engine.dispose()
        admin = create_engine(
            PG_URL.set(database="postgres"), isolation_level="AUTOCOMMIT"
        )
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _seed_pg(engine):
    """Create owner + company + candidate + published assessment; return ids."""
    with Session(engine) as s:
        owner = models.User(
            name="Owner", email=f"o{uuid.uuid4().hex[:8]}@t25.test", password="x",
            role=models.RoleEnum.company,
        )
        cand = models.User(
            name="Cand", email=f"c{uuid.uuid4().hex[:8]}@t25.test", password="x",
            role=models.RoleEnum.user,
        )
        s.add_all([owner, cand])
        s.flush()
        company = models.Company(user_id=owner.id, name="T25 Co", approved=True)
        s.add(company)
        s.flush()
        a = models.Assessment(
            company_id=company.id, title="Race", duration_minutes=60,
            status=models.CompanyAssessmentStatusEnum.published,
            starts_at=datetime(2020, 1, 1), ends_at=datetime(2030, 1, 1),
        )
        s.add(a)
        s.commit()
        return owner.id, cand.id, a.id


# ---------------------------------------------------------------------------
# Real PostgreSQL concurrency verification
# ---------------------------------------------------------------------------

@requires_pg
def test_deletion_wins_assign_returns_clear_404(pg_engine):
    """When deletion commits first, the concurrent assignment must fail with a
    clear 404 (not a misleading 409 and not a false success)."""
    owner_id, cand_id, aid = _seed_pg(pg_engine)
    locked = threading.Event()
    release = threading.Event()
    out = {}

    def deleter():
        s = Session(pg_engine)
        try:
            # Hold the assessment row lock, delete under it, then wait so the
            # assigner is forced to contend for the same row.
            s.execute(
                text("SELECT id FROM assessments WHERE id = :a FOR UPDATE"),
                {"a": aid},
            )
            s.execute(
                text("DELETE FROM assessment_assignments WHERE assessment_id = :a"),
                {"a": aid},
            )
            s.execute(text("DELETE FROM assessments WHERE id = :a"), {"a": aid})
            locked.set()
            release.wait(timeout=5)
            s.commit()
        except Exception as exc:  # pragma: no cover - surfaced via assertion
            out["deleter_error"] = repr(exc)
        finally:
            s.close()
            out["deleter_done"] = True

    def assigner():
        s = Session(pg_engine)
        try:
            owner = s.get(models.User, owner_id)
            assign_candidates(
                aid,
                schemas.AssessmentAssignIn(candidate_ids=[cand_id]),
                owner,
                s,
            )
            out["assign"] = 201
        except HTTPException as exc:
            out["assign"] = exc.status_code
        except Exception as exc:
            out["assign"] = repr(exc)
        finally:
            s.close()

    td = threading.Thread(target=deleter)
    td.start()
    assert locked.wait(5), "deleter never acquired the lock"
    ta = threading.Thread(target=assigner)
    ta.start()
    time.sleep(1.0)
    # The assigner must be blocked on the assessment row lock, not racing past.
    assert ta.is_alive(), "assign did not block on the assessment row lock"
    release.set()
    td.join(10)
    ta.join(10)

    assert "deleter_error" not in out, out.get("deleter_error")
    assert out.get("assign") == 404, f"expected 404, got {out.get('assign')!r}"
    with Session(pg_engine) as s:
        assert s.get(models.Assessment, aid) is None
        remaining = s.execute(
            text("SELECT count(*) FROM assessment_assignments WHERE assessment_id = :a"),
            {"a": aid},
        ).scalar()
        assert remaining == 0


@requires_pg
def test_assignment_commits_then_deletion_removes_not_started(pg_engine):
    """When the assignment commits first, it is a valid serialization: the
    assignment exists, and the subsequent deletion (allowed for not-started
    candidates) cascades it away."""
    owner_id, cand_id, aid = _seed_pg(pg_engine)

    with Session(pg_engine) as s:
        owner = s.get(models.User, owner_id)
        created = assign_candidates(
            aid, schemas.AssessmentAssignIn(candidate_ids=[cand_id]), owner, s
        )
        assert [a.candidate_id for a in created] == [cand_id]

    with Session(pg_engine) as s:
        owner = s.get(models.User, owner_id)
        delete_assessment(aid, owner, s)

    with Session(pg_engine) as s:
        assert s.get(models.Assessment, aid) is None
        assert s.execute(
            text("SELECT count(*) FROM assessment_assignments WHERE assessment_id = :a"),
            {"a": aid},
        ).scalar() == 0


@requires_pg
def test_assign_to_deleted_assessment_404(pg_engine):
    """Assignment against an already-deleted assessment is a clean 404."""
    owner_id, cand_id, aid = _seed_pg(pg_engine)
    with Session(pg_engine) as s:
        owner = s.get(models.User, owner_id)
        delete_assessment(aid, owner, s)

    with Session(pg_engine) as s:
        owner = s.get(models.User, owner_id)
        with pytest.raises(HTTPException) as exc:
            assign_candidates(
                aid, schemas.AssessmentAssignIn(candidate_ids=[cand_id]), owner, s
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Deterministic SQLite policy/ordering tests (always run)
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    models.Base.metadata.create_all(engine, tables=_tables())
    s = Session(engine)
    yield s
    s.close()
    engine.dispose()


def _seed_sqlite(db):
    owner = models.User(
        name="Owner", email="o@t25.test", password="x", role=models.RoleEnum.company
    )
    cand = models.User(
        name="Cand", email="c@t25.test", password="x", role=models.RoleEnum.user
    )
    db.add_all([owner, cand])
    db.flush()
    company = models.Company(user_id=owner.id, name="T25 Co", approved=True)
    db.add(company)
    db.flush()
    a = models.Assessment(
        company_id=company.id, title="Race", duration_minutes=60,
        status=models.CompanyAssessmentStatusEnum.published,
        starts_at=datetime(2020, 1, 1), ends_at=datetime(2030, 1, 1),
    )
    db.add(a)
    db.flush()
    return owner, cand, a


def test_sqlite_assign_then_delete_removes_not_started(db):
    owner, cand, a = _seed_sqlite(db)
    created = assign_candidates(
        a.id, schemas.AssessmentAssignIn(candidate_ids=[cand.id]), owner, db
    )
    assert len(created) == 1

    delete_assessment(a.id, owner, db)
    assert db.get(models.Assessment, a.id) is None
    assert (
        db.query(models.AssessmentAssignment)
        .filter(models.AssessmentAssignment.assessment_id == a.id)
        .count()
        == 0
    )


def test_sqlite_delete_then_assign_404(db):
    owner, cand, a = _seed_sqlite(db)
    delete_assessment(a.id, owner, db)
    with pytest.raises(HTTPException) as exc:
        assign_candidates(
            a.id, schemas.AssessmentAssignIn(candidate_ids=[cand.id]), owner, db
        )
    assert exc.value.status_code == 404


def test_sqlite_assign_to_missing_assessment_404(db):
    owner, cand, _a = _seed_sqlite(db)
    with pytest.raises(HTTPException) as exc:
        assign_candidates(
            999999, schemas.AssessmentAssignIn(candidate_ids=[cand.id]), owner, db
        )
    assert exc.value.status_code == 404


def test_sqlite_deletion_blocked_with_in_progress_attempt(db):
    owner, cand, a = _seed_sqlite(db)
    db.add(
        models.AssessmentAssignment(
            assessment_id=a.id, candidate_id=cand.id,
            status=models.AssessmentAssignmentStatusEnum.in_progress,
            started_at=datetime.utcnow() - timedelta(minutes=5),
        )
    )
    db.flush()
    with pytest.raises(HTTPException) as exc:
        delete_assessment(a.id, owner, db)
    assert exc.value.status_code == 409
    assert db.get(models.Assessment, a.id) is not None

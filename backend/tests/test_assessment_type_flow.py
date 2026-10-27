from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.routes.company_assessments import create_assessment


def _make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    from app import models as m

    tables = [
        m.User.__table__,
        m.Company.__table__,
        m.Job.__table__,
        m.Application.__table__,
        m.Assessment.__table__,
        m.AssessmentSection.__table__,
        m.AssessmentAssignment.__table__,
        m.AssessmentQuestion.__table__,
        m.AssessmentAnswer.__table__,
    ]
    m.Base.metadata.create_all(engine, tables=tables)
    s = Session(engine)
    return s


def test_create_assessment_with_types():
    db = _make_db()
    try:
        u = models.User(id=1, name="R", email="r@r.com", password="p", role=models.RoleEnum.company)
        db.add(u)
        db.flush()
        c = models.Company(user_id=u.id, name="Acme", approved=True)
        db.add(c)
        db.commit()

        res1 = create_assessment(schemas.AssessmentCreate(title="Apt", assessment_type=models.AssessmentTypeEnum.aptitude), u, db)
        assert res1.assessment_type == models.AssessmentTypeEnum.aptitude

        res2 = create_assessment(schemas.AssessmentCreate(title="T", assessment_type=models.AssessmentTypeEnum.technical_mcq), u, db)
        assert res2.assessment_type == models.AssessmentTypeEnum.technical_mcq

        res3 = create_assessment(schemas.AssessmentCreate(title="C", assessment_type=models.AssessmentTypeEnum.coding), u, db)
        assert res3.assessment_type == models.AssessmentTypeEnum.coding
    finally:
        db.close()

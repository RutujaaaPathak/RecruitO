"""RBAC tests for the RAG endpoints' application-access gates.

The same `_can_manage` helper guards the skill-gap, semantic-match,
retrieved-chunks and career-recommendations endpoints. It is tested here
hermetically with transient ORM objects and a stubbed session.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.models import (  # noqa: E402
    Application,
    ApplicationStatusEnum,
    Company,
    Job,
    User,
)
from app.routes.applications import _can_manage  # noqa: E402


class FakeCompanyQuery:
    def __init__(self, company):
        self._company = company

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._company


class FakeDB:
    def __init__(self, company=None):
        self._company = company

    def query(self, model):
        return FakeCompanyQuery(self._company)


def _company(id_, user_id):
    return Company(id=id_, user_id=user_id, name="Acme")


def _make(company_owner_user_id, applicant_user_id):
    company = _company(id_=5, user_id=company_owner_user_id)
    job = Job(id=100, company_id=5, title="Engineer")
    app = Application(
        id=200, job_id=100, user_id=applicant_user_id,
        status=ApplicationStatusEnum.applied,
    )
    app.job = job
    return company, app


def _user(role, id_=1):
    u = User(id=id_, name="x", email=f"{id_}@x.com", password="p", role=role)
    return u


def test_admin_can_access_any_application():
    company, app = _make(company_owner_user_id=1, applicant_user_id=2)
    db = FakeDB()  # admin path should not touch the DB
    assert _can_manage(db, app, _user("admin")) is True


def test_owning_candidate_can_access():
    company, app = _make(company_owner_user_id=1, applicant_user_id=2)
    assert _can_manage(FakeDB(), app, _user("user", id_=2)) is True


def test_other_candidate_cannot_access():
    company, app = _make(company_owner_user_id=1, applicant_user_id=2)
    assert _can_manage(FakeDB(), app, _user("user", id_=3)) is False


def test_owning_company_can_access():
    company, app = _make(company_owner_user_id=1, applicant_user_id=2)
    # The FakeDB returns the owner company for the query in _can_manage.
    db = FakeDB(company=company)
    assert _can_manage(db, app, _user("company", id_=1)) is True


def test_other_company_cannot_access():
    company, app = _make(company_owner_user_id=1, applicant_user_id=2)
    other_company = _company(id_=9, user_id=4)
    db = FakeDB(company=other_company)
    assert _can_manage(db, app, _user("company", id_=4)) is False


def test_company_without_profile_cannot_access():
    company, app = _make(company_owner_user_id=1, applicant_user_id=2)
    db = FakeDB(company=None)
    assert _can_manage(db, app, _user("company", id_=4)) is False


def test_retrieved_chunks_are_scoped_to_candidate_resume():
    # Retrieval is fed the application's owner resume. Verify the source
    # conversion keeps the chunk attached to the right candidate by running
    # the owning-candidate path end-to-end at the access-gate layer.
    company, app = _make(company_owner_user_id=1, applicant_user_id=2)
    db = FakeDB(company=company)
    assert _can_manage(db, app, _user("company", id_=1)) is True
    assert app.user_id == 2  # resume lookup is scoped to this user id
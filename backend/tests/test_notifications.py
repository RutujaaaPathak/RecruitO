"""In-app notification tests (/notifications + the event wiring that creates them).

Covers creation, owner-scoped listing (newest first), unread counting, mark-read
(including idempotency and 404 isolation), read-all, and the wiring that
notifies the right person when a candidate applies, an interview is
scheduled/completed/cancelled, or a company is approved/rejected. Uses the
suite's lightweight fake-DB convention (no DB, no network).
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.sql.elements import False_, True_

from app import models, schemas
from app.services.notifications import create_notification
from app.routes import notifications as notifications_mod
from app.routes import applications as applications_mod
from app.routes import interviews as interviews_mod
from app.routes import admin as admin_mod


def _user_row(id, role=models.RoleEnum.user, name="Test User"):
    return models.User(
        id=id,
        name=name,
        email=f"user{id}@recruito.com",
        password="hashed",
        role=role,
    )


def _notification_row(
    id,
    user_id,
    type=models.NotificationType.system,
    title="Title",
    message="Message",
    link=None,
    read=False,
    created_at=None,
):
    return models.Notification(
        id=id,
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        link=link,
        read=read,
        created_at=created_at or datetime.utcnow(),
    )


def _job_row(id, company_id, title="Backend Engineer"):
    return models.Job(
        id=id,
        company_id=company_id,
        title=title,
        status=models.JobStatusEnum.open,
    )


def _company_row(id, user_id, name="Acme", approved=True):
    return models.Company(
        id=id,
        user_id=user_id,
        name=name,
        approved=approved,
    )


def _notif_rows(db):
    return [r for r in db.rows if type(r) is models.Notification]


# ---------------------------------------------------------------------------
# Fake DB supporting the small query surface the notification routes use
# ---------------------------------------------------------------------------

def _right_value(right):
    """Normalize a comparison's right side: literal False_/True_ become bools,
    BindParameters give up their value, and anything else is kept as-is."""
    if isinstance(right, False_):
        return False
    if isinstance(right, True_):
        return True
    return getattr(right, "value", right)


class _FakeQuery:
    def __init__(self, db, model):
        self._db = db
        self._model = model
        self._filters = []
        self._sorts = []

    def filter(self, *args, **kwargs):
        for arg in args:
            try:
                self._filters.append((arg.left.key, _right_value(arg.right)))
            except Exception:
                continue
        for key, value in kwargs.items():
            self._filters.append((key, value))
        return self

    def order_by(self, *args, **kwargs):
        for arg in args:
            try:
                element = getattr(arg, "element", None)
                if element is None:
                    element = getattr(arg, "left", None)
                descending = "DESC" in str(arg).upper()
                self._sorts.append((element.key, descending))
            except Exception:
                continue
        return self

    def _matching(self):
        matches = [
            row
            for row in self._db.rows
            if type(row) is self._model
            and all(getattr(row, key) == value for key, value in self._filters)
        ]
        for key, descending in reversed(self._sorts):
            matches.sort(
                key=lambda r: getattr(r, key) or datetime.min, reverse=descending
            )
        return matches

    def first(self):
        matches = self._matching()
        return matches[0] if matches else None

    def all(self):
        return self._matching()

    def count(self):
        return len(self._matching())

    def delete(self):
        matched = {id(row) for row in self._matching()}
        self._db.rows = [row for row in self._db.rows if id(row) not in matched]
        return None


class _FakeDb:
    def __init__(self, rows=None):
        self.rows = []
        self.commits = 0
        self._next_id = 1
        for row in rows or []:
            self.add(row)

    def _apply_defaults(self, obj):
        """Mirror the INSERT-time behavior the routes rely on: scalar/python
        defaults the model declares (e.g. created_at, read) plus an
        auto-increment primary key. Kept explicit because SQLAlchemy wraps
        callable defaults, so calling ``column.default.arg()`` directly fails."""
        try:
            table = type(obj).__table__
        except Exception:
            return
        if getattr(obj, "id", None) is None:
            setattr(obj, "id", self._next_id)
            self._next_id += 1
        for key in ("created_at", "updated_at"):
            column = table.columns.get(key)
            if (
                column is not None
                and column.default is not None
                and getattr(obj, key, None) is None
            ):
                setattr(obj, key, datetime.utcnow())
        read = table.columns.get("read")
        if read is not None and read.default is not None and getattr(obj, "read", None) is None:
            setattr(obj, "read", read.default.arg)

    def query(self, model):
        return _FakeQuery(self, model)

    def add(self, obj):
        self._apply_defaults(obj)
        self.rows.append(obj)

    def delete(self, obj):
        if obj in self.rows:
            self.rows.remove(obj)

    def commit(self):
        self.commits += 1

    def flush(self):
        return None

    def refresh(self, obj):
        return obj


# ---------------------------------------------------------------------------
# Notification core endpoints
# ---------------------------------------------------------------------------

def test_list_notifications_is_owner_scoped_and_newest_first():
    mine_old = _notification_row(1, 10, created_at=datetime(2026, 1, 1))
    mine_mid = _notification_row(2, 10, created_at=datetime(2026, 1, 2))
    mine_new = _notification_row(3, 10, created_at=datetime(2026, 1, 3))
    others = _notification_row(4, 11, created_at=datetime(2026, 1, 4))
    db = _FakeDb([mine_old, others, mine_new, mine_mid])

    result = notifications_mod.list_notifications(_user_row(10), db)

    assert [n.id for n in result] == [3, 2, 1]
    assert all(n.user_id == 10 for n in result)


def test_unread_count_tracks_read_state_per_user():
    db = _FakeDb(
        [
            _notification_row(1, 10, read=False),
            _notification_row(2, 10, read=True),
            _notification_row(3, 10, read=False),
            _notification_row(4, 11, read=False),  # someone else's unread
        ]
    )
    user = _user_row(10)

    assert notifications_mod.unread_count(user, db) == {"unread_count": 2}
    notifications_mod.mark_read(1, user, db)
    assert notifications_mod.unread_count(user, db) == {"unread_count": 1}


def test_mark_read_marks_own_notification_and_is_idempotent():
    db = _FakeDb([_notification_row(1, 10)])
    user = _user_row(10)

    result = notifications_mod.mark_read(1, user, db)
    assert isinstance(result, models.Notification)
    assert result.read is True
    assert db.commits == 1

    notifications_mod.mark_read(1, user, db)
    assert db.commits == 1


def test_mark_read_404_for_other_users_or_unknown_notification():
    db = _FakeDb([_notification_row(1, 11), _notification_row(2, 10)])
    user = _user_row(10)

    with pytest.raises(HTTPException) as exc:
        notifications_mod.mark_read(1, user, db)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        notifications_mod.mark_read(999, user, db)
    assert exc.value.status_code == 404

    # The other user's notification stays untouched.
    (n,) = [r for r in _notif_rows(db) if r.id == 1]
    assert n.read is False


def test_read_all_marks_only_own_unread():
    db = _FakeDb(
        [
            _notification_row(1, 10, read=False),
            _notification_row(2, 10, read=False),
            _notification_row(3, 10, read=True),
            _notification_row(4, 11, read=False),  # someone else's unread
        ]
    )
    user = _user_row(10)

    result = notifications_mod.mark_all_read(user, db)

    assert result["marked"] == 2
    assert all(n.read for n in _notif_rows(db) if n.user_id == 10)
    assert next(n for n in _notif_rows(db) if n.id == 4).read is False


def test_create_notification_adds_row_without_committing():
    db = _FakeDb()

    create_notification(
        db,
        7,
        type=models.NotificationType.application,
        title="New Application",
        message="Someone applied",
        link="/company/applicants",
    )

    (n,) = _notif_rows(db)
    assert n.user_id == 7
    assert n.type is models.NotificationType.application
    assert n.title == "New Application"
    assert n.message == "Someone applied"
    assert n.link == "/company/applicants"
    assert n.read is False
    assert db.commits == 0


# ---------------------------------------------------------------------------
# Event wiring: the triggering routes create the right notification
# ---------------------------------------------------------------------------

def test_application_submission_notifies_job_owner():
    company = _company_row(1, 2)
    job = _job_row(1, 1)
    candidate = _user_row(10, name="Ada Lovelace")
    db = _FakeDb([company, job, candidate])

    result = applications_mod.create_application(
        schemas.ApplicationCreate(job_id=1), candidate, db
    )

    (n,) = _notif_rows(db)
    assert n.user_id == 2
    assert n.type is models.NotificationType.application
    assert n.title == "New Application"
    assert "Ada Lovelace" in n.message
    assert "Backend Engineer" in n.message
    assert n.link == "/company/applicants"
    assert result.job_id == 1
    assert n.read is False


def test_scheduling_interview_notifies_candidate():
    company = _company_row(1, 2)
    owner = _user_row(2, role=models.RoleEnum.company, name="Owner")
    candidate = _user_row(10)
    job = _job_row(1, 1)
    application = models.Application(
        id=10,
        job_id=1,
        user_id=10,
        status=models.ApplicationStatusEnum.applied,
    )
    application.job = job  # what _company_can_access needs on the fake
    db = _FakeDb([company, owner, candidate, job, application])

    interviews_mod.create_interview(
        schemas.InterviewCreate(
            application_id=10, scheduled_at=datetime.utcnow() + timedelta(days=1)
        ),
        owner,
        db,
    )

    (n,) = _notif_rows(db)
    assert n.user_id == 10
    assert n.type is models.NotificationType.interview
    assert n.title == "Interview Scheduled"
    assert "Backend Engineer" in n.message

    (app,) = [r for r in db.rows if type(r) is models.Application]
    assert app.status is models.ApplicationStatusEnum.shortlisted


@pytest.mark.parametrize(
    "status,expected_title,expected_word",
    [
        (models.InterviewStatusEnum.completed, "Interview Completed", "completed"),
        (models.InterviewStatusEnum.cancelled, "Interview Cancelled", "cancelled"),
    ],
)
def test_interview_status_change_notifies_candidate(
    status, expected_title, expected_word
):
    admin = _user_row(99, role=models.RoleEnum.admin)
    candidate = _user_row(10)
    interview = models.Interview(
        id=5,
        application_id=10,
        job_id=1,
        user_id=10,
        status=models.InterviewStatusEnum.scheduled,
    )
    application = models.Application(
        id=10,
        job_id=1,
        user_id=10,
        status=models.ApplicationStatusEnum.shortlisted,
    )
    db = _FakeDb([admin, candidate, interview, application])

    interviews_mod.update_interview(5, schemas.InterviewUpdate(status=status), admin, db)

    (n,) = _notif_rows(db)
    assert n.user_id == 10
    assert n.type is models.NotificationType.interview
    assert n.title == expected_title
    assert expected_word in n.message


def test_company_approval_notifies_company_owner():
    company = _company_row(1, 2, name="Acme", approved=False)
    admin = _user_row(99, role=models.RoleEnum.admin)
    db = _FakeDb([company, admin])

    result = admin_mod.set_company_approval(1, True, admin, db)

    (n,) = _notif_rows(db)
    assert n.user_id == 2
    assert n.type is models.NotificationType.system
    assert n.title == "Company Approved"
    assert "Acme" in n.message
    assert n.link == "/company/dashboard"
    assert result.approved is True


def test_company_rejection_notifies_company_owner():
    company = _company_row(1, 2, name="Acme")
    admin = _user_row(99, role=models.RoleEnum.admin)
    db = _FakeDb([company, admin])

    admin_mod.set_company_approval(1, False, admin, db)

    (n,) = _notif_rows(db)
    assert n.user_id == 2
    assert n.type is models.NotificationType.system
    assert n.title == "Company Application Rejected"
    assert "Acme" in n.message
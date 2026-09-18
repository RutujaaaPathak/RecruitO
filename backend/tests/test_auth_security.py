"""Security hardening tests: SECRET_KEY enforcement, configurable CORS origins,
timezone-aware JWT expiry, and last-active-admin protection in the admin API.
"""
import importlib
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jose import jwt

import app.auth as auth_mod
from app.config import cors_origins
from app.models import RoleEnum
from app.routes.admin import UserAdminUpdate, update_user

STRONG_SECRET = "x" * 64


@pytest.fixture
def auth_reloadable(monkeypatch):
    monkeypatch.setattr("app.config.load_env", lambda: None)
    yield
    monkeypatch.setenv("SECRET_KEY", STRONG_SECRET)
    importlib.reload(auth_mod)


# ---------------------------------------------------------------------------
# SECRET_KEY enforcement (no fallback, fail fast on missing/weak keys)
# ---------------------------------------------------------------------------

def test_secret_key_missing_fails_fast(auth_reloadable, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        importlib.reload(auth_mod)


def test_secret_key_too_short_fails_fast(auth_reloadable, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "too-short")
    with pytest.raises(RuntimeError, match="too weak"):
        importlib.reload(auth_mod)


def test_secret_key_placeholder_fails_fast(auth_reloadable, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "change-me-to-a-long-random-secret")
    with pytest.raises(RuntimeError, match="placeholder"):
        importlib.reload(auth_mod)


def test_old_demo_fallback_fails_fast(auth_reloadable, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "supersecretkey")
    with pytest.raises(RuntimeError, match="placeholder"):
        importlib.reload(auth_mod)


def test_strong_secret_key_loads_and_signs_tokens(auth_reloadable, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", STRONG_SECRET)
    importlib.reload(auth_mod)
    token = auth_mod.create_access_token({"sub": "candidate@recruito.com", "id": 7})
    payload = jwt.decode(token, STRONG_SECRET, algorithms=[auth_mod.ALGORITHM])
    assert payload["sub"] == "candidate@recruito.com"
    assert payload["id"] == 7


def test_access_token_expiry_is_timezone_aware_utc_future():
    token = auth_mod.create_access_token({"sub": "a@b.c"})
    payload = jwt.decode(token, auth_mod.SECRET_KEY, algorithms=[auth_mod.ALGORITHM])
    assert isinstance(payload["exp"], int)
    assert payload["exp"] > time.time()
    assert payload["exp"] <= time.time() + 2 * 60 * 60


# ---------------------------------------------------------------------------
# CORS origins configuration
# ---------------------------------------------------------------------------

def test_cors_origins_default_to_localhost(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert cors_origins() == ["http://localhost:5173"]


def test_cors_origins_parse_comma_separated(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS", " https://app.example.com , http://localhost:5173 "
    )
    assert cors_origins() == [
        "https://app.example.com",
        "http://localhost:5173",
    ]


def test_cors_origins_drop_empty_entries(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com,,,")
    assert cors_origins() == ["https://a.example.com"]


# ---------------------------------------------------------------------------
# Last-active-admin protection
# ---------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, db):
        self._db = db

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._db.target

    def count(self):
        return self._db.active_other_admins


class _FakeDb:
    def __init__(self, target, active_other_admins=0):
        self.target = target
        self.active_other_admins = active_other_admins
        self.commits = 0
        self.refreshes = 0

    def query(self, model):
        return _FakeQuery(self)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        self.refreshes += 1


def _admin(**kw):
    defaults = dict(
        id=1, name="Admin", email="admin@recruito.com",
        role=RoleEnum.admin, is_active=True,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_cannot_demote_last_active_admin():
    admin = _admin()
    db = _FakeDb(admin, active_other_admins=0)
    with pytest.raises(HTTPException) as exc:
        update_user(
            admin.id, UserAdminUpdate(role=RoleEnum.user),
            current_user=admin, db=db,
        )
    assert exc.value.status_code == 400
    assert "last active admin" in exc.value.detail
    assert db.commits == 0


def test_cannot_deactivate_last_active_admin():
    admin = _admin()
    db = _FakeDb(admin, active_other_admins=0)
    with pytest.raises(HTTPException) as exc:
        update_user(
            admin.id, UserAdminUpdate(is_active=False),
            current_user=admin, db=db,
        )
    assert exc.value.status_code == 400
    assert db.commits == 0


def test_cannot_demote_and_deactivate_last_active_admin_together():
    admin = _admin()
    db = _FakeDb(admin, active_other_admins=0)
    with pytest.raises(HTTPException) as exc:
        update_user(
            admin.id,
            UserAdminUpdate(role=RoleEnum.user, is_active=False),
            current_user=admin, db=db,
        )
    assert exc.value.status_code == 400


def test_demote_allowed_when_another_active_admin_exists():
    admin = _admin(id=2)
    db = _FakeDb(admin, active_other_admins=1)
    updated = update_user(
        admin.id, UserAdminUpdate(role=RoleEnum.user),
        current_user=_admin(id=1), db=db,
    )
    assert updated.role == RoleEnum.user
    assert db.commits == 1


def test_deactivate_allowed_when_another_active_admin_exists():
    admin = _admin(id=2)
    db = _FakeDb(admin, active_other_admins=2)
    updated = update_user(
        admin.id, UserAdminUpdate(is_active=False),
        current_user=_admin(id=1), db=db,
    )
    assert updated.is_active is False
    assert db.commits == 1


def test_last_active_admin_can_update_own_name():
    admin = _admin()
    db = _FakeDb(admin, active_other_admins=0)
    updated = update_user(
        admin.id, UserAdminUpdate(name="Renamed Admin"),
        current_user=admin, db=db,
    )
    assert updated.name == "Renamed Admin"
    assert db.commits == 1


def test_deactivating_inactive_admin_not_blocked():
    admin = _admin(is_active=False)
    db = _FakeDb(admin, active_other_admins=0)
    updated = update_user(
        admin.id, UserAdminUpdate(role=RoleEnum.user),
        current_user=_admin(id=2), db=db,
    )
    assert updated.role == RoleEnum.user


def test_deactivating_non_admin_user_allowed():
    user = SimpleNamespace(
        id=3, name="Cand", email="c@recruito.com",
        role=RoleEnum.user, is_active=True,
    )
    db = _FakeDb(user, active_other_admins=0)
    updated = update_user(
        user.id, UserAdminUpdate(is_active=False),
        current_user=_admin(id=1), db=db,
    )
    assert updated.is_active is False


def test_update_user_not_found_returns_404():
    db = _FakeDb(None, active_other_admins=0)
    with pytest.raises(HTTPException) as exc:
        update_user(
            999, UserAdminUpdate(role=RoleEnum.user),
            current_user=_admin(id=1), db=db,
        )
    assert exc.value.status_code == 404
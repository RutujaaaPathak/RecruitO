"""Tests for candidate signup email OTP verification.

OTP is REQUIRED by default (secure default) and may be explicitly bypassed
with BYPASS_EMAIL_OTP=true for local development/testing only. The bypass does
not remove OTP functionality, only switches the module-level default.

All tests call the route functions directly with a lightweight fake DB, so no
database or SMTP service is required.
"""
import importlib
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.routes.auth_routes as auth_mod
from app import models


@pytest.fixture
def otp_reloadable(monkeypatch):
    monkeypatch.setattr("app.config.load_env", lambda: None)
    yield


def _reload_with(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("BYPASS_EMAIL_OTP", raising=False)
    else:
        monkeypatch.setenv("BYPASS_EMAIL_OTP", value)
    importlib.reload(auth_mod)


class _SignupQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model
        self._otp_mismatch = False

    def filter(self, *args, **kwargs):
        if self.model is models.EmailOTP and self.db.otp is not None:
            # Honour the ``EmailOTP.otp == <code>`` predicate: a record whose
            # stored code differs behaves like no match (an OTP mismatch).
            for arg in args:
                try:
                    left_key = arg.left.key
                    right = arg.right.value
                except Exception:
                    continue
                if left_key == "otp" and right is not None and self.db.otp.otp != right:
                    self._otp_mismatch = True
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        if self.model is models.EmailOTP:
            return None if self._otp_mismatch else self.db.otp
        if self.model is models.User:
            return self.db.existing_user
        return None


class _SignupDb:
    def __init__(self, existing_user=None, otp=None):
        self.existing_user = existing_user
        self.otp = otp
        self.commits = 0
        self.deleted = []

    def query(self, model):
        return _SignupQuery(self, model)

    def add(self, obj):
        pass

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass


def _payload(email="cand@recruito.com", role=None, otp=""):
    return auth_mod.UserCreate(
        name="Test Candidate",
        email=email,
        password="password123",
        role=role,
        otp=otp,
    )


# ---------------------------------------------------------------------------
# BYPASS_EMAIL_OTP flag parsing (secure default)
# ---------------------------------------------------------------------------

def test_bypass_flag_defaults_to_required(otp_reloadable, monkeypatch):
    _reload_with(monkeypatch, None)
    assert auth_mod.BYPASS_EMAIL_OTP is False


@pytest.mark.parametrize(
    "value", ["true", "1", "yes", "on", " TRUE ", "Yes"]
)
def test_bypass_flag_true_variants(otp_reloadable, monkeypatch, value):
    _reload_with(monkeypatch, value)
    assert auth_mod.BYPASS_EMAIL_OTP is True


@pytest.mark.parametrize(
    "value", ["false", "0", "no", "off", ""]
)
def test_bypass_flag_false_variants(otp_reloadable, monkeypatch, value):
    _reload_with(monkeypatch, value)
    assert auth_mod.BYPASS_EMAIL_OTP is False


# ---------------------------------------------------------------------------
# OTP required by default (BYPASS_EMAIL_OTP unset/false)
# ---------------------------------------------------------------------------

def test_user_signup_requires_otp_when_not_bypassed(otp_reloadable, monkeypatch):
    _reload_with(monkeypatch, "false")
    db = _SignupDb(existing_user=None, otp=None)
    with pytest.raises(HTTPException) as exc:
        auth_mod.signup(_payload(role=models.RoleEnum.user, otp=""), db)
    assert exc.value.status_code == 400
    assert "Invalid OTP" in exc.value.detail
    assert db.commits == 0


def test_user_signup_succeeds_with_valid_otp(otp_reloadable, monkeypatch):
    _reload_with(monkeypatch, "false")
    otp = SimpleNamespace(
        email="cand@recruito.com", otp="123456", created_at=datetime.utcnow()
    )
    db = _SignupDb(existing_user=None, otp=otp)
    result = auth_mod.signup(
        _payload(role=models.RoleEnum.user, otp="123456"), db
    )
    assert result["email"] == "cand@recruito.com"
    assert result["role"] == models.RoleEnum.user
    assert db.commits == 1
    assert db.deleted == [otp]


def test_user_signup_rejects_wrong_otp(otp_reloadable, monkeypatch):
    _reload_with(monkeypatch, "false")
    otp = SimpleNamespace(
        email="cand@recruito.com", otp="111111", created_at=datetime.utcnow()
    )
    db = _SignupDb(existing_user=None, otp=otp)
    with pytest.raises(HTTPException) as exc:
        auth_mod.signup(
            _payload(role=models.RoleEnum.user, otp="222222"), db
        )
    assert exc.value.status_code == 400
    assert "Invalid OTP" in exc.value.detail


def test_user_signup_rejects_expired_otp(otp_reloadable, monkeypatch):
    _reload_with(monkeypatch, "false")
    otp = SimpleNamespace(
        email="cand@recruito.com",
        otp="123456",
        created_at=datetime.utcnow() - timedelta(minutes=6),
    )
    db = _SignupDb(existing_user=None, otp=otp)
    with pytest.raises(HTTPException) as exc:
        auth_mod.signup(
            _payload(role=models.RoleEnum.user, otp="123456"), db
        )
    assert exc.value.status_code == 400
    assert "OTP expired" in exc.value.detail
    assert db.deleted == [otp]


def test_company_signup_does_not_require_otp(otp_reloadable, monkeypatch):
    # Preserved existing behavior: OTP verification applies to candidate
    # signup; company signup does not go through the OTP flow.
    _reload_with(monkeypatch, "false")
    db = _SignupDb(existing_user=None, otp=None)
    result = auth_mod.signup(_payload(role=models.RoleEnum.company), db)
    assert result["role"] == models.RoleEnum.company
    assert db.commits == 1


def test_user_signup_still_rejects_admin_role_when_not_bypassed(
    otp_reloadable, monkeypatch
):
    # Privilege escalation is blocked before any OTP consideration.
    _reload_with(monkeypatch, "false")
    db = _SignupDb(existing_user=None, otp=None)
    with pytest.raises(HTTPException) as exc:
        auth_mod.signup(_payload(role=models.RoleEnum.admin), db)
    assert exc.value.status_code == 403
    assert db.commits == 0


# ---------------------------------------------------------------------------
# Explicit bypass mode (BYPASS_EMAIL_OTP=true)
# ---------------------------------------------------------------------------

def test_explicit_bypass_allows_user_signup_without_otp(
    otp_reloadable, monkeypatch
):
    _reload_with(monkeypatch, "true")
    db = _SignupDb(existing_user=None, otp=None)
    result = auth_mod.signup(
        _payload(role=models.RoleEnum.user, otp=""), db
    )
    assert result["role"] == models.RoleEnum.user
    assert db.commits == 1


def test_explicit_bypass_ignores_invalid_otp(otp_reloadable, monkeypatch):
    # Even with a stale/missing OTP, bypass mode signs the candidate up.
    _reload_with(monkeypatch, "yes")
    db = _SignupDb(existing_user=None, otp=None)
    result = auth_mod.signup(
        _payload(role=models.RoleEnum.user, otp="nope"), db
    )
    assert result["role"] == models.RoleEnum.user
    assert db.commits == 1


# ---------------------------------------------------------------------------
# Missing SMTP configuration error is clear and actionable
# ---------------------------------------------------------------------------

def test_send_email_otp_missing_smtp_raises_actionable_error(monkeypatch):
    monkeypatch.delenv("EMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    with pytest.raises(HTTPException) as exc:
        auth_mod.send_email_otp("cand@recruito.com", "123456")
    assert exc.value.status_code == 500
    assert "EMAIL_ADDRESS" in exc.value.detail
    assert "EMAIL_PASSWORD" in exc.value.detail
    assert "BYPASS_EMAIL_OTP" in exc.value.detail
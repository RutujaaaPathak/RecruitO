"""Password-reset endpoint tests (/forgot-password + /reset-password).

Covers the happy path, invalid / expired / reused / stale tokens, secure
(hashed) token storage, weak-password rejection, identical responses for
known and unknown emails, and rate limiting. Uses the suite's lightweight
fake-DB + reloaded-env convention (no DB, no SMTP, no network).
"""
import hashlib
import importlib
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.rate_limit as rate_limit_mod
import app.routes.auth_routes as auth_mod
from app import models
from app.utils import verify_password

IP = "198.51.100.20"
EMAIL = "cand@recruito.com"
UNKNOWN_EMAIL = "ghost@recruito.com"
NEW_PASSWORD = "NewPassw0rd!2026"
WEAK_PASSWORD = "12345"
CONFIRMATION = "If an account exists for that email, password reset instructions have been sent."
RESET_INVALID = "Invalid or expired reset token."
FORGOT_RATE_LIMIT_MSG = "Too many password reset requests. Please try again later."
RESET_RATE_LIMIT_MSG = "Too many reset attempts. Please try again later."


@pytest.fixture(autouse=True)
def _reset_limiter_state():
    """Every test starts (and ends) with a clean, in-memory limiter."""
    rate_limit_mod.reset_rate_limit()
    yield
    rate_limit_mod.reset_rate_limit()


@pytest.fixture
def auth_reloadable(monkeypatch):
    monkeypatch.setattr("app.config.load_env", lambda: None)
    yield


def _request(host=IP):
    """FastAPI-style Request stand-in exposing only ``.client.host``."""
    return SimpleNamespace(client=SimpleNamespace(host=host))


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _reload_auth(monkeypatch, *, smtp=True, rate_enabled=True, ttl="30", **overrides):
    """Reload auth_routes with password-reset env config (reload clears it)."""
    if smtp:
        monkeypatch.setenv("EMAIL_ADDRESS", "mailer@recruito.com")
        monkeypatch.setenv("EMAIL_PASSWORD", "mailer-app-password")
    else:
        monkeypatch.delenv("EMAIL_ADDRESS", raising=False)
        monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true" if rate_enabled else "false")
    if ttl is None:
        monkeypatch.delenv("RESET_TOKEN_EXPIRE_MINUTES", raising=False)
    else:
        monkeypatch.setenv("RESET_TOKEN_EXPIRE_MINUTES", ttl)
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    importlib.reload(auth_mod)


def _patch_reset_mail(monkeypatch):
    """Capture reset tokens instead of sending SMTP mail."""
    captured = {}
    monkeypatch.setattr(
        auth_mod,
        "send_password_reset_email",
        lambda email, token: captured.update({"email": email, "token": token}),
    )
    return captured


def _user_row(email=EMAIL, password="old-hash"):
    return models.User(
        name="Test Candidate",
        email=email,
        password=password,
        role=models.RoleEnum.user,
    )


def _token_row(email=EMAIL, token="rawtoken", expires=None):
    return models.PasswordResetToken(
        email=email,
        token_hash=_token_hash(token),
        expires_at=expires or (datetime.utcnow() + timedelta(minutes=30)),
    )


def _token_rows(db):
    return [r for r in db.rows if type(r) is models.PasswordResetToken]


def _user_rows(db):
    return [r for r in db.rows if type(r) is models.User]


def _forgot(db, email=EMAIL, ip=IP):
    return auth_mod.forgot_password(
        auth_mod.ForgotPasswordRequest(email=email), _request(ip), db
    )


def _reset(db, token, password=NEW_PASSWORD, ip=IP):
    return auth_mod.reset_password(
        auth_mod.ResetPasswordRequest(token=token, new_password=password),
        _request(ip),
        db,
    )


# ---------------------------------------------------------------------------
# Fake DB supporting the small query surface the reset routes use
# ---------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, db, model):
        self._db = db
        self._model = model
        self._filters = []

    def filter(self, *args, **kwargs):
        for arg in args:
            try:
                self._filters.append((arg.left.key, arg.right.value))
            except Exception:
                continue
        for key, value in kwargs.items():
            self._filters.append((key, value))
        return self

    def order_by(self, *args, **kwargs):
        return self

    def _matching(self):
        return [
            row
            for row in self._db.rows
            if type(row) is self._model
            and all(getattr(row, key) == value for key, value in self._filters)
        ]

    def first(self):
        matches = self._matching()
        return matches[0] if matches else None

    def all(self):
        return self._matching()

    def delete(self):
        matched = {id(row) for row in self._matching()}
        self._db.rows = [row for row in self._db.rows if id(row) not in matched]
        return None


class _FakeDb:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.commits = 0

    def query(self, model):
        return _FakeQuery(self, model)

    def add(self, obj):
        self.rows.append(obj)

    def delete(self, obj):
        if obj in self.rows:
            self.rows.remove(obj)

    def commit(self):
        self.commits += 1


# ---------------------------------------------------------------------------
# /forgot-password
# ---------------------------------------------------------------------------

def test_forgot_password_sends_token_and_stores_only_its_hash(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    captured = _patch_reset_mail(monkeypatch)
    db = _FakeDb([_user_row()])

    result = _forgot(db)

    assert result == {"message": CONFIRMATION}
    assert captured["email"] == EMAIL
    raw = captured["token"]
    assert len(raw) >= 43  # secrets.token_urlsafe(32)

    (row,) = _token_rows(db)
    assert row.email == EMAIL
    # Only a SHA-256 digest is persisted - never the raw token.
    assert row.token_hash == _token_hash(raw)
    assert raw not in row.token_hash
    assert row.token_hash != raw
    assert row.expires_at > datetime.utcnow()


def test_forgot_password_unknown_email_is_indistinguishable(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    captured = _patch_reset_mail(monkeypatch)
    db = _FakeDb()

    result = _forgot(db, email=UNKNOWN_EMAIL)

    assert result == {"message": CONFIRMATION}
    assert captured == {}  # no email is sent for unknown accounts
    assert _token_rows(db) == []  # and no token is minted


def test_forgot_password_known_and_unknown_answers_are_identical(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    captured = _patch_reset_mail(monkeypatch)
    known_db = _FakeDb([_user_row()])
    unknown_db = _FakeDb()

    assert _forgot(known_db) == {"message": CONFIRMATION}
    assert _forgot(unknown_db, email=UNKNOWN_EMAIL) == {
        "message": CONFIRMATION
    }
    # Only the known account actually received an email.
    assert captured["email"] == EMAIL
    assert set(captured) == {"email", "token"}


def _failing_reset_mail(monkeypatch):
    """Simulate a runtime SMTP failure after the token is stored."""
    def _fail(*args, **kwargs):
        raise HTTPException(status_code=500, detail="Failed to send email: SMTP error.")

    monkeypatch.setattr(auth_mod, "send_password_reset_email", _fail)


def test_forgot_password_smtp_runtime_failure_returns_generic_200(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    _failing_reset_mail(monkeypatch)
    db = _FakeDb([_user_row()])

    result = _forgot(db)

    # No status/detail difference: the caller just gets the generic message.
    assert result == {"message": CONFIRMATION}
    # The token may remain stored; it expires or is replaced by a later request.
    assert len(_token_rows(db)) == 1


def test_forgot_password_smtp_failure_is_indistinguishable_from_unknown_email(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    _failing_reset_mail(monkeypatch)
    known_db = _FakeDb([_user_row()])
    unknown_db = _FakeDb()

    known_response = _forgot(known_db)
    unknown_response = _forgot(unknown_db, email=UNKNOWN_EMAIL)

    assert known_response == unknown_response == {"message": CONFIRMATION}


def test_forgot_password_new_request_revokes_previous_token(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    captured = _patch_reset_mail(monkeypatch)
    db = _FakeDb([_user_row()])

    _forgot(db)
    first_token = captured["token"]
    _forgot(db)
    latest_token = captured["token"]

    (row,) = _token_rows(db)
    assert row.token_hash == _token_hash(latest_token)

    # The first token is dead; only the latest one can reset the password.
    with pytest.raises(HTTPException) as exc:
        _reset(db, first_token)
    assert exc.value.status_code == 400
    assert exc.value.detail == RESET_INVALID

    assert _reset(db, latest_token) == {
        "message": "Password reset successfully. You can now log in."
    }


@pytest.mark.parametrize(
    "ttl,minutes", [("30", 30), ("45", 45), (None, 30)]
)
def test_reset_token_expiry_is_env_configurable(
    auth_reloadable, monkeypatch, ttl, minutes
):
    _reload_auth(monkeypatch, ttl=ttl)
    captured = _patch_reset_mail(monkeypatch)
    db = _FakeDb([_user_row()])

    before = datetime.utcnow()
    _forgot(db)

    (row,) = _token_rows(db)
    elapsed = row.expires_at - before
    assert minutes * 60 - 60 <= elapsed.total_seconds() <= minutes * 60 + 60
    assert captured["email"] == EMAIL


# ---------------------------------------------------------------------------
# /reset-password
# ---------------------------------------------------------------------------

def test_reset_password_success_updates_password_and_is_single_use(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    captured = _patch_reset_mail(monkeypatch)
    db = _FakeDb([_user_row()])
    _forgot(db)
    token = captured["token"]

    result = _reset(db, token)

    assert result == {"message": "Password reset successfully. You can now log in."}
    (user,) = _user_rows(db)
    assert user.password != "old-hash"
    assert verify_password(NEW_PASSWORD, user.password)
    assert _token_rows(db) == []  # token consumed

    # Reusing the same token is rejected.
    with pytest.raises(HTTPException) as exc:
        _reset(db, token)
    assert exc.value.status_code == 400
    assert exc.value.detail == RESET_INVALID


def test_reset_password_invalid_token_fails(auth_reloadable, monkeypatch):
    _reload_auth(monkeypatch)
    db = _FakeDb([_user_row()])

    with pytest.raises(HTTPException) as exc:
        _reset(db, "not-a-real-token")
    assert exc.value.status_code == 400
    # Generic detail - never hints at whether the token/email exists.
    assert exc.value.detail == RESET_INVALID


def test_reset_password_empty_token_fails(auth_reloadable, monkeypatch):
    _reload_auth(monkeypatch)
    db = _FakeDb([_user_row()])

    with pytest.raises(HTTPException) as exc:
        _reset(db, "")
    assert exc.value.status_code == 400
    assert exc.value.detail == RESET_INVALID


def test_reset_password_expired_token_fails_and_is_cleaned_up(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    db = _FakeDb(
        [
            _user_row(),
            _token_row(token="expiredtoken", expires=datetime.utcnow() - timedelta(minutes=1)),
        ]
    )

    with pytest.raises(HTTPException) as exc:
        _reset(db, "expiredtoken")
    assert exc.value.status_code == 400
    assert exc.value.detail == RESET_INVALID
    assert _token_rows(db) == []  # stale row removed
    (user,) = _user_rows(db)
    assert user.password == "old-hash"


def test_reset_password_stale_token_for_missing_user_fails(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    db = _FakeDb([_token_row(email="deleted@recruito.com", token="orphan")])

    with pytest.raises(HTTPException) as exc:
        _reset(db, "orphan")
    assert exc.value.status_code == 400
    assert exc.value.detail == RESET_INVALID
    assert _token_rows(db) == []  # orphan token invalidated


def test_reset_password_weak_password_rejected_without_consuming_token(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    captured = _patch_reset_mail(monkeypatch)
    db = _FakeDb([_user_row()])
    _forgot(db)
    token = captured["token"]

    with pytest.raises(HTTPException) as exc:
        _reset(db, token, password=WEAK_PASSWORD)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Password must be at least 6 characters"

    (user,) = _user_rows(db)
    assert user.password == "old-hash"  # unchanged
    # The valid token survives a rejected attempt and still works.
    assert len(_token_rows(db)) == 1
    assert _reset(db, token) == {
        "message": "Password reset successfully. You can now log in."
    }


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def test_forgot_password_rate_limited_per_ip_and_email(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    _patch_reset_mail(monkeypatch)
    db = _FakeDb([_user_row()])
    limit = auth_mod.RESET_MAX_REQUESTS

    for _ in range(limit):
        result = _forgot(db)
        assert result == {"message": CONFIRMATION}

    with pytest.raises(HTTPException) as exc:
        _forgot(db)
    assert exc.value.status_code == 429
    assert exc.value.detail == FORGOT_RATE_LIMIT_MSG
    assert int(exc.value.headers["Retry-After"]) >= 1

    # Buckets are keyed per IP + email: a different caller is unaffected.
    assert _forgot(db, email="other@recruito.com") == {
        "message": CONFIRMATION
    }
    assert _forgot(db, ip="198.51.100.99") == {"message": CONFIRMATION}


def test_reset_password_rate_limited_per_ip(auth_reloadable, monkeypatch):
    _reload_auth(monkeypatch)
    db = _FakeDb([_user_row()])

    for _ in range(auth_mod.LOGIN_MAX_ATTEMPTS):
        with pytest.raises(HTTPException) as exc:
            _reset(db, "bogus")
        assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        _reset(db, "bogus")
    assert exc.value.status_code == 429
    assert exc.value.detail == RESET_RATE_LIMIT_MSG
    assert int(exc.value.headers["Retry-After"]) >= 1


def test_limiting_disabled_does_not_record_reset_buckets(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch, rate_enabled=False)
    _patch_reset_mail(monkeypatch)
    db = _FakeDb([_user_row()])

    for _ in range(10):
        _forgot(db)
    with pytest.raises(HTTPException) as exc:
        _reset(db, "bogus")
    assert exc.value.status_code == 400

    assert rate_limit_mod._limiter._buckets == {}


# ---------------------------------------------------------------------------
# Unconfigured SMTP: identical failure, no account-enumeration leak
# ---------------------------------------------------------------------------

def test_forgot_password_unconfigured_email_fails_for_everyone_identically(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch, smtp=False)
    known_db = _FakeDb([_user_row()])
    unknown_db = _FakeDb()

    with pytest.raises(HTTPException) as known_exc:
        _forgot(known_db)
    with pytest.raises(HTTPException) as unknown_exc:
        _forgot(unknown_db, email=UNKNOWN_EMAIL)

    assert known_exc.value.status_code == 500
    assert unknown_exc.value.status_code == 500
    assert known_exc.value.detail == unknown_exc.value.detail
    assert "EMAIL_ADDRESS" in known_exc.value.detail
    assert "EMAIL_PASSWORD" in known_exc.value.detail
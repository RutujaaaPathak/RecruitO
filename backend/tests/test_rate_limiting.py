"""In-memory auth rate-limiting tests (app/rate_limit.py + auth_routes wiring).

The sliding-window limiter keeps ALL state in process memory - it never
touches PostgreSQL, has no schema, and resets on restart. These tests cover
the limiter directly plus the env-driven wiring on /send-otp, /resend-otp and
/login, using the suite's lightweight fake-DB convention (no DB, no network).
"""
import importlib
from collections import deque
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import models
from app.rate_limit import (
    SlidingWindowRateLimiter,
    check_rate_limit,
    client_ip,
    reset_rate_limit,
)
import app.rate_limit as rate_limit_mod

import app.routes.auth_routes as auth_mod

IP_A = "198.51.100.7"
IP_B = "198.51.100.8"
EMAIL = "cand@recruito.com"


@pytest.fixture(autouse=True)
def _reset_limiter_state():
    """Every test starts (and ends) with a clean, in-memory limiter."""
    reset_rate_limit()
    yield
    reset_rate_limit()


@pytest.fixture
def auth_reloadable(monkeypatch):
    monkeypatch.setattr("app.config.load_env", lambda: None)
    yield


def _request(host=IP_A):
    """FastAPI-style Request stand-in exposing only ``.client.host``."""
    return SimpleNamespace(client=SimpleNamespace(host=host))


def _reload_auth(monkeypatch, enabled=None, **overrides):
    if enabled is None:
        monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    else:
        monkeypatch.setenv("RATE_LIMIT_ENABLED", enabled)
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    importlib.reload(auth_mod)


def _patch_smtp(monkeypatch):
    monkeypatch.setattr(auth_mod, "send_email_otp", lambda email, otp: None)


def _login_outcome(monkeypatch, ok):
    monkeypatch.setattr(auth_mod, "verify_password", lambda plain, hashed: ok)
    monkeypatch.setattr(auth_mod, "create_access_token", lambda payload: "fake-token")


class _OtpQuery:
    def __init__(self, model):
        self._model = model

    def filter(self, *args, **kwargs):
        return self

    def delete(self):
        return None


class _StrictOtpDb:
    """Fake DB that only supports the EmailOTP operations send/resend-otp
    perform. Any other DB touch (e.g. persisting rate-limit rows) fails loudly,
    proving rate-limit state never reaches the database."""

    def __init__(self):
        self.commits = 0
        self.added = []

    def query(self, model):
        if model is models.EmailOTP:
            return _OtpQuery(model)
        raise TypeError(f"Unexpected DB query for model {model!r}")

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1


class _LoginQuery:
    def __init__(self, user):
        self._user = user

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._user


class _StrictLoginDb:
    def __init__(self, user):
        self._user = user

    def query(self, model):
        if model is models.User:
            return _LoginQuery(self._user)
        raise TypeError(f"Unexpected DB query for model {model!r}")


def _user(email=EMAIL):
    return SimpleNamespace(
        id=1,
        name="Test Candidate",
        email=email,
        password="hashed",
        role=models.RoleEnum.user,
    )


# ---------------------------------------------------------------------------
# Sliding-window limiter basics
# ---------------------------------------------------------------------------

def test_allows_up_to_max_events():
    for _ in range(3):
        check_rate_limit("send-otp:key", 3, 60, "too many")


def test_exceeding_limit_raises_429_with_retry_after():
    for _ in range(3):
        check_rate_limit("send-otp:key", 3, 60, "too many")
    with pytest.raises(HTTPException) as exc:
        check_rate_limit("send-otp:key", 3, 60, "too many")
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) >= 1


def test_keys_are_isolated():
    for _ in range(3):
        check_rate_limit("a", 3, 60, "too many")
    # A different key is unaffected...
    check_rate_limit("b", 3, 60, "too many")
    # ...and only the exhausted key is blocked.
    with pytest.raises(HTTPException):
        check_rate_limit("a", 3, 60, "too many")


def test_sliding_window_recovers_after_window():
    class _Clock:
        def __init__(self, start=0.0):
            self.t = start

        def __call__(self):
            return self.t

    clock = _Clock()
    lim = SlidingWindowRateLimiter(now=clock)
    for _ in range(3):
        assert lim.check("k", 3, 60)[0] is True
    allowed, retry_after = lim.check("k", 3, 60)
    assert allowed is False
    assert retry_after >= 1

    clock.t += 61  # every timestamp has slid out of the 60s window
    for _ in range(3):
        assert lim.check("k", 3, 60)[0] is True


def test_client_ip_uses_peer_not_forwarding_header():
    assert client_ip(_request("203.0.113.9")) == "203.0.113.9"
    assert client_ip(SimpleNamespace(client=None)) == "unknown"


# ---------------------------------------------------------------------------
# RATE_LIMIT_ENABLED flag parsing (secure default: ON)
# ---------------------------------------------------------------------------

def test_rate_limit_enabled_defaults_true(auth_reloadable, monkeypatch):
    _reload_auth(monkeypatch)
    assert auth_mod.RATE_LIMIT_ENABLED is True


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", " TRUE ", "Yes"])
def test_rate_limit_enabled_true_variants(auth_reloadable, monkeypatch, value):
    _reload_auth(monkeypatch, enabled=value)
    assert auth_mod.RATE_LIMIT_ENABLED is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", ""])
def test_rate_limit_enabled_false_variants(auth_reloadable, monkeypatch, value):
    _reload_auth(monkeypatch, enabled=value)
    assert auth_mod.RATE_LIMIT_ENABLED is False


def test_rate_limit_enabled_false_disables_limiting(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch, enabled="false")
    _patch_smtp(monkeypatch)
    db = _StrictOtpDb()

    for _ in range(10):
        result = auth_mod.send_otp(
            auth_mod.SendOTPRequest(email=EMAIL), _request(IP_A), db
        )
    assert result["message"] == "OTP sent successfully"
    # Limiting is off: nothing was recorded even after 10 requests.
    assert rate_limit_mod._limiter._buckets == {}


def test_rate_limit_enabled_false_disables_login_limiting(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch, enabled="false")
    _login_outcome(monkeypatch, ok=False)
    db = _StrictLoginDb(_user())

    for _ in range(10):
        with pytest.raises(HTTPException) as exc:
            auth_mod.login(
                auth_mod.LoginRequest(email=EMAIL, password="wrong"),
                _request(IP_A), db,
            )
        # Only "invalid credentials" is ever raised, never a 429.
        assert exc.value.status_code == 400
    assert rate_limit_mod._limiter._buckets == {}


# ---------------------------------------------------------------------------
# /send-otp & /resend-otp: per IP + email keying, shared bucket
# ---------------------------------------------------------------------------

def test_send_otp_allows_up_to_limit_then_429(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    _patch_smtp(monkeypatch)
    db = _StrictOtpDb()
    limit = auth_mod.OTP_MAX_REQUESTS

    for _ in range(limit):
        result = auth_mod.send_otp(
            auth_mod.SendOTPRequest(email=EMAIL), _request(IP_A), db
        )
    assert result["message"] == "OTP sent successfully"

    with pytest.raises(HTTPException) as exc:
        auth_mod.send_otp(
            auth_mod.SendOTPRequest(email=EMAIL), _request(IP_A), db
        )
    assert exc.value.status_code == 429
    assert exc.value.detail == "Too many OTP requests. Please try again later."
    assert int(exc.value.headers["Retry-After"]) >= 1


def test_otp_bucket_is_keyed_by_ip_and_email(auth_reloadable, monkeypatch):
    _reload_auth(monkeypatch)
    _patch_smtp(monkeypatch)
    db = _StrictOtpDb()

    for _ in range(3):
        auth_mod.send_otp(auth_mod.SendOTPRequest(email=EMAIL), _request(IP_A), db)

    # Different IP, same email: fresh bucket.
    result = auth_mod.send_otp(
        auth_mod.SendOTPRequest(email=EMAIL), _request(IP_B), db
    )
    assert result["message"] == "OTP sent successfully"
    # Same IP, different email: fresh bucket.
    result = auth_mod.send_otp(
        auth_mod.SendOTPRequest(email="other@recruito.com"), _request(IP_A), db
    )
    assert result["message"] == "OTP sent successfully"

    # Back on the exhausted bucket: blocked.
    with pytest.raises(HTTPException) as exc:
        auth_mod.send_otp(
            auth_mod.SendOTPRequest(email=EMAIL), _request(IP_A), db
        )
    assert exc.value.status_code == 429

    keys = {
        f"otp:{IP_A}:{EMAIL.lower()}",
        f"otp:{IP_B}:{EMAIL.lower()}",
        f"otp:{IP_A}:other@recruito.com",
    }
    assert keys.issubset(rate_limit_mod._limiter._buckets)


def test_send_and_resend_otp_share_the_same_bucket(
    auth_reloadable, monkeypatch
):
    _reload_auth(monkeypatch)
    _patch_smtp(monkeypatch)
    db = _StrictOtpDb()

    auth_mod.send_otp(auth_mod.SendOTPRequest(email=EMAIL), _request(IP_A), db)
    auth_mod.send_otp(auth_mod.SendOTPRequest(email=EMAIL), _request(IP_A), db)
    auth_mod.resend_otp(auth_mod.SendOTPRequest(email=EMAIL), _request(IP_A), db)

    with pytest.raises(HTTPException) as exc:
        auth_mod.resend_otp(
            auth_mod.SendOTPRequest(email=EMAIL), _request(IP_A), db
        )
    assert exc.value.status_code == 429

    key = f"otp:{IP_A}:{EMAIL.lower()}"
    bucket = rate_limit_mod._limiter._buckets[key]
    assert len(bucket) == auth_mod.OTP_MAX_REQUESTS


# ---------------------------------------------------------------------------
# /login: brute-force bucket, reset on success only
# ---------------------------------------------------------------------------

def test_failed_login_does_not_reset_limiter(auth_reloadable, monkeypatch):
    _reload_auth(monkeypatch)
    _login_outcome(monkeypatch, ok=False)
    db = _StrictLoginDb(_user())

    for _ in range(auth_mod.LOGIN_MAX_ATTEMPTS):
        with pytest.raises(HTTPException) as exc:
            auth_mod.login(
                auth_mod.LoginRequest(email=EMAIL, password="wrong"),
                _request(IP_A), db,
            )
        assert exc.value.status_code == 400

    # Bucket is full; the next attempt is rate-limited before password checks.
    with pytest.raises(HTTPException) as exc:
        auth_mod.login(
            auth_mod.LoginRequest(email=EMAIL, password="wrong"),
            _request(IP_A), db,
        )
    assert exc.value.status_code == 429

    # Correct credentials are still rejected while the bucket is full, and the
    # bucket survives (failed logins must NOT reset it).
    with pytest.raises(HTTPException) as exc:
        auth_mod.login(
            auth_mod.LoginRequest(email=EMAIL, password="right"),
            _request(IP_A), db,
        )
    assert exc.value.status_code == 429
    key = f"login:{IP_A}:{EMAIL.lower()}"
    assert len(rate_limit_mod._limiter._buckets[key]) == auth_mod.LOGIN_MAX_ATTEMPTS


def test_successful_login_resets_limiter(auth_reloadable, monkeypatch):
    _reload_auth(monkeypatch)
    _login_outcome(monkeypatch, ok=False)
    db = _StrictLoginDb(_user())
    key = f"login:{IP_A}:{EMAIL.lower()}"

    for _ in range(auth_mod.LOGIN_MAX_ATTEMPTS - 1):
        with pytest.raises(HTTPException):
            auth_mod.login(
                auth_mod.LoginRequest(email=EMAIL, password="wrong"),
                _request(IP_A), db,
            )

    # A successful login inside the window clears this caller's bucket.
    _login_outcome(monkeypatch, ok=True)
    result = auth_mod.login(
        auth_mod.LoginRequest(email=EMAIL, password="right"),
        _request(IP_A), db,
    )
    assert result["access_token"] == "fake-token"
    assert key not in rate_limit_mod._limiter._buckets

    # The failed-attempt allowance is fresh again (the next failure would be a
    # 429 immediately if the successful login had NOT reset the bucket).
    _login_outcome(monkeypatch, ok=False)
    for _ in range(auth_mod.LOGIN_MAX_ATTEMPTS):
        with pytest.raises(HTTPException) as exc:
            auth_mod.login(
                auth_mod.LoginRequest(email=EMAIL, password="wrong"),
                _request(IP_A), db,
            )
        assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        auth_mod.login(
            auth_mod.LoginRequest(email=EMAIL, password="wrong"),
            _request(IP_A), db,
        )
    assert exc.value.status_code == 429


# ---------------------------------------------------------------------------
# State is in-process only - never PostgreSQL
# ---------------------------------------------------------------------------

def test_rate_limit_state_never_touches_database(auth_reloadable, monkeypatch):
    _reload_auth(monkeypatch)
    _patch_smtp(monkeypatch)
    _login_outcome(monkeypatch, ok=False)
    otp_db = _StrictOtpDb()
    login_db = _StrictLoginDb(_user())

    for _ in range(2):
        auth_mod.send_otp(auth_mod.SendOTPRequest(email=EMAIL), _request(IP_A), otp_db)
    for _ in range(2):
        with pytest.raises(HTTPException):
            auth_mod.login(
                auth_mod.LoginRequest(email=EMAIL, password="wrong"),
                _request(IP_A), login_db,
            )

    # IP + email buckets live purely as in-memory deques of timestamps.
    assert f"otp:{IP_A}:{EMAIL.lower()}" in rate_limit_mod._limiter._buckets
    assert f"login:{IP_A}:{EMAIL.lower()}" in rate_limit_mod._limiter._buckets
    assert all(
        isinstance(value, deque)
        for value in rate_limit_mod._limiter._buckets.values()
    )
    # The only DB writes were the legitimate EmailOTP rows. The strict fakes
    # raise TypeError on any unexpected model/query, so any attempt to persist
    # rate-limit state would have failed the test.
    assert otp_db.commits == 2
    assert all(isinstance(row, models.EmailOTP) for row in otp_db.added)

    # Clearing the limiter is a pure-memory operation.
    reset_rate_limit()
    assert rate_limit_mod._limiter._buckets == {}
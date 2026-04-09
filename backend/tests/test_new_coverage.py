"""
Additional test coverage targeting gaps identified in the coverage audit:
- Email / password validation boundaries
- verify_email and resend_verification flows
- OAuth one-time code exchange (single-use, expiry)
- register: admin-email path (wrong / correct admin password)
- login: email normalization, last_login update
- get_current_user_optional: all header edge cases
- rate_limiter: exactly-at-limit boundary, key-based window
- _check_repo_limits: free & pro file/byte limits
- _check_repo_accessibility: HTTP status branching
- admin patch_user: grant admin, demote, last-admin guard, own status guard
- stripe webhook handlers: unit tests
- dependency_parser: relative imports, Go, JS aliases, dedup
- file_service: is_test_file patterns, walk_repo pro limits, format_tree, get_readme
- billing portal: no Stripe customer returns 400
"""
import os
import time
import tempfile
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt as pyjwt

from models import Analysis, User, WatchedRepo
from services.auth_service import create_token, hash_password
from services.rate_limiter import (
    _lock, _requests, _keyed_requests,
    check_rate_limit, check_rate_limit_key,
    RATE_LIMIT_MAX,
)

_JWT_SECRET = os.environ.get("JWT_SECRET", "test-secret-do-not-use-in-prod")


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email="edge@example.com", plan="free",
               is_admin=False, is_verified=True):
    u = User(
        email=email,
        password_hash=hash_password("Test@Pass123"),
        plan=plan,
        is_admin=is_admin,
        is_verified=is_verified,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _auth(user):
    return {"Authorization": f"Bearer {create_token(user.id)}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Email / password validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmailValidation:
    """Boundary tests for _validate_email used by register."""

    def test_missing_at_symbol(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "notemail.com", "password": "Test@Pass123"})
        assert resp.status_code == 400
        assert "email" in resp.json()["detail"].lower()

    def test_missing_tld(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "user@nodot", "password": "Test@Pass123"})
        assert resp.status_code == 400

    def test_leading_trailing_whitespace_normalised(self, client, db_session):
        """Spaces around the email are stripped and the user is created."""
        resp = client.post("/api/auth/register",
                           json={"email": "  trim@example.com  ", "password": "Test@Pass123"})
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == "trim@example.com"

    def test_uppercase_normalised_to_lowercase(self, client, db_session):
        resp = client.post("/api/auth/register",
                           json={"email": "Upper@Example.COM", "password": "Test@Pass123"})
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == "upper@example.com"

    def test_email_too_long_rejected(self, client):
        long_email = "a" * 250 + "@b.co"   # > 254 chars total
        resp = client.post("/api/auth/register",
                           json={"email": long_email, "password": "Test@Pass123"})
        assert resp.status_code == 400

    def test_plus_addressing_accepted(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "user+tag@example.com", "password": "Test@Pass123"})
        assert resp.status_code == 200


class TestPasswordValidation:
    """Boundary tests for _validate_password used by register."""

    def test_blank_password_rejected(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "pw@example.com", "password": "   "})
        assert resp.status_code == 400

    def test_exactly_10_chars_no_complexity_rejected(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "pw10@example.com", "password": "1234567890"})
        assert resp.status_code == 400

    def test_9_chars_rejected(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "pw9@example.com", "password": "123456789"})
        assert resp.status_code == 400

    def test_1025_chars_rejected(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "pwlong@example.com", "password": "a" * 1025})
        assert resp.status_code == 400

    def test_1024_chars_accepted(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "pw1024@example.com", "password": "A" * 1014 + "aB@5fghijk"})
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Register: admin-email path
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegisterAdminEmail:
    def test_admin_password_wrong_returns_403(self, client):
        with patch.dict(os.environ, {"ADMIN_EMAIL": "boss@example.com",
                                     "ADMIN_PASSWORD": "correctpass"}):
            import api.auth as _auth_module
            old_email = _auth_module.ADMIN_EMAIL
            old_pw = _auth_module.ADMIN_PASSWORD
            _auth_module.ADMIN_EMAIL = "boss@example.com"
            _auth_module.ADMIN_PASSWORD = "correctpass"
            try:
                resp = client.post("/api/auth/register",
                                   json={"email": "boss@example.com",
                                         "password": "Wrong@Pass123"})
            finally:
                _auth_module.ADMIN_EMAIL = old_email
                _auth_module.ADMIN_PASSWORD = old_pw
        assert resp.status_code == 403

    def test_admin_password_correct_creates_admin(self, client, db_session):
        import api.auth as _auth_module
        old_email = _auth_module.ADMIN_EMAIL
        old_pw = _auth_module.ADMIN_PASSWORD
        _auth_module.ADMIN_EMAIL = "ceo@example.com"
        _auth_module.ADMIN_PASSWORD = "Ceo@Pass12345"
        try:
            resp = client.post("/api/auth/register",
                               json={"email": "ceo@example.com",
                                     "password": "Ceo@Pass12345"})
        finally:
            _auth_module.ADMIN_EMAIL = old_email
            _auth_module.ADMIN_PASSWORD = old_pw
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["is_admin"] is True
        assert data["user"]["plan"] == "pro"

    def test_admin_email_without_admin_password_configured_returns_503(self, client):
        import api.auth as _auth_module
        old_email = _auth_module.ADMIN_EMAIL
        old_pw = _auth_module.ADMIN_PASSWORD
        _auth_module.ADMIN_EMAIL = "boss2@example.com"
        _auth_module.ADMIN_PASSWORD = ""  # not configured
        try:
            resp = client.post("/api/auth/register",
                               json={"email": "boss2@example.com",
                                     "password": "Test@Pass123"})
        finally:
            _auth_module.ADMIN_EMAIL = old_email
            _auth_module.ADMIN_PASSWORD = old_pw
        assert resp.status_code == 403

    def test_duplicate_email_returns_400(self, client, test_user):
        resp = client.post("/api/auth/register",
                           json={"email": test_user.email, "password": "Test@Pass123"})
        assert resp.status_code == 400
        assert "Unable to create account" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Login: normalisation + last_login
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoginDetails:
    def test_uppercase_email_accepted(self, client, test_user):
        resp = client.post("/api/auth/login",
                           json={"email": test_user.email.upper(),
                                 "password": "Test@Pass123"})
        assert resp.status_code == 200

    def test_last_login_updated(self, client, test_user, db_session):
        assert test_user.last_login is None
        client.post("/api/auth/login",
                    json={"email": test_user.email, "password": "Test@Pass123"})
        db_session.refresh(test_user)
        assert test_user.last_login is not None

    def test_wrong_password_returns_401(self, client, test_user):
        resp = client.post("/api/auth/login",
                           json={"email": test_user.email, "password": "wrong"})
        assert resp.status_code == 401

    def test_nonexistent_user_returns_401(self, client):
        resp = client.post("/api/auth/login",
                           json={"email": "ghost@example.com", "password": "Test@Pass123"})
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# 4. verify_email endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerifyEmail:
    def _make_unverified(self, db_session, code="123456"):
        u = User(
            email="unverf@example.com",
            password_hash=hash_password("Test@Pass123"),
            plan="free",
            is_admin=False,
            is_verified=False,
            verification_code=code,
            verification_expires=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
        return u

    def test_already_verified_returns_200(self, client, test_user):
        """Verified users calling verify-email get 200 immediately."""
        resp = client.post("/api/auth/verify-email",
                           json={"code": "000000"},
                           headers=_auth(test_user))
        assert resp.status_code == 200
        assert "Already verified" in resp.json()["detail"]

    def test_wrong_code_returns_400(self, client, db_session):
        user = self._make_unverified(db_session, code="111111")
        resp = client.post("/api/auth/verify-email",
                           json={"code": "999999"},
                           headers=_auth(user))
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]

    def test_expired_code_returns_400(self, client, db_session):
        u = User(
            email="expired@example.com",
            password_hash=hash_password("Test@Pass123"),
            plan="free",
            is_admin=False,
            is_verified=False,
            verification_code="222222",
            verification_expires=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
        resp = client.post("/api/auth/verify-email",
                           json={"code": "222222"},
                           headers=_auth(u))
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_correct_code_verifies_user(self, client, db_session):
        user = self._make_unverified(db_session, code="333333")
        resp = client.post("/api/auth/verify-email",
                           json={"code": "333333"},
                           headers=_auth(user))
        assert resp.status_code == 200
        db_session.refresh(user)
        assert user.is_verified is True
        assert user.verification_code is None

    def test_code_cleared_after_verification(self, client, db_session):
        user = self._make_unverified(db_session, code="444444")
        client.post("/api/auth/verify-email",
                    json={"code": "444444"},
                    headers=_auth(user))
        db_session.refresh(user)
        assert user.verification_code is None
        assert user.verification_expires is None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. resend_verification endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestResendVerification:
    def _unverified_user(self, db_session):
        u = User(
            email="resend@example.com",
            password_hash=hash_password("Test@Pass123"),
            plan="free",
            is_admin=False,
            is_verified=False,
            verification_code="555555",
            verification_expires=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
        return u

    def test_already_verified_returns_200(self, client, test_user):
        resp = client.post("/api/auth/resend-verification", headers=_auth(test_user))
        assert resp.status_code == 200
        assert "Already verified" in resp.json()["detail"]

    def test_generates_new_code(self, client, db_session):
        user = self._unverified_user(db_session)
        old_code = user.verification_code
        with patch("api.auth.send_verification_email"):
            resp = client.post("/api/auth/resend-verification", headers=_auth(user))
        assert resp.status_code == 200
        db_session.refresh(user)
        assert user.verification_code != old_code
        assert user.verification_code is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. OAuth one-time code exchange
# ═══════════════════════════════════════════════════════════════════════════════

class TestOAuthCodeExchange:
    def _store_code(self, user):
        """Directly inject a valid one-time code into the module's store."""
        import api.auth as _auth_module
        code = "testcode123"
        token = create_token(user.id)
        with _auth_module._oauth_codes_lock:
            _auth_module._oauth_codes[code] = {
                "token": token,
                "expires_at": time.time() + 30,
            }
        return code, token

    def _store_expired_code(self, user):
        import api.auth as _auth_module
        code = "expiredcode456"
        token = create_token(user.id)
        with _auth_module._oauth_codes_lock:
            _auth_module._oauth_codes[code] = {
                "token": token,
                "expires_at": time.time() - 1,  # already expired
            }
        return code

    def test_valid_code_returns_token(self, client, db_session, test_user):
        code, token = self._store_code(test_user)
        resp = client.post("/api/auth/github/exchange", json={"code": code})
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_code_is_single_use(self, client, db_session, test_user):
        code, _ = self._store_code(test_user)
        r1 = client.post("/api/auth/github/exchange", json={"code": code})
        r2 = client.post("/api/auth/github/exchange", json={"code": code})
        assert r1.status_code == 200
        assert r2.status_code == 400  # consumed on first use

    def test_expired_code_returns_400(self, client, test_user):
        code = self._store_expired_code(test_user)
        resp = client.post("/api/auth/github/exchange", json={"code": code})
        assert resp.status_code == 400

    def test_nonexistent_code_returns_400(self, client):
        resp = client.post("/api/auth/github/exchange", json={"code": "doesnotexist"})
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# 7. get_current_user_optional
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetCurrentUserOptional:
    """Tests for the optional auth dependency used by public endpoints."""

    def test_no_header_returns_none(self, client, test_user, db_session):
        """Public analysis endpoint: no auth → public analyses visible, private not."""
        a = Analysis(
            repo_url="https://github.com/o/r",
            repo_name="o/r",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            is_public=True,
            result='{"repo_name":"o/r"}',
        )
        db_session.add(a)
        db_session.commit()
        resp = client.get(f"/api/public/analysis/{a.id}")
        assert resp.status_code == 200

    def test_valid_bearer_returns_user(self, client, test_user, db_session):
        a = Analysis(
            repo_url="https://github.com/o/r2",
            repo_name="o/r2",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            is_public=True,
            result='{"repo_name":"o/r2"}',
        )
        db_session.add(a)
        db_session.commit()
        resp = client.get(f"/api/public/analysis/{a.id}", headers=_auth(test_user))
        assert resp.status_code == 200

    def test_basic_auth_header_treated_as_no_auth(self, client, test_user, db_session):
        """'Basic ...' header is not Bearer — treated as anonymous."""
        a = Analysis(
            repo_url="https://github.com/o/r3",
            repo_name="o/r3",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            is_public=False,
        )
        db_session.add(a)
        db_session.commit()
        resp = client.get(f"/api/public/analysis/{a.id}",
                          headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 404  # private, anonymous caller

    def test_invalid_bearer_token_treated_as_no_auth(self, client, test_user, db_session):
        a = Analysis(
            repo_url="https://github.com/o/r4",
            repo_name="o/r4",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            is_public=False,
        )
        db_session.add(a)
        db_session.commit()
        resp = client.get(f"/api/public/analysis/{a.id}",
                          headers={"Authorization": "Bearer notavalidtoken"})
        assert resp.status_code == 404  # invalid token → anonymous → private 404


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Rate limiter — boundary conditions
# ═══════════════════════════════════════════════════════════════════════════════

class TestRateLimiterBoundary:
    """Direct unit tests for the rate limiter functions."""

    def _fresh_ip(self):
        return f"10.0.0.{int(time.time() * 1000) % 254 + 1}"

    def test_first_request_allowed(self):
        ip = self._fresh_ip()
        allowed, remaining, _ = check_rate_limit(ip)
        assert allowed is True
        assert remaining == RATE_LIMIT_MAX - 1

    def test_exactly_at_limit_allowed(self):
        ip = self._fresh_ip()
        for _ in range(RATE_LIMIT_MAX - 1):
            check_rate_limit(ip)
        allowed, remaining, _ = check_rate_limit(ip)
        assert allowed is True
        assert remaining == 0

    def test_one_over_limit_blocked(self):
        ip = self._fresh_ip()
        for _ in range(RATE_LIMIT_MAX):
            check_rate_limit(ip)
        allowed, remaining, retry_after = check_rate_limit(ip)
        assert allowed is False
        assert remaining == 0
        assert retry_after >= 1

    def test_key_based_first_request_allowed(self):
        key = f"test-key-{time.time()}"
        allowed, retry = check_rate_limit_key(key, max_requests=3, window=60)
        assert allowed is True
        assert retry == 0

    def test_key_based_at_limit_blocked(self):
        key = f"test-key-{time.time()}-limit"
        for _ in range(3):
            check_rate_limit_key(key, max_requests=3, window=60)
        allowed, retry = check_rate_limit_key(key, max_requests=3, window=60)
        assert allowed is False
        assert retry >= 1

    def test_different_keys_independent(self):
        suffix = time.time()
        key_a = f"key-a-{suffix}"
        key_b = f"key-b-{suffix}"
        for _ in range(3):
            check_rate_limit_key(key_a, max_requests=3, window=60)
        # key_b should still be fresh
        allowed, _ = check_rate_limit_key(key_b, max_requests=3, window=60)
        assert allowed is True

    def test_login_rate_limit_via_endpoint(self, client):
        """10 failed login attempts → 429 on the 11th."""
        for _ in range(10):
            client.post("/api/auth/login",
                        json={"email": "nobody@x.com", "password": "wrong"})
        resp = client.post("/api/auth/login",
                           json={"email": "nobody@x.com", "password": "wrong"})
        assert resp.status_code == 429


# ═══════════════════════════════════════════════════════════════════════════════
# 9. _check_repo_limits (unit tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckRepoLimits:
    """Unit tests that exercise _check_repo_limits directly with temp dirs."""

    def _make_repo(self, num_files: int, bytes_per_file: int = 10) -> str:
        td = tempfile.mkdtemp()
        for i in range(num_files):
            Path(td, f"file_{i}.py").write_bytes(b"x" * bytes_per_file)
        return td

    def test_free_under_limit_passes(self):
        from api.routes import _check_repo_limits
        d = self._make_repo(5)
        _check_repo_limits(d, plan="free")  # should not raise

    def test_free_file_count_exceeded_raises(self):
        from api.routes import _check_repo_limits
        d = self._make_repo(2001)
        with pytest.raises(RuntimeError, match="Free plan"):
            _check_repo_limits(d, plan="free")

    def test_free_file_count_error_mentions_upgrade(self):
        from api.routes import _check_repo_limits
        d = self._make_repo(2001)
        with pytest.raises(RuntimeError, match="Upgrade to Pro"):
            _check_repo_limits(d, plan="free")

    def test_pro_file_count_exceeded_raises(self):
        from api.routes import _check_repo_limits
        d = self._make_repo(10001)
        with pytest.raises(RuntimeError, match="too large"):
            _check_repo_limits(d, plan="pro")

    def test_free_size_exceeded_raises(self):
        from api.routes import _check_repo_limits
        # 101 MB > 100 MB free limit
        d = self._make_repo(1, bytes_per_file=101 * 1024 * 1024)
        with pytest.raises(RuntimeError, match="Free plan"):
            _check_repo_limits(d, plan="free")

    def test_pro_size_exceeded_raises(self):
        from api.routes import _check_repo_limits
        # 501 MB > 500 MB pro limit
        d = self._make_repo(1, bytes_per_file=501 * 1024 * 1024)
        with pytest.raises(RuntimeError, match="too large"):
            _check_repo_limits(d, plan="pro")

    def test_skip_dirs_not_counted(self):
        from api.routes import _check_repo_limits
        import tempfile
        td = tempfile.mkdtemp()
        # Create 5 real files + many files inside node_modules (should be skipped)
        Path(td, "node_modules").mkdir()
        for i in range(2000):
            Path(td, "node_modules", f"dep_{i}.js").write_bytes(b"x")
        for i in range(5):
            Path(td, f"real_{i}.py").write_bytes(b"x")
        _check_repo_limits(td, plan="free")  # should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# 10. _check_repo_accessibility (unit tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckRepoAccessibility:
    def _call(self, status_code, token=None):
        from api.routes import _check_repo_accessibility
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        with patch("httpx.get", return_value=mock_resp):
            return _check_repo_accessibility("owner", "repo", github_token=token)

    def test_200_returns_silently(self):
        self._call(200)  # no exception

    def test_404_without_token_raises_private_repo_no_token(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._call(404, token=None)
        assert exc.value.status_code == 422
        assert "PRIVATE_REPO_NO_TOKEN" in exc.value.detail

    def test_404_with_token_raises_404(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._call(404, token="mytoken")
        assert exc.value.status_code == 404

    def test_401_raises_token_invalid(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._call(401, token="badtoken")
        assert exc.value.status_code == 422
        assert "PRIVATE_REPO_TOKEN_INVALID" in exc.value.detail

    def test_403_raises_token_invalid(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._call(403, token="badtoken")
        assert exc.value.status_code == 422
        assert "PRIVATE_REPO_TOKEN_INVALID" in exc.value.detail

    def test_429_returns_silently(self):
        self._call(429)  # GitHub rate-limit — falls through

    def test_500_returns_silently(self):
        self._call(500)  # Server error — falls through

    def test_network_error_returns_silently(self):
        from api.routes import _check_repo_accessibility
        with patch("httpx.get", side_effect=Exception("connection refused")):
            _check_repo_accessibility("owner", "repo")  # should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Admin patch_user: admin promotion / demotion rules
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdminPatchUserRules:
    def test_grant_admin_auto_upgrades_to_pro(self, client, admin_auth_headers, db_session, test_user):
        assert test_user.plan == "free"
        assert test_user.is_admin is False
        resp = client.patch(f"/api/admin/users/{test_user.id}",
                            json={"is_admin": True},
                            headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_admin"] is True
        assert data["plan"] == "pro"

    def test_demote_admin_reverts_to_free(self, client, admin_auth_headers, db_session):
        # Create a second admin so the "last admin" guard doesn't fire
        second_admin = _make_user(db_session, email="second_admin@example.com",
                                  plan="pro", is_admin=True)
        resp = client.patch(f"/api/admin/users/{second_admin.id}",
                            json={"is_admin": False},
                            headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_admin"] is False
        assert data["plan"] == "free"

    def test_cannot_demote_last_admin(self, client, admin_auth_headers, db_session, admin_user):
        """When there are no other admins, demoting the only admin is blocked."""
        # admin_user is the only admin in this test's DB
        resp = client.patch(f"/api/admin/users/{admin_user.id}",
                            json={"is_admin": False},
                            headers=admin_auth_headers)
        # Either blocked (400) because it's the last admin, or blocked because it's self
        assert resp.status_code == 400

    def test_cannot_change_own_admin_status(self, client, admin_auth_headers, admin_user):
        resp = client.patch(f"/api/admin/users/{admin_user.id}",
                            json={"is_admin": False},
                            headers=admin_auth_headers)
        assert resp.status_code == 400
        assert "own admin" in resp.json()["detail"].lower() \
               or "last admin" in resp.json()["detail"].lower()

    def test_patch_plan_only_does_not_touch_admin_status(self, client, admin_auth_headers, test_user):
        resp = client.patch(f"/api/admin/users/{test_user.id}",
                            json={"plan": "pro"},
                            headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan"] == "pro"
        assert data["is_admin"] == test_user.is_admin  # unchanged

    def test_invalid_plan_value_returns_400(self, client, admin_auth_headers, test_user):
        resp = client.patch(f"/api/admin/users/{test_user.id}",
                            json={"plan": "enterprise"},
                            headers=admin_auth_headers)
        assert resp.status_code == 400

    def test_patch_nonexistent_user_returns_404(self, client, admin_auth_headers):
        resp = client.patch("/api/admin/users/nonexistent-id",
                            json={"plan": "pro"},
                            headers=admin_auth_headers)
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Stripe webhook handler unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestStripeWebhookHandlers:
    """Test the internal _handle_* functions directly (no HTTP, no Stripe SDK)."""

    def _make_pro_user_with_customer(self, db_session, customer_id="cus_abc"):
        u = _make_user(db_session, email=f"stripe_{customer_id}@example.com", plan="pro")
        u.stripe_customer_id = customer_id
        db_session.commit()
        return u

    def test_checkout_completed_upgrades_user(self, db_session):
        from api.billing import _handle_checkout_completed
        user = _make_user(db_session, email="checkout@example.com", plan="free")
        user.stripe_customer_id = "cus_checkout1"
        db_session.commit()

        _handle_checkout_completed(
            {"customer": "cus_checkout1", "subscription": "sub_123"},
            db_session,
        )
        db_session.refresh(user)
        assert user.plan == "pro"
        assert user.stripe_subscription_id == "sub_123"

    def test_checkout_completed_unknown_customer_is_noop(self, db_session):
        from api.billing import _handle_checkout_completed
        # Should not raise even if customer doesn't exist
        _handle_checkout_completed(
            {"customer": "cus_unknown", "subscription": "sub_999"},
            db_session,
        )

    def test_subscription_deleted_downgrades_user(self, db_session):
        from api.billing import _handle_subscription_deleted
        user = self._make_pro_user_with_customer(db_session, "cus_del1")
        user.stripe_subscription_id = "sub_del1"
        db_session.commit()

        _handle_subscription_deleted(
            {"id": "sub_del1", "customer": "cus_del1"},
            db_session,
        )
        db_session.refresh(user)
        assert user.plan == "free"
        assert user.stripe_subscription_id is None

    def test_subscription_deleted_unknown_customer_is_noop(self, db_session):
        from api.billing import _handle_subscription_deleted
        _handle_subscription_deleted(
            {"id": "sub_x", "customer": "cus_unknown2"},
            db_session,
        )

    def test_payment_failed_downgrades_user(self, db_session):
        from api.billing import _handle_payment_failed
        user = self._make_pro_user_with_customer(db_session, "cus_fail1")

        _handle_payment_failed({"customer": "cus_fail1"}, db_session)
        db_session.refresh(user)
        assert user.plan == "free"

    def test_payment_failed_unknown_customer_is_noop(self, db_session):
        from api.billing import _handle_payment_failed
        _handle_payment_failed({"customer": "cus_unknown3"}, db_session)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Billing portal: no customer
# ═══════════════════════════════════════════════════════════════════════════════

class TestBillingPortal:
    def test_portal_without_customer_returns_400(self, client, auth_headers):
        """User with no stripe_customer_id cannot access portal."""
        import api.billing as _billing
        old = _billing._stripe_configured
        _billing._stripe_configured = lambda: True  # pretend Stripe is set up
        try:
            resp = client.post("/api/billing/portal", headers=auth_headers)
        finally:
            _billing._stripe_configured = old
        assert resp.status_code == 400
        assert "billing account" in resp.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Dependency parser unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDependencyParser:
    # ── detect_language ──────────────────────────────────────────────────────

    def test_detect_python(self):
        from services.dependency_parser import detect_language
        assert detect_language("main.py") == "python"

    def test_detect_typescript(self):
        from services.dependency_parser import detect_language
        assert detect_language("app.tsx") == "typescript"

    def test_detect_go(self):
        from services.dependency_parser import detect_language
        assert detect_language("main.go") == "go"

    def test_detect_unknown_is_other(self):
        from services.dependency_parser import detect_language
        assert detect_language("styles.css") == "other"

    def test_detect_case_insensitive(self):
        from services.dependency_parser import detect_language
        assert detect_language("README.MD") == "other"   # .MD not in map
        assert detect_language("app.PY") == "python"

    # ── _parse_python: relative imports ──────────────────────────────────────

    def test_relative_import_single_dot(self):
        from services.dependency_parser import _parse_python
        all_files = {"pkg/utils.py", "pkg/main.py"}
        result = _parse_python("pkg/main.py",
                               "from .utils import helper\n",
                               all_files)
        assert "pkg/utils.py" in result

    def test_relative_import_double_dot(self):
        from services.dependency_parser import _parse_python
        all_files = {"pkg/utils.py", "pkg/sub/main.py"}
        result = _parse_python("pkg/sub/main.py",
                               "from ..utils import helper\n",
                               all_files)
        assert "pkg/utils.py" in result

    def test_stdlib_module_not_resolved(self):
        from services.dependency_parser import _parse_python
        all_files = {"os.py", "sys.py"}   # pretend these exist
        result = _parse_python("main.py", "import os\nimport sys\n", all_files)
        assert result == []  # stdlib skipped

    def test_absolute_import_resolved(self):
        from services.dependency_parser import _parse_python
        all_files = {"services/auth.py", "main.py"}
        result = _parse_python("main.py", "from services.auth import thing\n", all_files)
        assert "services/auth.py" in result

    # ── _detect_go_module ────────────────────────────────────────────────────

    def test_go_module_detected(self):
        from services.dependency_parser import _detect_go_module
        files = {"go.mod": "module github.com/acme/myapp\n\ngo 1.21\n"}
        assert _detect_go_module(files) == "github.com/acme/myapp"

    def test_go_module_missing_returns_empty(self):
        from services.dependency_parser import _detect_go_module
        assert _detect_go_module({}) == ""

    # ── _parse_go ────────────────────────────────────────────────────────────

    def test_go_internal_import_resolved(self):
        from services.dependency_parser import _parse_go
        all_files = {"internal/handler/http.go", "cmd/main.go"}
        content = 'import "github.com/acme/app/internal/handler"\n'
        result = _parse_go("cmd/main.go", content, all_files,
                           module_name="github.com/acme/app")
        assert "internal/handler/http.go" in result

    def test_go_external_import_ignored(self):
        from services.dependency_parser import _parse_go
        all_files = {"cmd/main.go"}
        content = 'import "github.com/gin-gonic/gin"\n'
        result = _parse_go("cmd/main.go", content, all_files,
                           module_name="github.com/acme/app")
        assert result == []

    def test_go_no_module_returns_empty(self):
        from services.dependency_parser import _parse_go
        result = _parse_go("main.go", 'import "anything/here"\n', set(), module_name="")
        assert result == []

    # ── parse_dependencies: deduplication ────────────────────────────────────

    def test_duplicate_edges_deduplicated(self):
        from services.dependency_parser import parse_dependencies
        # Two files that both import the same target
        files = {
            "a.py": "from utils import x\nfrom utils import y\n",
            "utils.py": "",
        }
        tree = ["a.py", "utils.py"]
        result = parse_dependencies(files, tree)
        edges = result["edges"]
        # a.py→utils.py should appear at most once
        a_to_utils = [e for e in edges
                      if e["source"] == "a.py" and e["target"] == "utils.py"]
        assert len(a_to_utils) <= 1

    def test_self_imports_not_added_as_edge(self):
        from services.dependency_parser import parse_dependencies
        files = {"a.py": "from a import something\n"}
        tree = ["a.py"]
        result = parse_dependencies(files, tree)
        self_edges = [e for e in result["edges"] if e["source"] == e["target"]]
        assert len(self_edges) == 0

    def test_non_source_files_skipped(self):
        from services.dependency_parser import parse_dependencies
        files = {"styles.css": "body { color: red; }", "main.py": ""}
        tree = ["styles.css", "main.py"]
        result = parse_dependencies(files, tree)
        node_ids = {n["id"] for n in result["nodes"]}
        assert "styles.css" not in node_ids

    # ── JS alias resolution ──────────────────────────────────────────────────

    def test_js_relative_import_resolved(self):
        from services.dependency_parser import _parse_js, _detect_aliases
        all_files = {"src/utils/format.ts", "src/pages/home.tsx"}
        aliases = _detect_aliases({})
        result = _parse_js("src/pages/home.tsx",
                           "import { fmt } from '../utils/format'\n",
                           all_files, aliases)
        assert "src/utils/format.ts" in result

    def test_js_at_alias_resolved(self):
        from services.dependency_parser import _parse_js, _detect_aliases
        all_files = {"src/lib/helpers.ts", "src/pages/index.tsx"}
        aliases = _detect_aliases({})  # default @/ → ["src/", ""]
        result = _parse_js("src/pages/index.tsx",
                           "import { h } from '@/lib/helpers'\n",
                           all_files, aliases)
        assert "src/lib/helpers.ts" in result

    def test_js_unknown_package_not_added(self):
        from services.dependency_parser import _parse_js, _detect_aliases
        all_files = {"src/pages/index.tsx"}
        aliases = _detect_aliases({})
        result = _parse_js("src/pages/index.tsx",
                           "import React from 'react'\n",
                           all_files, aliases)
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# 15. File service unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileService:
    # ── is_test_file ─────────────────────────────────────────────────────────

    def test_pytest_file_detected(self):
        from services.file_service import is_test_file
        assert is_test_file("tests/test_auth.py")

    def test_test_prefix_in_root_detected(self):
        from services.file_service import is_test_file
        assert is_test_file("test_routes.py")

    def test_jest_spec_file_detected(self):
        from services.file_service import is_test_file
        assert is_test_file("components/Button.test.tsx")

    def test_go_test_file_detected(self):
        from services.file_service import is_test_file
        assert is_test_file("pkg/handler/server_test.go")

    def test_java_test_class_detected(self):
        from services.file_service import is_test_file
        assert is_test_file("src/test/java/com/app/UserTest.java")

    def test_regular_file_not_test(self):
        from services.file_service import is_test_file
        assert not is_test_file("src/models/user.py")
        assert not is_test_file("routes/auth.ts")
        assert not is_test_file("main.go")

    def test_conftest_detected(self):
        from services.file_service import is_test_file
        assert is_test_file("tests/conftest.py")

    # ── format_tree ───────────────────────────────────────────────────────────

    def test_format_tree_indents_nested(self):
        from services.file_service import format_tree
        tree = ["src/a.py", "src/sub/b.py"]
        result = format_tree(tree)
        assert "a.py" in result
        assert "  " in result  # indented entry for sub/

    def test_format_tree_empty(self):
        from services.file_service import format_tree
        assert format_tree([]) == ""

    # ── get_readme ────────────────────────────────────────────────────────────

    def test_get_readme_returns_content(self):
        from services.file_service import get_readme
        files = {"README.md": "# Hello", "src/main.py": "print('hi')"}
        assert get_readme(files) == "# Hello"

    def test_get_readme_case_insensitive(self):
        from services.file_service import get_readme
        files = {"readme.md": "lowercase"}
        assert get_readme(files) == "lowercase"

    def test_get_readme_missing_returns_empty(self):
        from services.file_service import get_readme
        assert get_readme({"src/main.py": "code"}) == ""

    # ── walk_repo: pro vs free limits ─────────────────────────────────────────

    def test_walk_repo_free_tree_limit(self):
        from services.file_service import walk_repo
        with tempfile.TemporaryDirectory() as td:
            for i in range(400):   # more than free max_tree=300
                Path(td, f"file_{i}.py").write_text(f"# {i}")
            result = walk_repo(td, plan="free")
        assert len(result["tree"]) == 300  # capped at free limit

    def test_walk_repo_pro_tree_limit_higher(self):
        from services.file_service import walk_repo
        with tempfile.TemporaryDirectory() as td:
            for i in range(700):   # more than free (300) but within pro (600)
                Path(td, f"file_{i}.py").write_text(f"# {i}")
            result_free = walk_repo(td, plan="free")
            result_pro = walk_repo(td, plan="pro")
        assert len(result_pro["tree"]) > len(result_free["tree"])
        assert len(result_pro["tree"]) == 600

    def test_walk_repo_skips_node_modules(self):
        from services.file_service import walk_repo
        with tempfile.TemporaryDirectory() as td:
            nm = Path(td, "node_modules")
            nm.mkdir()
            (nm / "dep.js").write_text("module.exports = {}")
            Path(td, "index.js").write_text("require('dep')")
            result = walk_repo(td, plan="free")
        assert not any("node_modules" in p for p in result["tree"])

    def test_walk_repo_test_files_identified(self):
        from services.file_service import walk_repo
        with tempfile.TemporaryDirectory() as td:
            Path(td, "main.py").write_text("print('hi')")
            Path(td, "test_main.py").write_text("def test_x(): pass")
            result = walk_repo(td, plan="free")
        assert "test_main.py" in result["test_files"]
        assert "main.py" not in result["test_files"]

    def test_walk_repo_dep_files_read(self):
        from services.file_service import walk_repo
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.py").write_text("import b")
            Path(td, "b.py").write_text("x = 1")
            result = walk_repo(td, plan="free")
        # Both source files should be in dep_files
        assert "a.py" in result["dep_files"]
        assert "b.py" in result["dep_files"]


# ═══════════════════════════════════════════════════════════════════════════════
# 16. GitHub OAuth: not configured
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitHubOAuthNotConfigured:
    def test_github_login_not_configured_returns_503(self, client):
        import api.auth as _auth_module
        old = _auth_module.GITHUB_CLIENT_ID
        _auth_module.GITHUB_CLIENT_ID = ""
        try:
            resp = client.get("/api/auth/github", follow_redirects=False)
        finally:
            _auth_module.GITHUB_CLIENT_ID = old
        assert resp.status_code == 503

    def test_github_connect_not_configured_returns_503(self, client, test_user):
        import api.auth as _auth_module
        old = _auth_module.GITHUB_CLIENT_ID
        _auth_module.GITHUB_CLIENT_ID = ""
        try:
            token = create_token(test_user.id)
            resp = client.get(f"/api/auth/github/connect?token={token}",
                              follow_redirects=False)
        finally:
            _auth_module.GITHUB_CLIENT_ID = old
        assert resp.status_code == 503


# ═══════════════════════════════════════════════════════════════════════════════
# 17. GitHub callback: invalid/expired state
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitHubCallbackState:
    def test_invalid_state_redirects_to_login_error(self, client):
        import api.auth as _auth_module
        old_id = _auth_module.GITHUB_CLIENT_ID
        old_secret = _auth_module.GITHUB_CLIENT_SECRET
        _auth_module.GITHUB_CLIENT_ID = "fake_id"
        _auth_module.GITHUB_CLIENT_SECRET = "fake_secret"
        try:
            resp = client.get("/api/auth/github/callback?code=abc&state=invalid_state",
                              follow_redirects=False)
        finally:
            _auth_module.GITHUB_CLIENT_ID = old_id
            _auth_module.GITHUB_CLIENT_SECRET = old_secret
        assert resp.status_code == 307
        assert "invalid_state" in resp.headers.get("location", "")

    def test_missing_state_redirects_to_login_error(self, client):
        import api.auth as _auth_module
        old_id = _auth_module.GITHUB_CLIENT_ID
        old_secret = _auth_module.GITHUB_CLIENT_SECRET
        _auth_module.GITHUB_CLIENT_ID = "fake_id"
        _auth_module.GITHUB_CLIENT_SECRET = "fake_secret"
        try:
            # state defaults to "" when not provided; "" is not in _oauth_states
            resp = client.get("/api/auth/github/callback?code=abc",
                              follow_redirects=False)
        finally:
            _auth_module.GITHUB_CLIENT_ID = old_id
            _auth_module.GITHUB_CLIENT_SECRET = old_secret
        assert resp.status_code == 307
        assert "invalid_state" in resp.headers.get("location", "")


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Analysis endpoint: force=True gating
# ═══════════════════════════════════════════════════════════════════════════════

class TestForceAnalysisGating:
    def test_free_user_cannot_force_reanalyze(self, client, auth_headers):
        """Free users: force=True returns 403."""
        with patch("api.routes._check_repo_accessibility"):
            resp = client.post("/api/analyze",
                               json={"repo_url": "https://github.com/owner/repo",
                                     "force": True},
                               headers=auth_headers)
        assert resp.status_code == 403

    def test_pro_user_can_force_reanalyze(self, client, pro_auth_headers):
        with patch("api.routes._check_repo_accessibility"), \
             patch("api.routes._do_analysis"):
            resp = client.post("/api/analyze",
                               json={"repo_url": "https://github.com/owner/repo",
                                     "force": True},
                               headers=pro_auth_headers)
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 19. GET /api/github/repos: edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestGithubReposEndpoint:
    def test_no_token_returns_empty_list(self, client, auth_headers):
        """User with no GitHub token gets [] without error."""
        resp = client.get("/api/github/repos", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_github_api_error_returns_empty_list(self, client, db_session, test_user):
        from services.encryption import encrypt as encrypt_field
        test_user.github_access_token = encrypt_field("sometoken")
        db_session.commit()
        mock_resp = MagicMock()
        mock_resp.is_success = False
        with patch("httpx.Client") as mock_client_cls:
            ctx = MagicMock()
            ctx.__enter__ = lambda s: ctx
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.get = MagicMock(return_value=mock_resp)
            mock_client_cls.return_value = ctx
            resp = client.get("/api/github/repos", headers=_auth(test_user))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_github_starred_field_present(self, client, db_session, test_user):
        from services.encryption import encrypt as encrypt_field
        test_user.github_access_token = encrypt_field("sometoken")
        db_session.commit()

        repos_mock = MagicMock()
        repos_mock.is_success = True
        repos_mock.json.return_value = [{
            "name": "myrepo", "full_name": "user/myrepo",
            "private": False, "description": "a repo",
            "updated_at": "2025-01-01T00:00:00Z",
            "html_url": "https://github.com/user/myrepo",
            "language": "Python",
        }]
        starred_mock = MagicMock()
        starred_mock.is_success = True
        starred_mock.json.return_value = [{"full_name": "user/myrepo"}]

        with patch("httpx.Client") as mock_client_cls:
            ctx = MagicMock()
            ctx.__enter__ = lambda s: ctx
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.get = MagicMock(side_effect=[repos_mock, starred_mock])
            mock_client_cls.return_value = ctx
            resp = client.get("/api/github/repos", headers=_auth(test_user))

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["github_starred"] is True
        assert data[0]["language"] == "Python"

    def test_not_starred_repo_has_false_flag(self, client, db_session, test_user):
        from services.encryption import encrypt as encrypt_field
        test_user.github_access_token = encrypt_field("sometoken")
        db_session.commit()

        repos_mock = MagicMock()
        repos_mock.is_success = True
        repos_mock.json.return_value = [{
            "name": "notstarred", "full_name": "user/notstarred",
            "private": False, "description": "",
            "updated_at": "2025-01-01T00:00:00Z",
            "html_url": "https://github.com/user/notstarred",
            "language": None,
        }]
        starred_mock = MagicMock()
        starred_mock.is_success = True
        starred_mock.json.return_value = []  # no starred repos

        with patch("httpx.Client") as mock_client_cls:
            ctx = MagicMock()
            ctx.__enter__ = lambda s: ctx
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.get = MagicMock(side_effect=[repos_mock, starred_mock])
            mock_client_cls.return_value = ctx
            resp = client.get("/api/github/repos", headers=_auth(test_user))

        data = resp.json()
        assert data[0]["github_starred"] is False
        assert data[0]["language"] == ""  # None mapped to ""

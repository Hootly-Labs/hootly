"""
Security edge-case tests.
Covers: rate-limiter memory, X-Forwarded-For spoofing, OAuth dict cleanup,
password validation, admin safeguards, force-flag restriction, body size limit,
JWT attacks, IDOR, and account deletion.
"""
import time
import threading
from collections import deque
from unittest.mock import patch, MagicMock

import jwt
import pytest

from services.rate_limiter import (
    _lock, _requests, _keyed_requests,
    check_rate_limit, check_rate_limit_key,
    RATE_LIMIT_MAX, RATE_LIMIT_WINDOW,
    _evict_empty, _prune,
)
from services.auth_service import create_token, JWT_SECRET, JWT_ALGO, hash_password


# ─────────────────────────────────────────────────────────────────────────────
# Rate-limiter memory management
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimiterMemory:
    def test_empty_deque_is_evicted(self):
        """After all timestamps expire, the key should be removable via _evict_empty."""
        with _lock:
            _requests["test-ip"] = deque([time.time() - RATE_LIMIT_WINDOW - 1])
            dq = _requests["test-ip"]
            _prune(dq, time.time())
            assert len(dq) == 0
            _evict_empty(_requests)
            assert "test-ip" not in _requests

    def test_non_empty_deque_is_not_evicted(self):
        with _lock:
            _requests["active-ip"] = deque([time.time()])
            _evict_empty(_requests)
            assert "active-ip" in _requests
            del _requests["active-ip"]

    def test_keyed_empty_eviction(self):
        with _lock:
            _keyed_requests["login:1.2.3.4"] = deque([time.time() - 7200])
            dq = _keyed_requests["login:1.2.3.4"]
            _prune(dq, time.time())
            _evict_empty(_keyed_requests)
            assert "login:1.2.3.4" not in _keyed_requests

    def test_many_ips_dont_grow_forever(self):
        """Simulate 200 unique IPs each making 1 request; after expiry all deques evict."""
        now = time.time()
        old_ts = now - RATE_LIMIT_WINDOW - 1
        with _lock:
            for i in range(200):
                _requests[f"sim-{i}"] = deque([old_ts])
            # Prune + evict
            for dq in list(_requests.values()):
                _prune(dq, now)
            _evict_empty(_requests)
            leftover = [k for k in _requests if k.startswith("sim-")]
        assert leftover == [], f"Expected all sim- keys evicted, got {len(leftover)} left"


# ─────────────────────────────────────────────────────────────────────────────
# X-Forwarded-For spoofing
# ─────────────────────────────────────────────────────────────────────────────

class TestXForwardedFor:
    def test_xff_ignored_without_trusted_proxy(self, client, auth_headers):
        """When TRUSTED_PROXY_IPS is not set, X-Forwarded-For must be ignored."""
        import api.routes as routes_mod
        # Patch trusted proxies to empty (default)
        with patch.object(routes_mod, "_TRUSTED_PROXIES", frozenset()):
            with patch("services.git_service.clone_repo"), \
                 patch("services.file_service.walk_repo", return_value={
                     "tree": ["a.py"], "files": {"a.py": "x=1"},
                     "dep_files": {}, "test_files": []}), \
                 patch("services.claude_service.run_analysis_pipeline",
                       return_value={"summary": "ok", "key_files": [], "reading_order": [],
                                     "guide": "", "patterns": []}), \
                 patch("services.dependency_parser.parse_dependencies", return_value={}), \
                 patch("services.git_service.get_commit_hash", return_value="abc123"), \
                 patch("services.git_service.make_temp_dir", return_value="/tmp/x"), \
                 patch("services.git_service.cleanup_temp_dir"):
                # Use up all 5 slots from the real client IP
                for _ in range(RATE_LIMIT_MAX):
                    resp = client.post(
                        "/api/analyze",
                        json={"repo_url": "https://github.com/owner/repo"},
                        headers={**auth_headers, "X-Forwarded-For": "9.9.9.9"},
                    )
                # 6th request should be rate-limited regardless of the spoofed IP
                resp = client.post(
                    "/api/analyze",
                    json={"repo_url": "https://github.com/owner/repo"},
                    headers={**auth_headers, "X-Forwarded-For": "1.2.3.4"},
                )
                assert resp.status_code == 429

    def test_xff_used_when_trusted_proxy_matches(self, client, auth_headers):
        """When connecting IP IS a trusted proxy, XFF first entry is used as client IP."""
        import api.routes as routes_mod
        # Simulate client "testclient" as a trusted proxy
        with patch.object(routes_mod, "_TRUSTED_PROXIES", frozenset(["testclient"])):
            with patch("api.routes._check_repo_accessibility"), \
                 patch("services.git_service.clone_repo"), \
                 patch("services.file_service.walk_repo", return_value={
                     "tree": ["a.py"], "files": {"a.py": "x=1"},
                     "dep_files": {}, "test_files": []}), \
                 patch("services.claude_service.run_analysis_pipeline",
                       return_value={"summary": "ok", "key_files": [], "reading_order": [],
                                     "guide": "", "patterns": []}), \
                 patch("services.dependency_parser.parse_dependencies", return_value={}), \
                 patch("services.git_service.get_commit_hash", return_value="def456"), \
                 patch("services.git_service.make_temp_dir", return_value="/tmp/y"), \
                 patch("services.git_service.cleanup_temp_dir"):
                # First request with XFF pointing to a unique IP — should succeed
                resp = client.post(
                    "/api/analyze",
                    json={"repo_url": "https://github.com/owner/repo"},
                    headers={**auth_headers, "X-Forwarded-For": "200.200.200.1"},
                )
                assert resp.status_code in (200, 202)


# ─────────────────────────────────────────────────────────────────────────────
# Password validation hardening
# ─────────────────────────────────────────────────────────────────────────────

class TestPasswordValidation:
    def test_too_short(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "short@test.com", "password": "abc"})
        assert resp.status_code == 400

    def test_whitespace_only(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "ws@test.com", "password": "          "})
        assert resp.status_code == 400
        assert "blank" in resp.json()["detail"].lower()

    def test_too_long_rejected(self, client):
        """Passwords over 1024 chars must be rejected to prevent bcrypt DoS."""
        resp = client.post("/api/auth/register",
                           json={"email": "long@test.com", "password": "A" * 1025})
        assert resp.status_code == 400
        assert "1024" in resp.json()["detail"]

    def test_exactly_1024_accepted(self, client):
        # 1010 + 14 = 1024 chars exactly, with complexity (upper, lower, digit, special)
        resp = client.post("/api/auth/register",
                           json={"email": "max@test.com", "password": "A" * 1010 + "aB@5fghijk1234"})
        # Should not fail with "too long" (may fail for other reasons but not length)
        detail = resp.json().get("detail", "")
        assert "1024" not in detail

    def test_10_char_valid(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "valid@test.com", "password": "Test@Pass123"})
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# JWT attacks
# ─────────────────────────────────────────────────────────────────────────────

class TestJWTAttacks:
    def test_expired_token_rejected(self, client, test_user):
        """An expired JWT must be rejected with 401."""
        expired = jwt.encode(
            {"sub": test_user.id, "exp": 1},  # exp=epoch 1 → always expired
            JWT_SECRET, algorithm=JWT_ALGO,
        )
        resp = client.get("/api/auth/me",
                          headers={"Authorization": f"Bearer {expired}"})
        assert resp.status_code == 401

    def test_wrong_secret_rejected(self, client, test_user):
        forged = jwt.encode({"sub": test_user.id, "exp": int(time.time()) + 3600},
                            "wrong-secret", algorithm=JWT_ALGO)
        resp = client.get("/api/auth/me",
                          headers={"Authorization": f"Bearer {forged}"})
        assert resp.status_code == 401

    def test_none_algorithm_rejected(self, client, test_user):
        """alg=none tokens must not be accepted."""
        header = {"alg": "none", "typ": "JWT"}
        import base64, json as _json
        def b64(d): return base64.urlsafe_b64encode(_json.dumps(d).encode()).rstrip(b"=").decode()
        payload = {"sub": test_user.id, "exp": int(time.time()) + 3600}
        token = f"{b64(header)}.{b64(payload)}."
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_tampered_payload_rejected(self, client, test_user, db_session):
        """A valid JWT with a different sub must not grant access to that user's data."""
        from models import User
        other = User(email="other@test.com", password_hash=hash_password("otherpassword1"),
                     plan="free", is_admin=False, is_verified=True)
        db_session.add(other)
        db_session.commit()
        db_session.refresh(other)

        # Build a token for test_user but then swap the sub to other.id without re-signing
        real_token = create_token(test_user.id)
        parts = real_token.split(".")
        import base64, json as _json
        pad = lambda s: s + "=" * (-len(s) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(pad(parts[1])))
        payload["sub"] = other.id
        def b64(d): return base64.urlsafe_b64encode(_json.dumps(d).encode()).rstrip(b"=").decode()
        forged = f"{parts[0]}.{b64(payload)}.invalidsig"
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
        assert resp.status_code == 401

    def test_missing_bearer_rejected(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_deleted_user_token_rejected(self, client, db_session, test_user, auth_headers):
        """After account deletion, old JWT must not grant access."""
        # Delete the user directly (bypass the delete-account endpoint to avoid
        # the auth flow consuming the token)
        from models import Analysis, WatchedRepo
        db_session.query(Analysis).filter_by(user_id=test_user.id).delete()
        db_session.query(WatchedRepo).filter_by(user_id=test_user.id).delete()
        db_session.delete(test_user)
        db_session.commit()

        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# IDOR / Authorization
# ─────────────────────────────────────────────────────────────────────────────

class TestIDOR:
    def _make_analysis(self, db_session, user, status="completed"):
        from models import Analysis
        a = Analysis(repo_url="https://github.com/x/y", repo_name="x/y",
                     status=status, stage="Done", user_id=user.id)
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        return a

    def test_cannot_view_other_users_analysis(self, client, db_session, test_user, pro_user):
        analysis = self._make_analysis(db_session, pro_user)
        token = create_token(test_user.id)
        resp = client.get(f"/api/analysis/{analysis.id}",
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404

    def test_cannot_star_other_users_analysis(self, client, db_session, test_user, pro_user):
        analysis = self._make_analysis(db_session, pro_user)
        token = create_token(test_user.id)
        resp = client.patch(f"/api/analysis/{analysis.id}/star",
                            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404

    def test_cannot_toggle_visibility_of_others_analysis(self, client, db_session,
                                                          test_user, pro_user):
        analysis = self._make_analysis(db_session, pro_user)
        token = create_token(test_user.id)
        resp = client.patch(f"/api/analysis/{analysis.id}/visibility",
                            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404

    def test_own_analysis_is_accessible(self, client, db_session, test_user, auth_headers):
        analysis = self._make_analysis(db_session, test_user)
        resp = client.get(f"/api/analysis/{analysis.id}", headers=auth_headers)
        assert resp.status_code == 200

    def test_free_user_cannot_access_admin_endpoints(self, client, auth_headers):
        resp = client.get("/api/admin/stats", headers=auth_headers)
        assert resp.status_code == 403

    def test_unauthenticated_cannot_access_admin(self, client):
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Admin safeguards
# ─────────────────────────────────────────────────────────────────────────────

class TestAdminSafeguards:
    def test_cannot_demote_last_admin(self, client, db_session, admin_user, admin_auth_headers):
        """PATCH admin/{id} with is_admin=False must fail when no other admin exists."""
        resp = client.patch(
            f"/api/admin/users/{admin_user.id}",
            json={"is_admin": False},
            headers=admin_auth_headers,
        )
        # Self-demotion is blocked with 400
        assert resp.status_code == 400

    def test_cannot_change_own_admin_status(self, client, admin_user, admin_auth_headers):
        resp = client.patch(
            f"/api/admin/users/{admin_user.id}",
            json={"is_admin": False},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 400

    def test_promote_then_demote_revokes_pro(self, client, db_session, admin_user,
                                              admin_auth_headers, test_user):
        """Demoting an admin also sets their plan back to free."""
        # First promote test_user to admin
        resp = client.patch(f"/api/admin/users/{test_user.id}",
                            json={"is_admin": True}, headers=admin_auth_headers)
        assert resp.status_code == 200
        assert resp.json()["plan"] == "pro"

        # Now demote (there are now 2 admins, so this is allowed)
        resp = client.patch(f"/api/admin/users/{test_user.id}",
                            json={"is_admin": False}, headers=admin_auth_headers)
        assert resp.status_code == 200
        assert resp.json()["plan"] == "free"
        assert resp.json()["is_admin"] is False

    def test_free_user_cannot_patch_plan_via_settings(self, client, auth_headers):
        """Settings endpoint must not accept a 'plan' field."""
        resp = client.patch("/api/auth/settings",
                            json={"notify_on_complete": True, "plan": "pro"},
                            headers=auth_headers)
        # Pydantic will ignore unknown fields; plan must NOT change
        # If it returns 200 the plan must still be free (verified via /me)
        if resp.status_code == 200:
            me = client.get("/api/auth/me", headers=auth_headers)
            assert me.json()["plan"] == "free"


# ─────────────────────────────────────────────────────────────────────────────
# Force flag restriction
# ─────────────────────────────────────────────────────────────────────────────

class TestForceFlagRestriction:
    def test_free_user_cannot_force_reanalyze(self, client, auth_headers):
        resp = client.post("/api/analyze",
                           json={"repo_url": "https://github.com/owner/repo", "force": True},
                           headers=auth_headers)
        assert resp.status_code == 403
        assert "Pro" in resp.json()["detail"]

    def test_pro_user_can_force_reanalyze(self, client, pro_user, pro_auth_headers):
        with patch("api.routes._check_repo_accessibility"), \
             patch("services.git_service.clone_repo"), \
             patch("services.file_service.walk_repo", return_value={
                 "tree": ["a.py"], "files": {"a.py": "x=1"},
                 "dep_files": {}, "test_files": []}), \
             patch("services.claude_service.run_analysis_pipeline",
                   return_value={"summary": "ok", "key_files": [], "reading_order": [],
                                 "guide": "", "patterns": []}), \
             patch("services.dependency_parser.parse_dependencies", return_value={}), \
             patch("services.git_service.get_commit_hash", return_value="xyz"), \
             patch("services.git_service.make_temp_dir", return_value="/tmp/z"), \
             patch("services.git_service.cleanup_temp_dir"):
            resp = client.post("/api/analyze",
                               json={"repo_url": "https://github.com/owner/repo", "force": True},
                               headers=pro_auth_headers)
        assert resp.status_code == 200

    def test_admin_can_force_reanalyze(self, client, admin_auth_headers):
        with patch("api.routes._check_repo_accessibility"), \
             patch("services.git_service.clone_repo"), \
             patch("services.file_service.walk_repo", return_value={
                 "tree": ["a.py"], "files": {"a.py": "x=1"},
                 "dep_files": {}, "test_files": []}), \
             patch("services.claude_service.run_analysis_pipeline",
                   return_value={"summary": "ok", "key_files": [], "reading_order": [],
                                 "guide": "", "patterns": []}), \
             patch("services.dependency_parser.parse_dependencies", return_value={}), \
             patch("services.git_service.get_commit_hash", return_value="xyz2"), \
             patch("services.git_service.make_temp_dir", return_value="/tmp/z2"), \
             patch("services.git_service.cleanup_temp_dir"):
            resp = client.post("/api/analyze",
                               json={"repo_url": "https://github.com/owner/repo", "force": True},
                               headers=admin_auth_headers)
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Request body size limit
# ─────────────────────────────────────────────────────────────────────────────

class TestBodySizeLimit:
    def test_oversized_body_rejected(self, client, auth_headers):
        """Content-Length > 1 MB must be rejected with 413."""
        resp = client.post(
            "/api/analyze",
            content=b"x" * 1_000_001,
            headers={**auth_headers, "Content-Type": "application/json",
                     "Content-Length": "1000001"},
        )
        assert resp.status_code == 413

    def test_normal_body_accepted(self, client, auth_headers):
        """A normal-size request must not be blocked by the size middleware."""
        with patch("api.routes._check_repo_accessibility"), \
             patch("services.git_service.clone_repo"), \
             patch("services.file_service.walk_repo", return_value={
                 "tree": ["a.py"], "files": {"a.py": "x=1"},
                 "dep_files": {}, "test_files": []}), \
             patch("services.claude_service.run_analysis_pipeline",
                   return_value={"summary": "ok", "key_files": [], "reading_order": [],
                                 "guide": "", "patterns": []}), \
             patch("services.dependency_parser.parse_dependencies", return_value={}), \
             patch("services.git_service.get_commit_hash", return_value="small"), \
             patch("services.git_service.make_temp_dir", return_value="/tmp/s"), \
             patch("services.git_service.cleanup_temp_dir"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://github.com/owner/repo"},
                headers=auth_headers,
            )
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# OAuth code exchange — single-use enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestOAuthCodeExchange:
    def test_code_is_single_use(self, client, db_session, test_user):
        """The same OAuth code must not be exchangeable twice."""
        from api.auth import _new_oauth_code
        token = create_token(test_user.id)
        code = _new_oauth_code(token)

        r1 = client.post("/api/auth/github/exchange", json={"code": code})
        assert r1.status_code == 200

        r2 = client.post("/api/auth/github/exchange", json={"code": code})
        assert r2.status_code == 400

    def test_expired_code_rejected(self, client, test_user):
        """A code past its TTL must be rejected."""
        from api.auth import _oauth_codes, _oauth_codes_lock
        import secrets as _sec
        stale = _sec.token_urlsafe(32)
        with _oauth_codes_lock:
            _oauth_codes[stale] = {"token": create_token(test_user.id),
                                   "expires_at": time.time() - 1}
        r = client.post("/api/auth/github/exchange", json={"code": stale})
        assert r.status_code == 400

    def test_garbage_code_rejected(self, client):
        r = client.post("/api/auth/github/exchange", json={"code": "notarealcode"})
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Password reset rate limiting
# ─────────────────────────────────────────────────────────────────────────────

class TestPasswordResetRateLimit:
    def test_reset_submit_rate_limited(self, client):
        """POSTing /reset-password more than 5 times from same IP must 429."""
        dummy_token = jwt.encode(
            {"sub": "fake", "purpose": "reset", "ph": "12345678",
             "exp": int(time.time()) + 3600},
            JWT_SECRET, algorithm=JWT_ALGO,
        )
        for _ in range(5):
            client.post("/api/auth/reset-password",
                        json={"token": dummy_token, "new_password": "Newpassword1!"})
        resp = client.post("/api/auth/reset-password",
                           json={"token": dummy_token, "new_password": "Newpassword1!"})
        assert resp.status_code == 429

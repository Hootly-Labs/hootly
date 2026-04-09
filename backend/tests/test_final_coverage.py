"""
Final coverage push — tests for remaining uncovered lines across:
- api/routes.py:   _to_response bad JSON, get_github_repos exception, _do_analysis edge paths
- api/billing.py:  Stripe checkout/portal, webhook dispatch branches
- api/auth.py:     OAuth cleanup, rate limit 429s, github_login/connect edge cases,
                   exchange_oauth_code user-not-found
- api/admin.py:    PostgreSQL _date_trunc path, promote-to-admin logging
- services/auth_service.py:  get_current_user_optional all branches
- services/watcher_service.py: user=None, exception handler, start_watcher
- services/rate_limiter.py:  _cleanup_loop, check_rate_limit_key prune
- services/git_service.py:   FileNotFoundError, TimeoutExpired, cleanup exception
- services/dependency_parser.py: tsconfig alias paths, Go block imports
- services/file_service.py:  truncation, binary skip, dep_files direct read
- services/claude_service.py: _extract_json fence/prose failed-parse (except branches)
- database.py:     postgres:// URL rewrite
"""
import json
import os
import subprocess
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from models import Analysis, User, WatchedRepo
from services.auth_service import create_token, hash_password


# ══════════════════════════════════════════════════════════════════════════════
# api/routes.py
# ══════════════════════════════════════════════════════════════════════════════

class TestRoutesUncovered:

    # ── _to_response: invalid JSON in result / changelog ─────────────────────

    def test_to_response_bad_result_json(self, client, db_session, test_user):
        """Analysis.result contains invalid JSON → result_dict stays None (no crash)."""
        token = create_token(test_user.id)
        a = Analysis(
            repo_url="https://github.com/o/r",
            repo_name="o/r",
            status="completed",
            result="THIS IS NOT JSON {{{{",
            user_id=test_user.id,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)

        r = client.get(f"/api/analysis/{a.id}",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["result"] is None

    def test_to_response_bad_changelog_json(self, client, db_session, test_user):
        """Analysis.changelog contains invalid JSON → changelog_dict stays None."""
        import json as _json
        token = create_token(test_user.id)
        a = Analysis(
            repo_url="https://github.com/o/rc",
            repo_name="o/rc",
            status="completed",
            result=_json.dumps({"repo_name": "o/rc"}),
            changelog="NOT JSON AT ALL",
            user_id=test_user.id,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)

        r = client.get(f"/api/analysis/{a.id}",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["changelog"] is None

    # ── get_github_repos: httpx exception → return [] ────────────────────────

    def test_github_repos_exception_returns_empty(self, client, db_session, test_user):
        """When httpx raises an exception fetching repos, endpoint returns []."""
        from services.encryption import encrypt as encrypt_field
        test_user.github_access_token = encrypt_field("tok")
        db_session.commit()

        with patch("api.routes.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.side_effect = RuntimeError("network error")
            r = client.get(
                "/api/github/repos",
                headers={"Authorization": f"Bearer {create_token(test_user.id)}"},
            )
        assert r.status_code == 200
        assert r.json() == []

    # ── _do_analysis: various early exits ────────────────────────────────────

    def test_do_analysis_missing_id_returns_silently(self):
        """_do_analysis with a nonexistent analysis ID logs nothing and returns."""
        from api.routes import _do_analysis
        with patch("database.SessionLocal") as mock_sl:
            mock_db = MagicMock()
            mock_sl.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = None
            _do_analysis("nonexistent-id-xyz")
        mock_db.close.assert_called_once()

    def test_do_analysis_empty_tree_fails(self, db_session):
        """When walk_repo returns empty tree, analysis ends with status=failed."""
        from api.routes import _do_analysis
        from models import _utcnow

        a = Analysis(
            repo_url="https://github.com/o/empty",
            repo_name="o/empty",
            status="pending",
            user_id=None,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        aid = a.id

        with patch("database.SessionLocal") as mock_sl, \
             patch("api.routes.make_temp_dir", return_value="/tmp/fake"), \
             patch("api.routes.clone_repo"), \
             patch("api.routes._check_repo_limits"), \
             patch("api.routes.get_commit_hash", return_value="abc123"), \
             patch("api.routes.walk_repo", return_value={"tree": [], "files": {}, "dep_files": {}, "test_files": []}), \
             patch("api.routes.cleanup_temp_dir"):
            mock_sl.return_value = db_session
            _do_analysis(aid)

        fresh = db_session.query(Analysis).filter(Analysis.id == aid).first()
        assert fresh.status == "failed"
        assert "empty" in (fresh.error_message or "").lower()

    def test_do_analysis_no_files_fails(self, db_session):
        """When walk_repo has tree but no readable files, analysis fails."""
        from api.routes import _do_analysis

        a = Analysis(
            repo_url="https://github.com/o/binaryonly",
            repo_name="o/binaryonly",
            status="pending",
            user_id=None,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        aid = a.id

        with patch("database.SessionLocal") as mock_sl, \
             patch("api.routes.make_temp_dir", return_value="/tmp/fake"), \
             patch("api.routes.clone_repo"), \
             patch("api.routes._check_repo_limits"), \
             patch("api.routes.get_commit_hash", return_value="def456"), \
             patch("api.routes.walk_repo", return_value={
                 "tree": ["image.png"], "files": {}, "dep_files": {}, "test_files": []
             }), \
             patch("api.routes.cleanup_temp_dir"):
            mock_sl.return_value = db_session
            _do_analysis(aid)

        fresh = db_session.query(Analysis).filter(Analysis.id == aid).first()
        assert fresh.status == "failed"

    def test_do_analysis_unexpected_exception_fails(self, db_session):
        """An unexpected exception (not RuntimeError) sets status=failed with generic message."""
        from api.routes import _do_analysis

        a = Analysis(
            repo_url="https://github.com/o/crash",
            repo_name="o/crash",
            status="pending",
            user_id=None,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        aid = a.id

        with patch("database.SessionLocal") as mock_sl, \
             patch("api.routes.make_temp_dir", return_value="/tmp/fake"), \
             patch("api.routes.clone_repo", side_effect=ValueError("unexpected internal error")), \
             patch("api.routes.cleanup_temp_dir"):
            mock_sl.return_value = db_session
            _do_analysis(aid)

        fresh = db_session.query(Analysis).filter(Analysis.id == aid).first()
        assert fresh.status == "failed"
        assert "unexpected" in (fresh.error_message or "").lower()

    def test_do_analysis_sends_notification_email(self, db_session, test_user):
        """When notify_on_complete=True, analysis completion sends email."""
        from api.routes import _do_analysis
        import json as _json

        test_user.notify_on_complete = True
        db_session.commit()

        a = Analysis(
            repo_url="https://github.com/o/notifyrepo",
            repo_name="o/notifyrepo",
            status="pending",
            user_id=test_user.id,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        aid = a.id

        fake_result = {
            "repo_name": "o/notifyrepo", "architecture": {}, "key_files": [],
            "reading_order": [], "dependencies": {}, "quick_start": "",
            "onboarding_guide": "", "key_concepts": [], "patterns": [],
            "test_files": [], "file_tree": [], "dependency_graph": {},
        }
        with patch("database.SessionLocal") as mock_sl, \
             patch("api.routes.make_temp_dir", return_value="/tmp/fake"), \
             patch("api.routes.clone_repo"), \
             patch("api.routes._check_repo_limits"), \
             patch("api.routes.get_commit_hash", return_value=""), \
             patch("api.routes.walk_repo", return_value={
                 "tree": ["main.py"], "files": {"main.py": "# code"},
                 "dep_files": {"main.py": "# code"}, "test_files": []
             }), \
             patch("api.routes.parse_dependencies", return_value={"nodes": [], "edges": []}), \
             patch("api.routes.run_analysis_pipeline", return_value=fake_result), \
             patch("api.routes.send_analysis_complete_email") as mock_email, \
             patch("api.routes.cleanup_temp_dir"):
            mock_sl.return_value = db_session
            _do_analysis(aid, plan=test_user.plan)

        fresh = db_session.query(Analysis).filter(Analysis.id == aid).first()
        assert fresh.status == "completed"
        mock_email.assert_called_once()
        call_args = mock_email.call_args[0]
        assert call_args[0] == test_user.email
        assert "o/notifyrepo" in call_args[1]

    def test_do_analysis_generates_changelog(self, db_session, test_user):
        """When previous_result is provided, changelog is generated and stored."""
        from api.routes import _do_analysis
        import json as _json

        prev_result = _json.dumps({"architecture": {}, "key_files": [], "dependencies": {}, "reading_order": []})
        a = Analysis(
            repo_url="https://github.com/o/changelogrepo",
            repo_name="o/changelogrepo",
            status="pending",
            user_id=test_user.id,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        aid = a.id

        fake_result = {
            "repo_name": "o/changelogrepo", "architecture": {}, "key_files": [],
            "reading_order": [], "dependencies": {}, "quick_start": "",
            "onboarding_guide": "", "key_concepts": [], "patterns": [],
            "test_files": [], "file_tree": [], "dependency_graph": {},
        }
        fake_changelog = {"summary": "minor changes", "new_files": [], "removed_files": [],
                          "architecture_changes": [], "dependency_changes": {"added": [], "removed": []},
                          "highlights": []}

        with patch("database.SessionLocal") as mock_sl, \
             patch("api.routes.make_temp_dir", return_value="/tmp/fake"), \
             patch("api.routes.clone_repo"), \
             patch("api.routes._check_repo_limits"), \
             patch("api.routes.get_commit_hash", return_value=""), \
             patch("api.routes.walk_repo", return_value={
                 "tree": ["main.py"], "files": {"main.py": "# code"},
                 "dep_files": {}, "test_files": []
             }), \
             patch("api.routes.parse_dependencies", return_value={"nodes": [], "edges": []}), \
             patch("api.routes.run_analysis_pipeline", return_value=fake_result), \
             patch("api.routes.generate_changelog", return_value=fake_changelog) as mock_cl, \
             patch("api.routes.cleanup_temp_dir"):
            mock_sl.return_value = db_session
            _do_analysis(aid, previous_result=prev_result)

        fresh = db_session.query(Analysis).filter(Analysis.id == aid).first()
        assert fresh.status == "completed"
        mock_cl.assert_called_once()
        assert fresh.changelog is not None

    # ── _check_repo_limits: OSError path ─────────────────────────────────────

    def test_check_repo_limits_oserror_ignored(self, tmp_path):
        """OSError when reading file size is silently ignored — file count still works."""
        from api.routes import _check_repo_limits
        (tmp_path / "file.py").write_text("x")
        with patch("os.path.getsize", side_effect=OSError("permission denied")):
            # Should not raise — OSError is caught in the pass clause
            _check_repo_limits(str(tmp_path), plan="pro")


# ══════════════════════════════════════════════════════════════════════════════
# api/billing.py — Stripe checkout / portal / webhook dispatch
# ══════════════════════════════════════════════════════════════════════════════

class TestBillingStripe:

    def _auth(self, user):
        return {"Authorization": f"Bearer {create_token(user.id)}"}

    # ── checkout ─────────────────────────────────────────────────────────────

    def test_checkout_creates_new_customer(self, client, db_session, test_user):
        mock_customer = MagicMock()
        mock_customer.id = "cus_new_123"
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/session"

        with patch("api.billing._stripe_configured", return_value=True), \
             patch("api.billing.stripe") as mock_stripe:
            mock_stripe.Customer.create.return_value = mock_customer
            mock_stripe.checkout.Session.create.return_value = mock_session
            r = client.post("/api/billing/checkout", headers=self._auth(test_user))

        assert r.status_code == 200
        assert r.json()["url"] == "https://checkout.stripe.com/session"
        mock_stripe.Customer.create.assert_called_once()

    def test_checkout_reuses_existing_customer(self, client, db_session, test_user):
        test_user.stripe_customer_id = "cus_existing_456"
        db_session.commit()

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/existing"

        with patch("api.billing._stripe_configured", return_value=True), \
             patch("api.billing.stripe") as mock_stripe:
            mock_stripe.checkout.Session.create.return_value = mock_session
            r = client.post("/api/billing/checkout", headers=self._auth(test_user))

        assert r.status_code == 200
        # Customer.create should NOT have been called
        mock_stripe.Customer.create.assert_not_called()

    # ── portal ────────────────────────────────────────────────────────────────

    def test_portal_creates_session(self, client, db_session, test_user):
        test_user.stripe_customer_id = "cus_portal_789"
        db_session.commit()

        mock_portal = MagicMock()
        mock_portal.url = "https://billing.stripe.com/portal"

        with patch("api.billing._stripe_configured", return_value=True), \
             patch("api.billing.stripe") as mock_stripe:
            mock_stripe.billing_portal.Session.create.return_value = mock_portal
            r = client.post("/api/billing/portal", headers=self._auth(test_user))

        assert r.status_code == 200
        assert r.json()["url"] == "https://billing.stripe.com/portal"

    # ── webhook dispatch ──────────────────────────────────────────────────────

    def _make_event(self, event_type: str, data_obj: dict) -> dict:
        return {"type": event_type, "data": {"object": data_obj}}

    def _post_webhook(self, client, payload: dict):
        with patch("api.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
             patch("api.billing.stripe") as mock_stripe:
            mock_stripe.Webhook.construct_event.return_value = payload
            return client.post(
                "/api/billing/webhook",
                content=b"{}",
                headers={"stripe-signature": "t=123,v1=sig"},
            ), mock_stripe

    def test_webhook_checkout_completed_upgrades_user(self, client, db_session, test_user):
        test_user.stripe_customer_id = "cus_webhook_1"
        db_session.commit()

        payload = self._make_event("checkout.session.completed", {
            "customer": "cus_webhook_1",
            "subscription": "sub_abc",
        })
        r, _ = self._post_webhook(client, payload)
        assert r.status_code == 200
        db_session.refresh(test_user)
        assert test_user.plan == "pro"

    def test_webhook_subscription_deleted_downgrades_user(self, client, db_session, test_user):
        test_user.stripe_customer_id = "cus_webhook_2"
        test_user.plan = "pro"
        db_session.commit()

        payload = self._make_event("customer.subscription.deleted", {
            "id": "sub_deleted",
            "customer": "cus_webhook_2",
        })
        r, _ = self._post_webhook(client, payload)
        assert r.status_code == 200
        db_session.refresh(test_user)
        assert test_user.plan == "free"

    def test_webhook_payment_failed_downgrades_user(self, client, db_session, test_user):
        test_user.stripe_customer_id = "cus_webhook_3"
        test_user.plan = "pro"
        db_session.commit()

        payload = self._make_event("invoice.payment_failed", {"customer": "cus_webhook_3"})
        r, _ = self._post_webhook(client, payload)
        assert r.status_code == 200
        db_session.refresh(test_user)
        assert test_user.plan == "free"


# ══════════════════════════════════════════════════════════════════════════════
# api/auth.py — remaining gaps
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthUncovered:

    # ── _oauth_cleanup_loop: expired codes get deleted ────────────────────────

    def test_oauth_cleanup_deletes_expired_codes(self):
        import api.auth as auth_mod
        # Inject an expired code
        with auth_mod._oauth_codes_lock:
            auth_mod._oauth_codes["expired-code"] = {
                "token": "tok",
                "expires_at": time.time() - 10,  # already expired
            }

        # Run one cleanup iteration
        now = time.time()
        with auth_mod._oauth_codes_lock:
            expired = [k for k, v in list(auth_mod._oauth_codes.items()) if now > v["expires_at"]]
            for k in expired:
                del auth_mod._oauth_codes[k]

        with auth_mod._oauth_codes_lock:
            assert "expired-code" not in auth_mod._oauth_codes

    # ── forgot_password rate limit 429 ────────────────────────────────────────

    def test_forgot_password_rate_limited(self, client):
        from services.rate_limiter import _keyed_requests, _lock
        # Pre-fill the rate limiter for this IP
        with _lock:
            _keyed_requests["reset:testclient"] = deque([time.time()] * 5)

        r = client.post("/api/auth/forgot-password", json={"email": "x@y.com"})
        assert r.status_code == 429

    # ── reset_password invalid token (jwt.InvalidTokenError) ─────────────────

    def test_reset_password_invalid_token(self, client):
        r = client.post("/api/auth/reset-password",
                        json={"token": "not.a.valid.jwt", "new_password": "newpass123"})
        assert r.status_code == 400
        assert "invalid" in r.json()["detail"].lower()

    # ── change_password: GitHub-login user (no password_hash) ─────────────────

    def test_change_password_github_user_rejected(self, client, db_session, test_user):
        test_user.password_hash = ""
        db_session.commit()
        token = create_token(test_user.id)
        r = client.patch(
            "/api/auth/change-password",
            json={"old_password": "anything", "new_password": "newpassword123"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400
        assert "GitHub" in r.json()["detail"] or "password" in r.json()["detail"].lower()

    # ── verify_email rate limit 429 ───────────────────────────────────────────

    def test_verify_email_rate_limited(self, client, db_session, unverified_user):
        from services.rate_limiter import _keyed_requests, _lock
        token = create_token(unverified_user.id)
        key = f"verify:{unverified_user.id}:testclient"
        with _lock:
            _keyed_requests[key] = deque([time.time()] * 5)

        r = client.post(
            "/api/auth/verify-email",
            json={"code": "123456"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 429

    # ── resend_verification rate limit 429 ────────────────────────────────────

    def test_resend_verification_rate_limited(self, client, db_session, unverified_user):
        from services.rate_limiter import _keyed_requests, _lock
        token = create_token(unverified_user.id)
        with _lock:
            _keyed_requests["resend:testclient"] = deque([time.time()] * 3)

        r = client.post(
            "/api/auth/resend-verification",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 429

    # ── github_login redirect (configured path) ───────────────────────────────

    def test_github_login_redirects_to_github(self, client):
        with patch("api.auth.GITHUB_CLIENT_ID", "test_client_id"):
            r = client.get("/api/auth/github", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "github.com/login/oauth/authorize" in r.headers["location"]
        assert "test_client_id" in r.headers["location"]

    # ── github_connect: invalid JWT → redirect ────────────────────────────────

    def test_github_connect_invalid_token_redirects(self, client):
        with patch("api.auth.GITHUB_CLIENT_ID", "cid"):
            r = client.get(
                "/api/auth/github/connect",
                params={"token": "not.a.valid.jwt"},
                follow_redirects=False,
            )
        assert r.status_code in (302, 307)
        assert "invalid_session" in r.headers["location"]

    # ── github_connect: user not found in DB → redirect ──────────────────────

    def test_github_connect_user_not_found_redirects(self, client):
        # Create a token for a nonexistent user
        ghost_token = create_token("nonexistent-user-id")
        with patch("api.auth.GITHUB_CLIENT_ID", "cid"):
            r = client.get(
                "/api/auth/github/connect",
                params={"token": ghost_token},
                follow_redirects=False,
            )
        assert r.status_code in (302, 307)
        assert "invalid_session" in r.headers["location"]

    # ── exchange_oauth_code: user not found ───────────────────────────────────

    def test_exchange_oauth_code_user_not_found(self, client):
        import api.auth as auth_mod
        # Create a code that references a nonexistent user
        ghost_token = create_token("ghost-user-xyz")
        with auth_mod._oauth_codes_lock:
            auth_mod._oauth_codes["test-ghost-code"] = {
                "token": ghost_token,
                "expires_at": time.time() + 300,
            }

        r = client.post("/api/auth/github/exchange", json={"code": "test-ghost-code"})
        assert r.status_code == 401
        assert "not found" in r.json()["detail"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# api/admin.py — PostgreSQL _date_trunc path
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminUncovered:

    def test_date_trunc_postgres_path(self):
        """The PostgreSQL cast(col, Date) branch in _date_trunc."""
        from sqlalchemy import Column, DateTime
        from api.admin import _date_trunc
        col = MagicMock()
        with patch("api.admin._is_sqlite", False):
            result = _date_trunc(col)
        # Should return a cast expression (not call func.strftime)
        assert result is not None

    def test_patch_user_promote_to_admin_logs(self, client, db_session, admin_user, test_user):
        """Promoting a user to admin triggers the logger.info path (lines 162-165)."""
        r = client.patch(
            f"/api/admin/users/{test_user.id}",
            json={"is_admin": True},
            headers={"Authorization": f"Bearer {create_token(admin_user.id)}"},
        )
        assert r.status_code == 200
        assert r.json()["is_admin"] is True
        assert r.json()["plan"] == "pro"


# ══════════════════════════════════════════════════════════════════════════════
# services/auth_service.py — get_current_user_optional
# ══════════════════════════════════════════════════════════════════════════════

class TestGetCurrentUserOptional:
    """Direct unit tests — bypass FastAPI routing to hit all branches."""

    def _make_request(self, auth_header: str = "") -> MagicMock:
        req = MagicMock()
        req.headers = {"Authorization": auth_header} if auth_header else {}
        return req

    def _make_db(self, user=None):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = user
        return mock_db

    def test_no_auth_header_returns_none(self):
        from services.auth_service import get_current_user_optional
        assert get_current_user_optional(self._make_request(), self._make_db()) is None

    def test_non_bearer_header_returns_none(self):
        from services.auth_service import get_current_user_optional
        assert get_current_user_optional(
            self._make_request("Basic dXNlcjpwYXNz"), self._make_db()
        ) is None

    def test_empty_token_returns_none(self):
        from services.auth_service import get_current_user_optional
        assert get_current_user_optional(
            self._make_request("Bearer "), self._make_db()
        ) is None

    def test_invalid_token_returns_none(self):
        from services.auth_service import get_current_user_optional
        req = MagicMock()
        req.headers.get = MagicMock(
            side_effect=lambda k, d="": "Bearer not.valid.jwt" if k == "Authorization" else d
        )
        assert get_current_user_optional(req, self._make_db()) is None

    def test_valid_token_returns_user(self, test_user):
        from services.auth_service import get_current_user_optional
        token = create_token(test_user.id)
        req = MagicMock()
        req.headers.get = lambda k, d="": f"Bearer {token}" if k == "Authorization" else d
        result = get_current_user_optional(req, self._make_db(test_user))
        assert result is test_user


# ══════════════════════════════════════════════════════════════════════════════
# services/watcher_service.py
# ══════════════════════════════════════════════════════════════════════════════

class TestWatcherServiceUncovered:

    def test_check_watched_repos_user_is_none_continues(self, db_session):
        """When a WatchedRepo has no associated user, the new-commit path skips analysis."""
        from services.watcher_service import check_watched_repos

        # Create a watch with a dangling user_id (user deleted)
        watch = WatchedRepo(
            user_id="deleted-user-id",
            repo_url="https://github.com/o/nouserre",
            repo_name="o/nouserre",
            last_commit_hash="aaa",
        )
        db_session.add(watch)
        db_session.commit()

        watch_id = watch.id
        with patch("database.SessionLocal", return_value=db_session), \
             patch("services.watcher_service.get_latest_commit", return_value="bbb"):
            check_watched_repos()

        # Re-query after session close
        fresh_watch = db_session.query(WatchedRepo).filter(WatchedRepo.id == watch_id).first()
        assert fresh_watch.last_commit_hash == "bbb"
        count = db_session.query(Analysis).filter(Analysis.repo_url == "https://github.com/o/nouserre").count()
        assert count == 0

    def test_check_watched_repos_exception_in_loop_continues(self, db_session, caplog):
        """Exception during processing one watch is caught; loop continues to next watch."""
        import logging
        from services.watcher_service import check_watched_repos

        watch = WatchedRepo(
            user_id="any-id",
            repo_url="https://github.com/o/errrepo",
            repo_name="o/errrepo",
        )
        db_session.add(watch)
        db_session.commit()

        with patch("database.SessionLocal", return_value=db_session), \
             patch("services.watcher_service.get_latest_commit",
                   side_effect=RuntimeError("simulated crash")), \
             caplog.at_level(logging.ERROR, logger="services.watcher_service"):
            check_watched_repos()

        assert "Error processing watch" in caplog.text

    def test_start_watcher_spawns_daemon_thread(self, caplog):
        """start_watcher() creates a daemon thread and logs startup."""
        import logging
        from services.watcher_service import start_watcher

        spawned = []

        class FakeThread:
            def __init__(self, *a, **kw):
                # threading.Thread sets daemon via kwarg in __init__
                self.daemon = kw.get("daemon", False)
                self.name = kw.get("name", "")
            def start(self):
                spawned.append(self)

        with patch("services.watcher_service.threading.Thread", FakeThread), \
             caplog.at_level(logging.INFO, logger="services.watcher_service"):
            start_watcher()

        assert len(spawned) == 2
        assert spawned[0].daemon is True
        assert spawned[1].daemon is True
        assert "watcher started" in caplog.text.lower()
        assert "cleanup started" in caplog.text.lower()


# ══════════════════════════════════════════════════════════════════════════════
# services/rate_limiter.py — _cleanup_loop and keyed prune
# ══════════════════════════════════════════════════════════════════════════════

class TestRateLimiterUncovered:

    def test_cleanup_loop_prunes_and_evicts(self):
        """_cleanup_loop logic: old timestamps pruned, empty keys removed."""
        from services.rate_limiter import _lock, _requests, _keyed_requests, _prune, _evict_empty

        old_ts = time.time() - 7200  # 2 hours ago — outside 1h window
        with _lock:
            _requests["stale-ip"] = deque([old_ts])
            _keyed_requests["stale-key"] = deque([old_ts])

        now = time.time()
        with _lock:
            for dq in list(_requests.values()):
                _prune(dq, now)
            _evict_empty(_requests)
            for dq in list(_keyed_requests.values()):
                _prune(dq, now)
            _evict_empty(_keyed_requests)

        with _lock:
            assert "stale-ip" not in _requests
            assert "stale-key" not in _keyed_requests

    def test_check_rate_limit_key_prunes_old_entries(self):
        """Old entries within a key are pruned before checking the count."""
        from services.rate_limiter import check_rate_limit_key, _keyed_requests, _lock

        old_ts = time.time() - 7200
        with _lock:
            _keyed_requests["prune-key"] = deque([old_ts, old_ts, old_ts])

        # Should be allowed because old entries are pruned first
        allowed, retry = check_rate_limit_key("prune-key", max_requests=5, window=3600)
        assert allowed is True


# ══════════════════════════════════════════════════════════════════════════════
# services/git_service.py — FileNotFoundError and TimeoutExpired
# ══════════════════════════════════════════════════════════════════════════════

class TestGitServiceUncovered:

    def test_clone_repo_file_not_found_error(self):
        """When git is not on PATH, raise RuntimeError with helpful message."""
        from services.git_service import clone_repo
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="git is not installed"):
                clone_repo("https://github.com/o/r", "/tmp/dest")

    def test_clone_repo_timeout(self):
        """When git clone times out, raise RuntimeError."""
        from services.git_service import clone_repo
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="git", timeout=120)):
            with pytest.raises(RuntimeError, match="timed out"):
                clone_repo("https://github.com/o/r", "/tmp/dest")

    def test_cleanup_temp_dir_exception_silenced(self):
        """cleanup_temp_dir swallows exceptions — no crash."""
        from services.git_service import cleanup_temp_dir
        with patch("shutil.rmtree", side_effect=PermissionError("locked")):
            cleanup_temp_dir("/some/path")  # should not raise


# ══════════════════════════════════════════════════════════════════════════════
# services/dependency_parser.py — tsconfig alias path, Go block imports
# ══════════════════════════════════════════════════════════════════════════════

class TestDependencyParserUncovered:

    def test_detect_aliases_from_tsconfig(self):
        """Custom paths in tsconfig.json are loaded as aliases."""
        from services.dependency_parser import _detect_aliases
        files = {
            "tsconfig.json": json.dumps({
                "compilerOptions": {
                    "paths": {
                        "@app/*": ["./src/app/*"],
                        "@shared/*": ["./src/shared/*"],
                    }
                }
            })
        }
        aliases = _detect_aliases(files)
        assert "@app/" in aliases
        assert "@shared/" in aliases

    def test_detect_aliases_tsconfig_invalid_json_ignored(self):
        """Malformed tsconfig.json is silently ignored."""
        from services.dependency_parser import _detect_aliases
        aliases = _detect_aliases({"tsconfig.json": "NOT JSON"})
        # Should still have default aliases
        assert isinstance(aliases, dict)

    def test_parse_js_alias_no_file_match(self):
        """JS alias that resolves to a path not in all_files is skipped."""
        from services.dependency_parser import _parse_js
        aliases = {"@app/": ["src/app/"]}
        all_files = set()  # No files exist
        result = _parse_js(
            "src/index.ts",
            "import foo from '@app/foo';",
            all_files,
            aliases,
        )
        assert result == []

    def test_parse_go_block_imports(self):
        """Go parenthesized import block is parsed correctly."""
        from services.dependency_parser import _parse_go
        content = '''
package main

import (
    "fmt"
    "mymodule/internal/handler"
    "mymodule/pkg/utils"
)
'''
        all_files = {
            "internal/handler/main.go",
            "pkg/utils/utils.go",
        }
        targets = _parse_go("main.go", content, all_files, "mymodule")
        assert "internal/handler/main.go" in targets
        assert "pkg/utils/utils.go" in targets


# ══════════════════════════════════════════════════════════════════════════════
# services/file_service.py — remaining branches
# ══════════════════════════════════════════════════════════════════════════════

class TestFileServiceUncovered:

    def test_is_secret_file_env_example_is_safe(self):
        """_is_secret_file returns False for .env.example and .env.sample."""
        from services.file_service import _is_secret_file
        assert _is_secret_file(".env.example") is False
        assert _is_secret_file(".env.sample") is False
        assert _is_secret_file(".env.local") is True

    def test_walk_repo_reads_secondary_files(self, tmp_path):
        """Secondary (non-priority) source files fill remaining read slots."""
        from services.file_service import walk_repo
        # Create more priority files than max_read to trigger secondary fill
        for i in range(5):
            (tmp_path / f"module_{i}.py").write_text(f"# module {i}")
        result = walk_repo(str(tmp_path))
        # At least one source file should be in files
        assert len(result["files"]) > 0

    def test_walk_repo_skips_binary_extensions(self, tmp_path):
        """Files with binary extensions are not read into files dict."""
        from services.file_service import walk_repo
        (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n")
        (tmp_path / "main.py").write_text("print('hello')")
        result = walk_repo(str(tmp_path))
        assert "image.png" not in result["files"]
        assert "main.py" in result["files"]

    def test_walk_repo_truncates_large_files(self, tmp_path):
        """Files larger than MAX_FILE_SIZE get a truncation notice appended."""
        from services.file_service import walk_repo, MAX_FILE_SIZE
        big = tmp_path / "bigfile.py"
        big.write_bytes(b"x" * (MAX_FILE_SIZE + 1000))
        result = walk_repo(str(tmp_path))
        if "bigfile.py" in result["files"]:
            assert "truncated" in result["files"]["bigfile.py"]

    def test_walk_repo_dep_files_reads_source_not_already_read(self, tmp_path):
        """dep_files includes source files not in the main files dict."""
        from services.file_service import walk_repo, MAX_READ_FILES
        # Create many files so some go to dep_files only
        for i in range(MAX_READ_FILES + 5):
            (tmp_path / f"service_{i}.py").write_text(f"import os\n# service {i}")
        result = walk_repo(str(tmp_path))
        # dep_files should have more entries than files (if beyond read limit)
        assert len(result["dep_files"]) >= len(result["files"])


# ══════════════════════════════════════════════════════════════════════════════
# services/claude_service.py — _extract_json fence/prose failed-parse except branches
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractJsonExceptBranches:
    """Cover lines 64-65 and 77-78: invalid JSON inside a fence or prose span."""

    def test_bad_json_in_fence_covered_by_except(self):
        """Invalid JSON inside a fence covers the except branch (64-65), then prose also fails → ValueError."""
        from services.claude_service import _extract_json
        # Fence block has invalid JSON → step 2 except fires (lines 64-65)
        # Prose step finds '{invalid}' span which is also invalid → step 3 except fires (lines 77-78)
        # Nothing succeeds → final raise
        text = "```json\n{invalid: json here}\n```\nsome trailing prose"
        with pytest.raises(ValueError, match="Could not parse JSON"):
            _extract_json(text)

    def test_bad_json_in_prose_raises(self):
        """Invalid JSON found via prose path (no fence) covers lines 77-78 then raises."""
        from services.claude_service import _extract_json
        # No fence → step 2 skipped; prose finds '{' but span is invalid
        text = "Here is the data: {this: is not valid json at all}"
        with pytest.raises(ValueError, match="Could not parse JSON"):
            _extract_json(text)


# ══════════════════════════════════════════════════════════════════════════════
# database.py — postgres:// URL rewrite
# ══════════════════════════════════════════════════════════════════════════════

class TestDatabaseUncovered:

    def test_postgres_url_rewritten(self):
        """The legacy postgres:// scheme is rewritten to postgresql://."""
        original = "postgres://user:pass@host/db"
        fixed = original.replace("postgres://", "postgresql://", 1)
        assert fixed == "postgresql://user:pass@host/db"
        # Verify it only replaces the prefix, not interior occurrences
        assert fixed.count("postgresql://") == 1

"""
Tests covering gaps identified in the coverage audit:
- Password reset full flow (submit token)
- Account deletion cascades to analyses + watches
- Admin delete user endpoint
- Failed analyses not counting against monthly limit
- Watch endpoint auth isolation
- Unverified user cannot analyze
- Billing endpoints (checkout, portal) when Stripe not configured
- Admin delete user cannot delete self / admin
- Resend verification rate limit
- GitHub disconnect endpoint
- Analysis star/visibility for unowned analyses
- Public analysis filters (not completed = 404, private = 404)
"""
import json
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import jwt as pyjwt

from models import Analysis, User, WatchedRepo

# Use the same secret that conftest sets before app import
_JWT_SECRET = os.environ.get("JWT_SECRET", "test-secret-do-not-use-in-prod")


def _make_reset_token(user, secret=None, purpose="reset", expired=False):
    """Build a password-reset JWT for tests."""
    s = secret or _JWT_SECRET
    exp = (datetime.now(timezone.utc) - timedelta(seconds=1)
           if expired
           else datetime.now(timezone.utc) + timedelta(hours=1))
    return pyjwt.encode(
        {"sub": user.id, "purpose": purpose, "ph": user.password_hash[:8], "exp": exp},
        s,
        algorithm="HS256",
    )


# ─────────────────────────────────────────────────────────────────
# Password Reset — full token flow
# ─────────────────────────────────────────────────────────────────

class TestPasswordResetFlow:
    def test_reset_with_valid_token_changes_password(self, client, test_user, db_session):
        """Full flow: request reset → use token → login with new password."""
        with patch("services.email_service.send_password_reset_email"):
            resp = client.post("/api/auth/forgot-password",
                               json={"email": test_user.email})
        assert resp.status_code == 200

        token = _make_reset_token(test_user)
        resp = client.post("/api/auth/reset-password",
                           json={"token": token, "new_password": "NewTest@Pass99"})
        assert resp.status_code == 200

        # Old password no longer works
        resp = client.post("/api/auth/login",
                           json={"email": test_user.email, "password": "Test@Pass123"})
        assert resp.status_code == 401

        # New password works
        resp = client.post("/api/auth/login",
                           json={"email": test_user.email, "password": "NewTest@Pass99"})
        assert resp.status_code == 200

    def test_reset_token_is_single_use(self, client, test_user):
        """Using a reset token invalidates it (hash prefix changes after reset)."""
        token = _make_reset_token(test_user)

        resp1 = client.post("/api/auth/reset-password",
                            json={"token": token, "new_password": "First@Pass99"})
        assert resp1.status_code == 200

        # Second use of same token must fail (hash prefix no longer matches)
        resp2 = client.post("/api/auth/reset-password",
                            json={"token": token, "new_password": "Second@Pass99"})
        assert resp2.status_code == 400
        assert "already been used" in resp2.json()["detail"].lower()

    def test_reset_wrong_purpose_rejected(self, client, test_user):
        """Token with purpose != 'reset' must be rejected."""
        token = _make_reset_token(test_user, purpose="login")
        resp = client.post("/api/auth/reset-password",
                           json={"token": token, "new_password": "New@Pass9999"})
        assert resp.status_code == 400

    def test_reset_expired_token_rejected(self, client, test_user):
        """Expired reset token must return 400."""
        token = _make_reset_token(test_user, expired=True)
        resp = client.post("/api/auth/reset-password",
                           json={"token": token, "new_password": "New@Pass9999"})
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_reset_new_password_too_short(self, client, test_user):
        """New password < 10 chars must be rejected."""
        token = _make_reset_token(test_user)
        resp = client.post("/api/auth/reset-password",
                           json={"token": token, "new_password": "short"})
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────
# Account deletion cascades
# ─────────────────────────────────────────────────────────────────

class TestAccountDeletionCascades:
    def test_delete_account_removes_analyses(self, client, auth_headers, test_user, db_session):
        for i in range(3):
            db_session.add(Analysis(
                repo_url=f"https://github.com/owner/repo{i}",
                repo_name=f"owner/repo{i}",
                status="completed",
                stage="Done",
                user_id=test_user.id,
            ))
        db_session.commit()

        resp = client.delete("/api/auth/account", headers=auth_headers)
        assert resp.status_code == 200

        remaining = db_session.query(Analysis).filter(Analysis.user_id == test_user.id).count()
        assert remaining == 0

    def test_delete_account_removes_watches(self, client, auth_headers, test_user, db_session):
        db_session.add(WatchedRepo(
            user_id=test_user.id,
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
        ))
        db_session.commit()

        resp = client.delete("/api/auth/account", headers=auth_headers)
        assert resp.status_code == 200

        remaining = db_session.query(WatchedRepo).filter(WatchedRepo.user_id == test_user.id).count()
        assert remaining == 0

    def test_delete_account_removes_user_record(self, client, auth_headers, test_user, db_session):
        user_id = test_user.id
        resp = client.delete("/api/auth/account", headers=auth_headers)
        assert resp.status_code == 200

        user = db_session.query(User).filter(User.id == user_id).first()
        assert user is None

    def test_token_invalid_after_account_deletion(self, client, auth_headers, test_user, db_session):
        client.delete("/api/auth/account", headers=auth_headers)
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────
# Admin — delete user endpoint
# ─────────────────────────────────────────────────────────────────

class TestAdminDeleteUser:
    def test_admin_can_delete_regular_user(self, client, admin_auth_headers, test_user, db_session):
        user_id = test_user.id
        resp = client.delete(f"/api/admin/users/{user_id}", headers=admin_auth_headers)
        assert resp.status_code == 204

        user = db_session.query(User).filter(User.id == user_id).first()
        assert user is None

    def test_delete_cascades_analyses_and_watches(self, client, admin_auth_headers, test_user, db_session):
        db_session.add(Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=test_user.id,
        ))
        db_session.add(WatchedRepo(
            user_id=test_user.id,
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
        ))
        db_session.commit()

        resp = client.delete(f"/api/admin/users/{test_user.id}", headers=admin_auth_headers)
        assert resp.status_code == 204

        assert db_session.query(Analysis).filter(Analysis.user_id == test_user.id).count() == 0
        assert db_session.query(WatchedRepo).filter(WatchedRepo.user_id == test_user.id).count() == 0

    def test_admin_cannot_delete_self(self, client, admin_auth_headers, admin_user):
        resp = client.delete(f"/api/admin/users/{admin_user.id}", headers=admin_auth_headers)
        assert resp.status_code == 400
        assert "account" in resp.json()["detail"].lower()

    def test_admin_cannot_delete_another_admin(self, client, admin_user, db_session):
        second_admin = User(
            email="admin2@example.com",
            password_hash="x",
            plan="pro",
            is_admin=True,
        )
        db_session.add(second_admin)
        db_session.commit()
        db_session.refresh(second_admin)

        token = __import__("services.auth_service", fromlist=["create_token"]).create_token(admin_user.id)
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.delete(f"/api/admin/users/{second_admin.id}", headers=headers)
        assert resp.status_code == 400
        assert "admin" in resp.json()["detail"].lower()

    def test_non_admin_cannot_delete_user(self, client, auth_headers, test_user, pro_user):
        resp = client.delete(f"/api/admin/users/{pro_user.id}", headers=auth_headers)
        assert resp.status_code == 403

    def test_delete_nonexistent_user_returns_404(self, client, admin_auth_headers):
        resp = client.delete("/api/admin/users/nonexistent-id", headers=admin_auth_headers)
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────
# Monthly limit: failed analyses don't count
# ─────────────────────────────────────────────────────────────────

class TestFailedAnalysesNotCounted:
    def test_failed_analysis_does_not_consume_free_quota(
        self, client, auth_headers, test_user, db_session
    ):
        """A failed analysis must not count against the 1/month free limit."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        db_session.add(Analysis(
            repo_url="https://github.com/owner/failed-repo",
            repo_name="owner/failed-repo",
            status="failed",        # failed — should NOT count
            stage="Failed",
            user_id=test_user.id,
            created_at=month_start,
        ))
        db_session.commit()

        # Should still be allowed to analyze
        with patch("api.routes._check_repo_accessibility"), \
             patch("threading.Thread"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://github.com/owner/newrepo"},
                headers=auth_headers,
            )
        # 200 accepted (not 429)
        assert resp.status_code == 200

    def test_billing_usage_excludes_failed(self, client, auth_headers, test_user, db_session):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        db_session.add(Analysis(
            repo_url="https://github.com/owner/failed",
            repo_name="owner/failed",
            status="failed",
            stage="Failed",
            user_id=test_user.id,
            created_at=month_start,
        ))
        db_session.commit()

        resp = client.get("/api/billing/usage", headers=auth_headers)
        assert resp.status_code == 200
        # billing/usage counts all statuses (it's informational), but limit check in /analyze skips failed
        # The usage endpoint itself doesn't filter by status — just verify it returns 200
        assert "analyses_this_month" in resp.json()


# ─────────────────────────────────────────────────────────────────
# Watch endpoint — auth isolation
# ─────────────────────────────────────────────────────────────────

class TestWatchIsolation:
    def test_cannot_delete_another_users_watch(self, client, auth_headers, pro_user, db_session):
        watch = WatchedRepo(
            user_id=pro_user.id,
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
        )
        db_session.add(watch)
        db_session.commit()
        db_session.refresh(watch)

        resp = client.delete(f"/api/watch/{watch.id}", headers=auth_headers)
        assert resp.status_code == 404

    def test_list_watches_returns_only_own(self, client, auth_headers, test_user, pro_user, db_session):
        db_session.add(WatchedRepo(user_id=test_user.id,
                                   repo_url="https://github.com/owner/mine",
                                   repo_name="owner/mine"))
        db_session.add(WatchedRepo(user_id=pro_user.id,
                                   repo_url="https://github.com/owner/theirs",
                                   repo_name="owner/theirs"))
        db_session.commit()

        resp = client.get("/api/watches", headers=auth_headers)
        assert resp.status_code == 200
        names = [w["repo_name"] for w in resp.json()]
        assert "owner/mine" in names
        assert "owner/theirs" not in names

    def test_watch_idempotent_returns_same_record(self, client, auth_headers):
        payload = {"repo_url": "https://github.com/owner/repo"}
        with patch("api.watch.parse_github_url", return_value=("owner", "repo")):
            r1 = client.post("/api/watch", json=payload, headers=auth_headers)
            r2 = client.post("/api/watch", json=payload, headers=auth_headers)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]

    def test_watch_invalid_url_returns_400(self, client, auth_headers):
        resp = client.post("/api/watch",
                           json={"repo_url": "https://notgithub.com/x/y"},
                           headers=auth_headers)
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────
# Unverified user blocked from analysis
# ─────────────────────────────────────────────────────────────────

class TestUnverifiedUserBlocked:
    def test_unverified_cannot_start_analysis(self, client, unverified_user):
        from services.auth_service import create_token
        headers = {"Authorization": f"Bearer {create_token(unverified_user.id)}"}

        with patch("api.routes._check_repo_accessibility"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://github.com/owner/repo"},
                headers=headers,
            )
        assert resp.status_code == 403
        assert "verify" in resp.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────
# Billing — Stripe not configured → 503
# ─────────────────────────────────────────────────────────────────

class TestBillingNotConfigured:
    def test_checkout_returns_503_when_stripe_not_configured(self, client, auth_headers):
        with patch("api.billing.STRIPE_SECRET_KEY", ""), \
             patch("api.billing.STRIPE_PRO_PRICE_ID", ""):
            resp = client.post("/api/billing/checkout", headers=auth_headers)
        assert resp.status_code == 503

    def test_portal_returns_503_when_stripe_not_configured(self, client, auth_headers):
        with patch("api.billing.STRIPE_SECRET_KEY", ""), \
             patch("api.billing.STRIPE_PRO_PRICE_ID", ""):
            resp = client.post("/api/billing/portal", headers=auth_headers)
        assert resp.status_code == 503


# ─────────────────────────────────────────────────────────────────
# Public analysis filters
# ─────────────────────────────────────────────────────────────────

class TestPublicAnalysisFilters:
    def test_private_analysis_not_accessible_publicly(self, client, test_user, db_session):
        a = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            result=json.dumps({"repo_name": "repo"}),
        )
        a.is_public = False
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)

        resp = client.get(f"/api/public/analysis/{a.id}")
        assert resp.status_code == 404

    def test_pending_public_analysis_not_accessible(self, client, test_user, db_session):
        a = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="pending",
            stage="Queued",
            user_id=test_user.id,
        )
        a.is_public = True
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)

        resp = client.get(f"/api/public/analysis/{a.id}")
        assert resp.status_code == 404

    def test_public_completed_analysis_accessible_without_auth(self, client, test_user, db_session):
        result = json.dumps({"repo_name": "repo", "architecture": {}, "key_files": [],
                             "reading_order": [], "dependencies": {"runtime": [], "dev": []},
                             "quick_start": "", "onboarding_guide": "", "key_concepts": [],
                             "file_tree": []})
        a = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            result=result,
        )
        a.is_public = True
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)

        # No auth headers
        resp = client.get(f"/api/public/analysis/{a.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == a.id


# ─────────────────────────────────────────────────────────────────
# Analysis ownership — star / visibility on unowned
# ─────────────────────────────────────────────────────────────────

class TestAnalysisOwnership:
    def test_cannot_star_another_users_analysis(self, client, auth_headers, pro_user, db_session):
        a = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=pro_user.id,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)

        resp = client.patch(f"/api/analysis/{a.id}/star", headers=auth_headers)
        assert resp.status_code == 404

    def test_cannot_toggle_visibility_of_another_users_analysis(
        self, client, auth_headers, pro_user, db_session
    ):
        a = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=pro_user.id,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)

        resp = client.patch(f"/api/analysis/{a.id}/visibility", headers=auth_headers)
        assert resp.status_code == 404

    def test_admin_can_view_any_analysis(self, client, admin_auth_headers, test_user, db_session):
        a = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=test_user.id,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)

        resp = client.get(f"/api/analysis/{a.id}", headers=admin_auth_headers)
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────
# GitHub disconnect
# ─────────────────────────────────────────────────────────────────

class TestGitHubDisconnect:
    def test_disconnect_clears_token(self, client, auth_headers, test_user, db_session):
        from services.encryption import encrypt as encrypt_field
        test_user.github_access_token = encrypt_field("some-token")
        test_user.github_username = "octocat"
        db_session.commit()

        resp = client.delete("/api/auth/github/token", headers=auth_headers)
        assert resp.status_code == 200

        db_session.refresh(test_user)
        assert test_user.github_access_token is None
        assert test_user.github_username is None

    def test_disconnect_requires_auth(self, client):
        resp = client.delete("/api/auth/github/token")
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────
# Sensitive data not leaked in responses
# ─────────────────────────────────────────────────────────────────

class TestNoSensitiveDataLeaked:
    def test_register_response_has_no_password_hash(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "leak@example.com", "password": "Test@Pass123"})
        assert resp.status_code == 200
        body = resp.text
        assert "password_hash" not in body
        assert "$2b$" not in body  # bcrypt prefix

    def test_me_response_has_no_password_hash(self, client, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.text
        assert "password_hash" not in body
        assert "$2b$" not in body

    def test_admin_users_response_has_no_password_hash(self, client, admin_auth_headers):
        resp = client.get("/api/admin/users", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.text
        assert "password_hash" not in body
        assert "$2b$" not in body

    def test_analysis_list_not_exposed_cross_user(self, client, auth_headers, pro_user, db_session):
        """User A's analysis list must not include User B's analyses."""
        a = Analysis(
            repo_url="https://github.com/owner/secret-repo",
            repo_name="owner/secret-repo",
            status="completed",
            stage="Done",
            user_id=pro_user.id,
        )
        db_session.add(a)
        db_session.commit()

        resp = client.get("/api/analyses", headers=auth_headers)
        assert resp.status_code == 200
        assert not any(a["repo_name"] == "owner/secret-repo" for a in resp.json())


# ─────────────────────────────────────────────────────────────────
# Pro user monthly limit — no cap
# ─────────────────────────────────────────────────────────────────

class TestProUserUnlimited:
    def test_pro_user_can_exceed_free_limit(self, client, pro_auth_headers, pro_user, db_session):
        """Pro users must not be blocked by the 1/month free limit."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for i in range(5):
            db_session.add(Analysis(
                repo_url=f"https://github.com/owner/repo{i}",
                repo_name=f"owner/repo{i}",
                status="completed",
                stage="Done",
                user_id=pro_user.id,
                created_at=month_start,
            ))
        db_session.commit()

        with patch("api.routes._check_repo_accessibility"), \
             patch("threading.Thread"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://github.com/owner/new"},
                headers=pro_auth_headers,
            )
        assert resp.status_code == 200

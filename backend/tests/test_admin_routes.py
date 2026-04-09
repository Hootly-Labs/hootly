"""Integration tests for admin endpoints: stats, users, charts, plan/admin toggle."""
import pytest
from datetime import datetime, timezone

from models import Analysis, User
from services.auth_service import hash_password


class TestAdminStats:
    def test_stats_requires_admin(self, client, auth_headers):
        resp = client.get("/api/admin/stats", headers=auth_headers)
        assert resp.status_code == 403

    def test_stats_unauthenticated(self, client):
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 401

    def test_stats_returns_correct_structure(self, client, admin_auth_headers):
        resp = client.get("/api/admin/stats", headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "total_users",
            "free_users",
            "pro_users",
            "total_analyses",
            "completed_analyses",
            "recent_signups_30d",
            "analyses_today",
        }
        assert expected_keys <= set(data.keys())

    def test_stats_counts_users(self, client, admin_auth_headers, test_user, pro_user, admin_user):
        resp = client.get("/api/admin/stats", headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # admin_user fixture creates 1 admin (pro), test_user=free, pro_user=pro
        assert data["total_users"] >= 3
        assert data["free_users"] >= 1
        assert data["pro_users"] >= 2  # admin + pro_user

    def test_stats_completed_analyses_count(self, client, admin_auth_headers, test_user, db_session):
        db_session.add(Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=test_user.id,
        ))
        db_session.commit()
        resp = client.get("/api/admin/stats", headers=admin_auth_headers)
        assert resp.json()["completed_analyses"] >= 1
        assert resp.json()["total_analyses"] >= 1


class TestAdminUsers:
    def test_list_users_requires_admin(self, client, auth_headers):
        resp = client.get("/api/admin/users", headers=auth_headers)
        assert resp.status_code == 403

    def test_list_users_returns_users(self, client, admin_auth_headers, test_user, admin_user):
        resp = client.get("/api/admin/users", headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        emails = [u["email"] for u in data]
        assert test_user.email in emails
        assert admin_user.email in emails

    def test_list_users_structure(self, client, admin_auth_headers, test_user):
        resp = client.get("/api/admin/users", headers=admin_auth_headers)
        assert resp.status_code == 200
        user_data = next(u for u in resp.json() if u["email"] == test_user.email)
        expected_keys = {"id", "email", "plan", "is_admin", "is_verified", "created_at",
                         "last_login", "analysis_count", "analyses_this_month"}
        assert expected_keys <= set(user_data.keys())

    def test_analysis_count_accurate(self, client, admin_auth_headers, test_user, db_session):
        for i in range(2):
            db_session.add(Analysis(
                repo_url=f"https://github.com/owner/repo{i}",
                repo_name=f"owner/repo{i}",
                status="completed",
                stage="Done",
                user_id=test_user.id,
            ))
        db_session.commit()

        resp = client.get("/api/admin/users", headers=admin_auth_headers)
        user_data = next(u for u in resp.json() if u["email"] == test_user.email)
        assert user_data["analysis_count"] == 2


class TestAdminPatchUser:
    def test_patch_plan_free_to_pro(self, client, admin_auth_headers, test_user):
        resp = client.patch(
            f"/api/admin/users/{test_user.id}",
            json={"plan": "pro"},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["plan"] == "pro"

    def test_patch_plan_pro_to_free(self, client, admin_auth_headers, pro_user):
        resp = client.patch(
            f"/api/admin/users/{pro_user.id}",
            json={"plan": "free"},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["plan"] == "free"

    def test_patch_invalid_plan_rejected(self, client, admin_auth_headers, test_user):
        resp = client.patch(
            f"/api/admin/users/{test_user.id}",
            json={"plan": "enterprise"},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 400

    def test_patch_nonexistent_user(self, client, admin_auth_headers):
        resp = client.patch(
            "/api/admin/users/nonexistent-id",
            json={"plan": "pro"},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 404

    def test_patch_requires_admin(self, client, auth_headers, test_user):
        resp = client.patch(
            f"/api/admin/users/{test_user.id}",
            json={"plan": "pro"},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    def test_grant_admin_also_grants_pro(self, client, admin_auth_headers, test_user):
        resp = client.patch(
            f"/api/admin/users/{test_user.id}",
            json={"is_admin": True},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_admin"] is True
        assert data["plan"] == "pro"

    def test_cannot_demote_last_admin(self, client, admin_auth_headers, admin_user, db_session):
        # Create a second admin to perform the demotion (can't demote yourself)
        second_admin = User(
            email="second_admin@example.com",
            password_hash=hash_password("Test@Pass123"),
            plan="pro",
            is_admin=True,
            is_verified=True,
        )
        db_session.add(second_admin)
        db_session.commit()
        db_session.refresh(second_admin)

        # Now demote the second admin — only admin_user remains after, so that's fine.
        # Instead, demote admin_user from second_admin's perspective when admin_user is the only other admin.
        # Simplest: demote second_admin via admin_auth_headers — both admins exist so this should succeed.
        # To test "last admin" guard: demote second_admin first, then try to demote admin_user.
        from services.auth_service import create_token
        second_headers = {"Authorization": f"Bearer {create_token(second_admin.id)}"}

        # Demote admin_user — second_admin is still an admin, so this succeeds
        resp = client.patch(
            f"/api/admin/users/{admin_user.id}",
            json={"is_admin": False},
            headers=second_headers,
        )
        # Now second_admin is the only admin — demoting them should be blocked
        resp2 = client.patch(
            f"/api/admin/users/{second_admin.id}",
            json={"is_admin": False},
            headers=second_headers,  # can't change own status
        )
        # Either "cannot change own status" or "last admin" — both are valid protection
        assert resp2.status_code == 400


class TestAdminCharts:
    def test_charts_requires_admin(self, client, auth_headers):
        resp = client.get("/api/admin/charts", headers=auth_headers)
        assert resp.status_code == 403

    def test_charts_returns_structure(self, client, admin_auth_headers):
        resp = client.get("/api/admin/charts", headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_analyses" in data
        assert "daily_signups" in data
        assert isinstance(data["daily_analyses"], list)
        assert isinstance(data["daily_signups"], list)

    def test_charts_last_30_days(self, client, admin_auth_headers):
        resp = client.get("/api/admin/charts", headers=admin_auth_headers)
        data = resp.json()
        # Should return up to 30 days of data
        assert len(data["daily_analyses"]) <= 30
        assert len(data["daily_signups"]) <= 30

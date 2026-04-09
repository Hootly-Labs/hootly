"""Integration tests for API endpoints using FastAPI TestClient."""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from models import Analysis


class TestAnalyzeEndpoint:
    def test_requires_auth(self, client):
        resp = client.post("/api/analyze", json={"repo_url": "https://github.com/owner/repo"})
        assert resp.status_code == 401

    def test_invalid_url_rejected(self, client, auth_headers):
        resp = client.post(
            "/api/analyze",
            json={"repo_url": "https://notgithub.com/owner/repo"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_url_too_long_rejected(self, client, auth_headers):
        resp = client.post(
            "/api/analyze",
            json={"repo_url": "https://github.com/" + "a" * 300},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_valid_url_returns_pending(self, client, auth_headers):
        with patch("api.routes._check_repo_accessibility"), \
             patch("api.routes._do_analysis"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://github.com/fastapi/fastapi"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["repo_name"] == "fastapi/fastapi"
        assert data["status"] == "pending"

    def test_tree_url_normalised(self, client, auth_headers):
        """URL with /tree/main path should be accepted and stripped."""
        with patch("api.routes._check_repo_accessibility"), \
             patch("api.routes._do_analysis"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://github.com/fastapi/fastapi/tree/main"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["repo_name"] == "fastapi/fastapi"

    def test_blob_url_normalised(self, client, auth_headers):
        with patch("api.routes._check_repo_accessibility"), \
             patch("api.routes._do_analysis"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://github.com/fastapi/fastapi/blob/main/README.md"},
                headers=auth_headers,
            )
        assert resp.status_code == 200

    def test_http_url_accepted(self, client, auth_headers):
        with patch("api.routes._check_repo_accessibility"), \
             patch("api.routes._do_analysis"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "http://github.com/fastapi/fastapi"},
                headers=auth_headers,
            )
        assert resp.status_code == 200

    def test_www_url_accepted(self, client, auth_headers):
        with patch("api.routes._check_repo_accessibility"), \
             patch("api.routes._do_analysis"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://www.github.com/fastapi/fastapi"},
                headers=auth_headers,
            )
        assert resp.status_code == 200

    def test_rate_limit_headers_returned(self, client, auth_headers):
        with patch("api.routes._check_repo_accessibility"), \
             patch("api.routes._do_analysis"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://github.com/owner/repo"},
                headers=auth_headers,
            )
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers

    def test_private_repo_no_token_returns_422(self, client, auth_headers):
        from fastapi import HTTPException
        with patch(
            "api.routes._check_repo_accessibility",
            side_effect=HTTPException(status_code=422, detail="PRIVATE_REPO_NO_TOKEN"),
        ):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://github.com/owner/private-repo"},
                headers=auth_headers,
            )
        assert resp.status_code == 422
        assert "PRIVATE_REPO_NO_TOKEN" in resp.json()["detail"]

    def test_empty_repo_url_rejected(self, client, auth_headers):
        resp = client.post("/api/analyze", json={"repo_url": ""}, headers=auth_headers)
        assert resp.status_code == 400

    def test_xss_attempt_rejected(self, client, auth_headers):
        resp = client.post(
            "/api/analyze",
            json={"repo_url": "https://github.com/<script>/repo"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_non_github_domain_rejected(self, client, auth_headers):
        resp = client.post(
            "/api/analyze",
            json={"repo_url": "https://evil.com/fastapi/fastapi"},
            headers=auth_headers,
        )
        assert resp.status_code == 400


class TestFreePlanLimit:
    def test_limit_enforced_at_one(self, client, auth_headers, test_user, db_session):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        db_session.add(Analysis(
            repo_url="https://github.com/owner/repo0",
            repo_name="owner/repo0",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            created_at=month_start,
        ))
        db_session.commit()

        with patch("api.routes._check_repo_accessibility"), \
             patch("api.routes._do_analysis"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://github.com/owner/newrepo"},
                headers=auth_headers,
            )
        assert resp.status_code == 429
        assert "1 analysis per month" in resp.json()["detail"]

    def test_pro_user_not_limited(self, client, pro_auth_headers, pro_user, db_session):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for i in range(10):
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
             patch("api.routes._do_analysis"):
            resp = client.post(
                "/api/analyze",
                json={"repo_url": "https://github.com/owner/repo999"},
                headers=pro_auth_headers,
            )
        assert resp.status_code == 200


class TestGetAnalysis:
    def _make_analysis(self, db_session, user_id, repo_name="owner/repo"):
        a = Analysis(
            repo_url=f"https://github.com/{repo_name}",
            repo_name=repo_name,
            status="completed",
            stage="Done",
            user_id=user_id,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        return a

    def test_get_own_analysis(self, client, auth_headers, test_user, db_session):
        a = self._make_analysis(db_session, test_user.id)
        resp = client.get(f"/api/analysis/{a.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["repo_name"] == "owner/repo"

    def test_cannot_get_other_users_analysis(self, client, auth_headers, db_session):
        a = self._make_analysis(db_session, "other-user-id")
        resp = client.get(f"/api/analysis/{a.id}", headers=auth_headers)
        assert resp.status_code == 404

    def test_admin_can_see_all(self, client, admin_auth_headers, db_session):
        a = self._make_analysis(db_session, "some-user-id")
        resp = client.get(f"/api/analysis/{a.id}", headers=admin_auth_headers)
        assert resp.status_code == 200

    def test_nonexistent_returns_404(self, client, auth_headers):
        resp = client.get("/api/analysis/does-not-exist", headers=auth_headers)
        assert resp.status_code == 404

    def test_requires_auth(self, client, db_session, test_user):
        a = self._make_analysis(db_session, test_user.id)
        resp = client.get(f"/api/analysis/{a.id}")
        assert resp.status_code == 401


class TestPublicAnalysis:
    def test_public_analysis_accessible_without_auth(self, client, test_user, db_session):
        a = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            is_public=True,
            result='{"repo_name": "owner/repo"}',
        )
        db_session.add(a)
        db_session.commit()
        resp = client.get(f"/api/public/analysis/{a.id}")
        assert resp.status_code == 200

    def test_private_analysis_not_accessible_without_auth(self, client, test_user, db_session):
        a = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            is_public=False,
        )
        db_session.add(a)
        db_session.commit()
        resp = client.get(f"/api/public/analysis/{a.id}")
        assert resp.status_code == 404


class TestStarAndVisibility:
    def _make_analysis(self, db_session, user_id):
        a = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=user_id,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        return a

    def test_star_toggles(self, client, auth_headers, test_user, db_session):
        a = self._make_analysis(db_session, test_user.id)
        resp = client.patch(f"/api/analysis/{a.id}/star", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["is_starred"] is True
        # Toggle back
        resp2 = client.patch(f"/api/analysis/{a.id}/star", headers=auth_headers)
        assert resp2.json()["is_starred"] is False

    def test_visibility_toggles(self, client, auth_headers, test_user, db_session):
        a = self._make_analysis(db_session, test_user.id)
        resp = client.patch(f"/api/analysis/{a.id}/visibility", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["is_public"] is True

    def test_cannot_star_others_analysis(self, client, auth_headers, db_session):
        a = self._make_analysis(db_session, "other-user")
        resp = client.patch(f"/api/analysis/{a.id}/star", headers=auth_headers)
        assert resp.status_code == 404


class TestWatchEndpoints:
    def test_watch_repo(self, client, auth_headers):
        resp = client.post(
            "/api/watch",
            json={"repo_url": "https://github.com/fastapi/fastapi"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["repo_name"] == "fastapi/fastapi"
        assert data["repo_url"] == "https://github.com/fastapi/fastapi"

    def test_watch_tree_url_normalised(self, client, auth_headers):
        resp = client.post(
            "/api/watch",
            json={"repo_url": "https://github.com/fastapi/fastapi/tree/main"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["repo_url"] == "https://github.com/fastapi/fastapi"

    def test_watch_is_idempotent(self, client, auth_headers):
        url = "https://github.com/owner/repo"
        r1 = client.post("/api/watch", json={"repo_url": url}, headers=auth_headers)
        r2 = client.post("/api/watch", json={"repo_url": url}, headers=auth_headers)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]

    def test_list_watches(self, client, auth_headers):
        client.post("/api/watch", json={"repo_url": "https://github.com/owner/repo1"}, headers=auth_headers)
        client.post("/api/watch", json={"repo_url": "https://github.com/owner/repo2"}, headers=auth_headers)
        resp = client.get("/api/watches", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_unwatch_removes_entry(self, client, auth_headers):
        watch = client.post(
            "/api/watch",
            json={"repo_url": "https://github.com/owner/repo"},
            headers=auth_headers,
        ).json()
        del_resp = client.delete(f"/api/watch/{watch['id']}", headers=auth_headers)
        assert del_resp.status_code == 200
        watches = client.get("/api/watches", headers=auth_headers).json()
        assert len(watches) == 0

    def test_unwatch_nonexistent_returns_404(self, client, auth_headers):
        resp = client.delete("/api/watch/does-not-exist", headers=auth_headers)
        assert resp.status_code == 404

    def test_cannot_unwatch_others_entry(self, client, auth_headers, pro_auth_headers):
        watch = client.post(
            "/api/watch",
            json={"repo_url": "https://github.com/owner/repo"},
            headers=auth_headers,
        ).json()
        resp = client.delete(f"/api/watch/{watch['id']}", headers=pro_auth_headers)
        assert resp.status_code == 404

    def test_watch_invalid_url(self, client, auth_headers):
        resp = client.post(
            "/api/watch",
            json={"repo_url": "https://notgithub.com/owner/repo"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_watch_requires_auth(self, client):
        resp = client.post("/api/watch", json={"repo_url": "https://github.com/owner/repo"})
        assert resp.status_code == 401


class TestHealthEndpoint:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

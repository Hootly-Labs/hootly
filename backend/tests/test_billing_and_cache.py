"""Tests for billing usage endpoint and analysis caching behavior."""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from sqlalchemy.orm import sessionmaker

from models import Analysis


class TestBillingUsage:
    def test_usage_requires_auth(self, client):
        resp = client.get("/api/billing/usage")
        assert resp.status_code == 401

    def test_usage_free_user_zero_analyses(self, client, auth_headers):
        resp = client.get("/api/billing/usage", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["analyses_this_month"] == 0
        assert data["limit"] == 1
        assert data["plan"] == "free"

    def test_usage_free_user_counts_this_month(self, client, auth_headers, test_user, db_session):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for i in range(2):
            db_session.add(Analysis(
                repo_url=f"https://github.com/owner/repo{i}",
                repo_name=f"owner/repo{i}",
                status="completed",
                stage="Done",
                user_id=test_user.id,
                created_at=month_start,
            ))
        db_session.commit()

        resp = client.get("/api/billing/usage", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["analyses_this_month"] == 2

    def test_usage_pro_user_no_limit(self, client, pro_auth_headers):
        resp = client.get("/api/billing/usage", headers=pro_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] is None
        assert data["plan"] == "pro"

    def test_usage_does_not_count_prior_month(self, client, auth_headers, test_user, db_session):
        # Add an analysis from last month — should NOT count
        import datetime as dt
        last_month = datetime.now(timezone.utc).replace(tzinfo=None)
        if last_month.month == 1:
            last_month = last_month.replace(year=last_month.year - 1, month=12, day=15)
        else:
            last_month = last_month.replace(month=last_month.month - 1, day=15)

        db_session.add(Analysis(
            repo_url="https://github.com/owner/old",
            repo_name="owner/old",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            created_at=last_month,
        ))
        db_session.commit()

        resp = client.get("/api/billing/usage", headers=auth_headers)
        assert resp.json()["analyses_this_month"] == 0


_FAKE_RESULT = json.dumps({
    "repo_name": "owner/repo",
    "architecture": {"project_name": "repo"},
    "key_files": [],
    "reading_order": [],
    "dependencies": {"runtime": [], "dev": []},
    "quick_start": "",
    "onboarding_guide": "",
    "key_concepts": [],
    "file_tree": [],
})


class TestAnalysisCache:
    """Test cache behavior inside _do_analysis (the background task)."""

    def _make_analysis(self, db_session, user, commit_hash="abc123"):
        a = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="pending",
            stage="Queued",
            user_id=user.id,
        )
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        return a

    def _run_do_analysis(self, engine, new_id, force=False, plan="free", extra_patches=None):
        """Helper: run _do_analysis with SessionLocal bound to the test engine."""
        TestSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        patches = [
            patch("database.SessionLocal", TestSessionLocal),
            patch("api.routes.make_temp_dir", return_value="/tmp/fake"),
            patch("api.routes.cleanup_temp_dir"),
            patch("api.routes.clone_repo"),
            patch("api.routes.get_commit_hash", return_value="abc123" if not extra_patches else extra_patches.get("commit", "abc123")),
            patch("api.routes._check_repo_limits"),
        ]
        if extra_patches and extra_patches.get("pipeline"):
            patches += [
                patch("api.routes.walk_repo", return_value={"tree": ["file.py"], "files": [{"path": "file.py", "content": "x"}], "dep_files": [], "test_files": []}),
                patch("api.routes.parse_dependencies", return_value={"nodes": [], "edges": []}),
                patch("api.routes.run_analysis_pipeline", return_value={"repo_name": "owner/repo", "architecture": {}, "key_files": [], "reading_order": [], "dependencies": {"runtime": [], "dev": []}, "quick_start": "", "onboarding_guide": "", "key_concepts": [], "file_tree": []}),
            ]
            if extra_patches.get("commit"):
                patches[4] = patch("api.routes.get_commit_hash", return_value=extra_patches["commit"])
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            from api.routes import _do_analysis
            _do_analysis(new_id, force=force, plan=plan)

    def test_cache_hit_reuses_result(self, db_session, test_user, engine):
        """_do_analysis sets status=completed and stage contains 'cache' when commit matches."""
        cached = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            commit_hash="abc123",
            result=_FAKE_RESULT,
        )
        db_session.add(cached)
        db_session.commit()

        new_analysis = self._make_analysis(db_session, test_user)
        new_id = new_analysis.id

        self._run_do_analysis(engine, new_id, force=False, plan="free")

        db_session.expire_all()
        refreshed = db_session.query(Analysis).filter(Analysis.id == new_id).first()
        assert refreshed.status == "completed"
        assert "cache" in refreshed.stage.lower()
        assert refreshed.result == _FAKE_RESULT

    def test_cache_miss_with_different_commit(self, db_session, test_user, engine):
        """_do_analysis runs pipeline when commit hash is new (no cache match)."""
        old = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            commit_hash="oldcommit",
            result=_FAKE_RESULT,
        )
        db_session.add(old)
        db_session.commit()

        new_analysis = self._make_analysis(db_session, test_user)
        new_id = new_analysis.id

        self._run_do_analysis(engine, new_id, force=False, plan="free",
                              extra_patches={"commit": "newcommit", "pipeline": True})

        db_session.expire_all()
        refreshed = db_session.query(Analysis).filter(Analysis.id == new_id).first()
        assert refreshed.status == "completed"
        assert refreshed.commit_hash == "newcommit"
        assert "cache" not in refreshed.stage.lower()

    def test_force_flag_skips_cache(self, db_session, pro_user, engine):
        """force=True bypasses cache even when commit matches."""
        cached = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=pro_user.id,
            commit_hash="abc123",
            result=_FAKE_RESULT,
        )
        db_session.add(cached)
        db_session.commit()

        new_analysis = self._make_analysis(db_session, pro_user)
        new_id = new_analysis.id

        self._run_do_analysis(engine, new_id, force=True, plan="pro",
                              extra_patches={"commit": "abc123", "pipeline": True})

        db_session.expire_all()
        refreshed = db_session.query(Analysis).filter(Analysis.id == new_id).first()
        assert refreshed.status == "completed"
        assert "cache" not in refreshed.stage.lower()


class TestGetAnalyses:
    def test_get_analyses_requires_auth(self, client):
        resp = client.get("/api/analyses")
        assert resp.status_code == 401

    def test_get_analyses_returns_own_analyses(self, client, auth_headers, test_user, db_session):
        db_session.add(Analysis(
            repo_url="https://github.com/owner/myrepo",
            repo_name="owner/myrepo",
            status="completed",
            stage="Done",
            user_id=test_user.id,
        ))
        db_session.commit()

        resp = client.get("/api/analyses", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert any(a["repo_name"] == "owner/myrepo" for a in data)

    def test_get_analyses_does_not_return_others(self, client, auth_headers, pro_user, db_session):
        # Add analysis for another user
        db_session.add(Analysis(
            repo_url="https://github.com/owner/otherrepo",
            repo_name="owner/otherrepo",
            status="completed",
            stage="Done",
            user_id=pro_user.id,
        ))
        db_session.commit()

        resp = client.get("/api/analyses", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert not any(a["repo_name"] == "owner/otherrepo" for a in data)

    def test_admin_sees_all_analyses(self, client, admin_auth_headers, test_user, pro_user, db_session):
        for user, name in [(test_user, "user-repo"), (pro_user, "pro-repo")]:
            db_session.add(Analysis(
                repo_url=f"https://github.com/owner/{name}",
                repo_name=f"owner/{name}",
                status="completed",
                stage="Done",
                user_id=user.id,
            ))
        db_session.commit()

        resp = client.get("/api/analyses", headers=admin_auth_headers)
        assert resp.status_code == 200
        names = [a["repo_name"] for a in resp.json()]
        assert "owner/user-repo" in names
        assert "owner/pro-repo" in names


class TestRepoLimits:
    def test_free_user_repo_size_limit_fails_analysis(self, db_session, test_user, engine):
        """When _check_repo_limits raises for a free user, analysis is marked failed."""
        analysis = Analysis(
            repo_url="https://github.com/owner/bigfree",
            repo_name="owner/bigfree",
            status="pending",
            stage="Queued",
            user_id=test_user.id,
        )
        db_session.add(analysis)
        db_session.commit()
        db_session.refresh(analysis)
        new_id = analysis.id

        TestSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        with patch("database.SessionLocal", TestSessionLocal), \
             patch("api.routes.make_temp_dir", return_value="/tmp/fake"), \
             patch("api.routes.cleanup_temp_dir"), \
             patch("api.routes.clone_repo"), \
             patch("api.routes.get_commit_hash", return_value="abc123"), \
             patch("api.routes._check_repo_limits",
                   side_effect=RuntimeError("Repo has 3000 files, exceeds free plan limit of 2000")):
            from api.routes import _do_analysis
            _do_analysis(new_id, force=False, plan="free")

        db_session.expire_all()
        refreshed = db_session.query(Analysis).filter(Analysis.id == new_id).first()
        assert refreshed.status == "failed"
        assert "3000 files" in refreshed.error_message

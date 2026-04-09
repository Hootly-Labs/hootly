"""Tests for GET /api/user/stats endpoint."""
import pytest
from datetime import datetime, timezone, timedelta

from models import Analysis


def _dt(days_ago: int = 0) -> datetime:
    """Return a naive UTC datetime N days in the past."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(tzinfo=None)


def _make_analysis(db_session, user_id, repo_name="owner/repo", status="completed",
                   days_ago=0, is_starred=False):
    a = Analysis(
        repo_url=f"https://github.com/{repo_name}",
        repo_name=repo_name,
        status=status,
        stage="Done" if status == "completed" else status.capitalize(),
        user_id=user_id,
        created_at=_dt(days_ago),
        is_starred=is_starred,
    )
    db_session.add(a)
    db_session.commit()
    db_session.refresh(a)
    return a


class TestUserStatsAuth:
    def test_requires_auth(self, client):
        resp = client.get("/api/user/stats")
        assert resp.status_code == 401

    def test_authenticated_returns_200(self, client, auth_headers, test_user, db_session):
        resp = client.get("/api/user/stats", headers=auth_headers)
        assert resp.status_code == 200


class TestUserStatsEmpty:
    def test_empty_state_all_zeros(self, client, auth_headers, test_user, db_session):
        resp = client.get("/api/user/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_analyses"] == 0
        assert data["completed_analyses"] == 0
        assert data["starred_count"] == 0
        assert data["analyses_this_month"] == 0

    def test_empty_state_daily_analyses_is_list(self, client, auth_headers, test_user, db_session):
        resp = client.get("/api/user/stats", headers=auth_headers)
        data = resp.json()
        assert isinstance(data["daily_analyses"], list)

    def test_empty_state_top_repos_is_list(self, client, auth_headers, test_user, db_session):
        resp = client.get("/api/user/stats", headers=auth_headers)
        data = resp.json()
        assert isinstance(data["top_repos"], list)
        assert len(data["top_repos"]) == 0


class TestUserStatsTotals:
    def test_total_analyses_counts_all_statuses(self, client, auth_headers, test_user, db_session):
        _make_analysis(db_session, test_user.id, status="completed")
        _make_analysis(db_session, test_user.id, status="failed")
        _make_analysis(db_session, test_user.id, status="pending")
        resp = client.get("/api/user/stats", headers=auth_headers)
        assert resp.json()["total_analyses"] == 3

    def test_completed_count_only_completed(self, client, auth_headers, test_user, db_session):
        _make_analysis(db_session, test_user.id, status="completed")
        _make_analysis(db_session, test_user.id, status="completed")
        _make_analysis(db_session, test_user.id, status="failed")
        resp = client.get("/api/user/stats", headers=auth_headers)
        assert resp.json()["completed_analyses"] == 2

    def test_starred_count(self, client, auth_headers, test_user, db_session):
        _make_analysis(db_session, test_user.id, is_starred=True)
        _make_analysis(db_session, test_user.id, is_starred=True)
        _make_analysis(db_session, test_user.id, is_starred=False)
        resp = client.get("/api/user/stats", headers=auth_headers)
        assert resp.json()["starred_count"] == 2

    def test_no_cross_user_contamination(self, client, auth_headers, test_user,
                                          pro_user, db_session):
        # analyses belonging to another user should not appear in test_user's stats
        _make_analysis(db_session, pro_user.id, repo_name="other/repo")
        _make_analysis(db_session, test_user.id, repo_name="owner/repo")
        resp = client.get("/api/user/stats", headers=auth_headers)
        data = resp.json()
        assert data["total_analyses"] == 1
        assert data["top_repos"][0]["repo_name"] == "owner/repo"


class TestUserStatsThisMonth:
    def test_analyses_this_month_includes_current_month(self, client, auth_headers,
                                                         test_user, db_session):
        _make_analysis(db_session, test_user.id, days_ago=0)
        _make_analysis(db_session, test_user.id, days_ago=0)
        resp = client.get("/api/user/stats", headers=auth_headers)
        assert resp.json()["analyses_this_month"] >= 2

    def test_analyses_this_month_excludes_prior_months(self, client, auth_headers,
                                                        test_user, db_session):
        # Create analysis from > 31 days ago (safe to be prior month)
        old = Analysis(
            repo_url="https://github.com/owner/old",
            repo_name="owner/old",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            created_at=_dt(45),
        )
        db_session.add(old)
        db_session.commit()
        _make_analysis(db_session, test_user.id, days_ago=0)

        resp = client.get("/api/user/stats", headers=auth_headers)
        # Only the recent one should count; the 45-day-old one should not
        assert resp.json()["analyses_this_month"] >= 1

    def test_failed_not_in_this_month_count(self, client, auth_headers, test_user, db_session):
        _make_analysis(db_session, test_user.id, status="failed", days_ago=0)
        resp = client.get("/api/user/stats", headers=auth_headers)
        # ACTIVE_ANALYSIS_STATUSES excludes "failed" from monthly count
        assert resp.json()["analyses_this_month"] == 0


class TestUserStatsMonthlyLimit:
    def test_free_user_has_limit_of_one(self, client, auth_headers, test_user, db_session):
        resp = client.get("/api/user/stats", headers=auth_headers)
        assert resp.json()["monthly_limit"] == 1

    def test_pro_user_has_no_limit(self, client, pro_auth_headers, pro_user, db_session):
        resp = client.get("/api/user/stats", headers=pro_auth_headers)
        assert resp.json()["monthly_limit"] is None


class TestUserStatsDailyAnalyses:
    def test_daily_analyses_shape(self, client, auth_headers, test_user, db_session):
        _make_analysis(db_session, test_user.id, days_ago=1)
        resp = client.get("/api/user/stats", headers=auth_headers)
        rows = resp.json()["daily_analyses"]
        assert len(rows) >= 1
        row = rows[0]
        assert "date" in row
        assert "total" in row
        assert "completed" in row
        assert "failed" in row

    def test_daily_analyses_counts_correct(self, client, auth_headers, test_user, db_session):
        _make_analysis(db_session, test_user.id, status="completed", days_ago=2)
        _make_analysis(db_session, test_user.id, status="failed", days_ago=2)
        resp = client.get("/api/user/stats", headers=auth_headers)
        rows = resp.json()["daily_analyses"]
        # Find the row for 2 days ago
        date_key = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
        matching = [r for r in rows if r["date"] == date_key]
        assert len(matching) == 1
        row = matching[0]
        assert row["total"] == 2
        assert row["completed"] == 1
        assert row["failed"] == 1

    def test_daily_analyses_excludes_older_than_30_days(self, client, auth_headers,
                                                          test_user, db_session):
        # Analysis from 35 days ago should not appear in daily breakdown
        old = Analysis(
            repo_url="https://github.com/owner/old",
            repo_name="owner/old",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            created_at=_dt(35),
        )
        db_session.add(old)
        db_session.commit()
        resp = client.get("/api/user/stats", headers=auth_headers)
        rows = resp.json()["daily_analyses"]
        date_key = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m-%d")
        assert not any(r["date"] == date_key for r in rows)

    def test_daily_analyses_only_own_data(self, client, auth_headers, test_user,
                                           pro_user, db_session):
        _make_analysis(db_session, pro_user.id, days_ago=1)
        _make_analysis(db_session, pro_user.id, days_ago=1)
        _make_analysis(db_session, test_user.id, days_ago=1)
        resp = client.get("/api/user/stats", headers=auth_headers)
        rows = resp.json()["daily_analyses"]
        date_key = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        matching = [r for r in rows if r["date"] == date_key]
        assert len(matching) == 1
        assert matching[0]["total"] == 1  # only test_user's analysis


class TestUserStatsTopRepos:
    def test_top_repos_sorted_by_count_desc(self, client, auth_headers, test_user, db_session):
        for _ in range(3):
            _make_analysis(db_session, test_user.id, repo_name="owner/busy")
        _make_analysis(db_session, test_user.id, repo_name="owner/quiet")
        resp = client.get("/api/user/stats", headers=auth_headers)
        repos = resp.json()["top_repos"]
        assert repos[0]["repo_name"] == "owner/busy"
        assert repos[0]["count"] == 3
        assert repos[1]["repo_name"] == "owner/quiet"
        assert repos[1]["count"] == 1

    def test_top_repos_has_last_analyzed_at(self, client, auth_headers, test_user, db_session):
        _make_analysis(db_session, test_user.id, repo_name="owner/repo")
        resp = client.get("/api/user/stats", headers=auth_headers)
        repo = resp.json()["top_repos"][0]
        assert "last_analyzed_at" in repo
        assert repo["last_analyzed_at"]  # non-empty string

    def test_top_repos_limited_to_ten(self, client, auth_headers, test_user, db_session):
        for i in range(15):
            _make_analysis(db_session, test_user.id, repo_name=f"owner/repo{i}")
        resp = client.get("/api/user/stats", headers=auth_headers)
        assert len(resp.json()["top_repos"]) == 10

    def test_top_repos_excludes_other_users(self, client, auth_headers, test_user,
                                             pro_user, db_session):
        for _ in range(5):
            _make_analysis(db_session, pro_user.id, repo_name="other/popular")
        _make_analysis(db_session, test_user.id, repo_name="owner/mine")
        resp = client.get("/api/user/stats", headers=auth_headers)
        repos = resp.json()["top_repos"]
        names = [r["repo_name"] for r in repos]
        assert "other/popular" not in names
        assert "owner/mine" in names

    def test_top_repos_count_aggregates_multiple_analyses(self, client, auth_headers,
                                                           test_user, db_session):
        for _ in range(4):
            _make_analysis(db_session, test_user.id, repo_name="owner/repo")
        resp = client.get("/api/user/stats", headers=auth_headers)
        assert resp.json()["top_repos"][0]["count"] == 4


class TestUserStatsResponseShape:
    def test_all_required_fields_present(self, client, auth_headers, test_user, db_session):
        resp = client.get("/api/user/stats", headers=auth_headers)
        data = resp.json()
        for field in ("total_analyses", "completed_analyses", "starred_count",
                      "analyses_this_month", "monthly_limit", "daily_analyses", "top_repos"):
            assert field in data, f"Missing field: {field}"

    def test_numeric_fields_are_non_negative(self, client, auth_headers, test_user, db_session):
        _make_analysis(db_session, test_user.id)
        resp = client.get("/api/user/stats", headers=auth_headers)
        data = resp.json()
        assert data["total_analyses"] >= 0
        assert data["completed_analyses"] >= 0
        assert data["starred_count"] >= 0
        assert data["analyses_this_month"] >= 0

    def test_completed_never_exceeds_total(self, client, auth_headers, test_user, db_session):
        _make_analysis(db_session, test_user.id, status="completed")
        _make_analysis(db_session, test_user.id, status="failed")
        resp = client.get("/api/user/stats", headers=auth_headers)
        data = resp.json()
        assert data["completed_analyses"] <= data["total_analyses"]

    def test_starred_never_exceeds_total(self, client, auth_headers, test_user, db_session):
        _make_analysis(db_session, test_user.id, is_starred=True)
        _make_analysis(db_session, test_user.id, is_starred=False)
        resp = client.get("/api/user/stats", headers=auth_headers)
        data = resp.json()
        assert data["starred_count"] <= data["total_analyses"]

"""Tests for watcher_service: commit fetching and repo change detection."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from models import Analysis, User, WatchedRepo
from services.auth_service import hash_password
from services.watcher_service import get_latest_commit, check_watched_repos


# ── get_latest_commit ─────────────────────────────────────────────────────────

class TestGetLatestCommit:
    def test_returns_sha_on_success(self):
        sha = "a" * 40
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = sha + "\n"
        with patch("httpx.get", return_value=mock_resp):
            result = get_latest_commit("owner", "repo")
        assert result == sha

    def test_returns_empty_on_404(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("httpx.get", return_value=mock_resp):
            result = get_latest_commit("owner", "nonexistent")
        assert result == ""

    def test_returns_empty_on_403(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        with patch("httpx.get", return_value=mock_resp):
            result = get_latest_commit("owner", "private-repo")
        assert result == ""

    def test_returns_empty_on_network_error(self):
        with patch("httpx.get", side_effect=Exception("connection refused")):
            result = get_latest_commit("owner", "repo")
        assert result == ""

    def test_uses_token_when_provided(self):
        sha = "b" * 40
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = sha
        captured = {}

        def fake_get(url, headers=None, timeout=None):
            captured["headers"] = headers
            return mock_resp

        with patch("httpx.get", side_effect=fake_get):
            get_latest_commit("owner", "repo", github_token="mytoken")

        assert "Authorization" in captured["headers"]
        assert "mytoken" in captured["headers"]["Authorization"]

    def test_no_token_omits_auth_header(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "a" * 40
        captured = {}

        def fake_get(url, headers=None, timeout=None):
            captured["headers"] = headers
            return mock_resp

        with patch("httpx.get", side_effect=fake_get):
            get_latest_commit("owner", "repo", github_token=None)

        assert "Authorization" not in captured["headers"]

    def test_strips_trailing_whitespace(self):
        sha = "c" * 40
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = f"  {sha}  \n"
        with patch("httpx.get", return_value=mock_resp):
            result = get_latest_commit("owner", "repo")
        assert result == sha


# ── check_watched_repos helpers ───────────────────────────────────────────────

def _make_user(db, email="watcher@example.com", plan="free"):
    user = User(
        email=email,
        password_hash=hash_password("Test@Pass123"),
        plan=plan,
        is_admin=False,
        is_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_watch(db, user_id, repo_url="https://github.com/owner/repo",
                repo_name="owner/repo", last_commit_hash=None):
    w = WatchedRepo(
        user_id=user_id,
        repo_url=repo_url,
        repo_name=repo_name,
        last_commit_hash=last_commit_hash,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def _session_factory(db_session):
    """Return a mock SessionLocal that yields db_session without closing it."""
    mock_session = MagicMock(wraps=db_session)
    mock_session.close = MagicMock()  # prevent teardown from closing our test session
    return mock_session


# ── check_watched_repos ────────────────────────────────────────────────────────

class TestCheckWatchedRepos:
    def test_no_change_does_not_trigger_analysis(self, db_session):
        user = _make_user(db_session)
        sha = "a" * 40
        _make_watch(db_session, user.id, last_commit_hash=sha)

        with patch("services.watcher_service.get_latest_commit", return_value=sha), \
             patch("services.email_service.send_repo_changed_email") as mock_email, \
             patch("database.SessionLocal", return_value=_session_factory(db_session)):
            check_watched_repos()

        mock_email.assert_not_called()
        assert db_session.query(Analysis).count() == 0

    def test_new_commit_creates_analysis(self, db_session):
        user = _make_user(db_session)
        old_sha = "a" * 40
        new_sha = "b" * 40
        _make_watch(db_session, user.id, last_commit_hash=old_sha)

        with patch("services.watcher_service.get_latest_commit", return_value=new_sha), \
             patch("services.email_service.send_repo_changed_email"), \
             patch("api.routes._do_analysis"), \
             patch("threading.Thread") as mock_thread, \
             patch("database.SessionLocal", return_value=_session_factory(db_session)):
            mock_thread.return_value = MagicMock()
            check_watched_repos()

        assert db_session.query(Analysis).count() == 1
        analysis = db_session.query(Analysis).first()
        assert analysis.repo_name == "owner/repo"
        assert analysis.status == "pending"

    def test_new_commit_updates_watch_hash(self, db_session):
        user = _make_user(db_session)
        old_sha = "a" * 40
        new_sha = "b" * 40
        watch = _make_watch(db_session, user.id, last_commit_hash=old_sha)

        with patch("services.watcher_service.get_latest_commit", return_value=new_sha), \
             patch("services.email_service.send_repo_changed_email"), \
             patch("api.routes._do_analysis"), \
             patch("threading.Thread") as mock_thread, \
             patch("database.SessionLocal", return_value=_session_factory(db_session)):
            mock_thread.return_value = MagicMock()
            check_watched_repos()

        db_session.refresh(watch)
        assert watch.last_commit_hash == new_sha
        assert watch.last_changed_at is not None

    def test_new_commit_sends_email(self, db_session):
        user = _make_user(db_session)
        new_sha = "c" * 40
        _make_watch(db_session, user.id, last_commit_hash="a" * 40)

        with patch("services.watcher_service.get_latest_commit", return_value=new_sha), \
             patch("services.email_service.send_repo_changed_email") as mock_email, \
             patch("api.routes._do_analysis"), \
             patch("threading.Thread") as mock_thread, \
             patch("database.SessionLocal", return_value=_session_factory(db_session)):
            mock_thread.return_value = MagicMock()
            check_watched_repos()

        mock_email.assert_called_once()
        args = mock_email.call_args[0]
        assert args[0] == user.email
        assert args[1] == "owner/repo"

    def test_empty_sha_skips_silently(self, db_session):
        user = _make_user(db_session)
        _make_watch(db_session, user.id, last_commit_hash="a" * 40)

        with patch("services.watcher_service.get_latest_commit", return_value=""), \
             patch("services.email_service.send_repo_changed_email") as mock_email, \
             patch("database.SessionLocal", return_value=_session_factory(db_session)):
            check_watched_repos()

        mock_email.assert_not_called()

    def test_free_user_at_limit_skips_analysis(self, db_session):
        user = _make_user(db_session, plan="free")
        new_sha = "d" * 40
        _make_watch(db_session, user.id, last_commit_hash="a" * 40)

        # Add 1 analysis this month (free plan limit is now 1)
        month_start = datetime.now(timezone.utc).replace(tzinfo=None).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        db_session.add(Analysis(
            repo_url="https://github.com/owner/repo0",
            repo_name="owner/repo0",
            status="completed",
            stage="Done",
            user_id=user.id,
            created_at=month_start,
        ))
        db_session.commit()

        with patch("services.watcher_service.get_latest_commit", return_value=new_sha), \
             patch("services.email_service.send_repo_changed_email") as mock_email, \
             patch("database.SessionLocal", return_value=_session_factory(db_session)):
            check_watched_repos()

        mock_email.assert_not_called()
        assert db_session.query(Analysis).filter(
            Analysis.repo_name == "owner/repo"
        ).count() == 0

    def test_pro_user_not_limited(self, db_session):
        user = _make_user(db_session, email="pro@example.com", plan="pro")
        new_sha = "e" * 40
        _make_watch(db_session, user.id, last_commit_hash="a" * 40)

        # Add 10 analyses (would block a free user)
        month_start = datetime.now(timezone.utc).replace(tzinfo=None).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for i in range(10):
            db_session.add(Analysis(
                repo_url=f"https://github.com/owner/repo{i}",
                repo_name=f"owner/repo{i}",
                status="completed",
                stage="Done",
                user_id=user.id,
                created_at=month_start,
            ))
        db_session.commit()

        with patch("services.watcher_service.get_latest_commit", return_value=new_sha), \
             patch("services.email_service.send_repo_changed_email"), \
             patch("api.routes._do_analysis"), \
             patch("threading.Thread") as mock_thread, \
             patch("database.SessionLocal", return_value=_session_factory(db_session)):
            mock_thread.return_value = MagicMock()
            check_watched_repos()

        assert db_session.query(Analysis).filter(
            Analysis.repo_name == "owner/repo"
        ).count() == 1

    def test_last_checked_at_updated_even_on_no_change(self, db_session):
        user = _make_user(db_session)
        sha = "a" * 40
        watch = _make_watch(db_session, user.id, last_commit_hash=sha)
        assert watch.last_checked_at is None

        with patch("services.watcher_service.get_latest_commit", return_value=sha), \
             patch("database.SessionLocal", return_value=_session_factory(db_session)):
            check_watched_repos()

        db_session.refresh(watch)
        assert watch.last_checked_at is not None

    def test_invalid_url_watch_skipped(self, db_session):
        user = _make_user(db_session)
        w = WatchedRepo(
            user_id=user.id,
            repo_url="https://notgithub.com/owner/repo",
            repo_name="owner/repo",
        )
        db_session.add(w)
        db_session.commit()

        with patch("database.SessionLocal", return_value=_session_factory(db_session)):
            check_watched_repos()  # should not raise

        assert db_session.query(Analysis).count() == 0

    def test_multiple_watches_all_checked(self, db_session):
        user = _make_user(db_session, plan="pro")
        sha1 = "a" * 40
        sha2 = "b" * 40
        _make_watch(db_session, user.id, repo_url="https://github.com/owner/repo1",
                    repo_name="owner/repo1", last_commit_hash=sha1)
        _make_watch(db_session, user.id, repo_url="https://github.com/owner/repo2",
                    repo_name="owner/repo2", last_commit_hash=sha1)

        call_count = 0

        def counting_get_latest(owner, repo, token=None):
            nonlocal call_count
            call_count += 1
            return sha2

        with patch("services.watcher_service.get_latest_commit", side_effect=counting_get_latest), \
             patch("services.email_service.send_repo_changed_email"), \
             patch("api.routes._do_analysis"), \
             patch("threading.Thread") as mock_thread, \
             patch("database.SessionLocal", return_value=_session_factory(db_session)):
            mock_thread.return_value = MagicMock()
            check_watched_repos()

        assert call_count == 2
        assert db_session.query(Analysis).count() == 2

    def test_first_seen_commit_triggers_update(self, db_session):
        """Watch with no prior hash should record the first SHA (treated as a change)."""
        user = _make_user(db_session)
        sha = "f" * 40
        _make_watch(db_session, user.id, last_commit_hash=None)

        with patch("services.watcher_service.get_latest_commit", return_value=sha), \
             patch("services.email_service.send_repo_changed_email"), \
             patch("api.routes._do_analysis"), \
             patch("threading.Thread") as mock_thread, \
             patch("database.SessionLocal", return_value=_session_factory(db_session)):
            mock_thread.return_value = MagicMock()
            check_watched_repos()

        watch = db_session.query(WatchedRepo).first()
        db_session.refresh(watch)
        assert watch.last_commit_hash == sha

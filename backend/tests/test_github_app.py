"""Tests for GitHub App webhook handler."""
import hashlib
import hmac
import json

import pytest
from unittest.mock import patch, MagicMock

from models import Analysis, GitHubInstallation


WEBHOOK_SECRET = "whsec_test_github_app"


def _sign(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    """Compute x-hub-signature-256 header value."""
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _session_factory(session):
    """Return a callable that yields the same session (prevents close)."""
    def factory():
        return session
    return factory


def _post_webhook(client, event: str, payload: dict, secret: str = WEBHOOK_SECRET):
    """Helper to POST a signed webhook."""
    body = json.dumps(payload).encode()
    sig = ""
    if secret:
        sig = _sign(body, secret)
    return client.post(
        "/api/github-app/webhook",
        content=body,
        headers={
            "x-github-event": event,
            "x-hub-signature-256": sig,
            "content-type": "application/json",
        },
    )


# ── Signature verification ────────────────────────────────────────────────


class TestSignatureVerification:
    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    def test_valid_signature_accepted(self, client):
        resp = _post_webhook(client, "ping", {"zen": "hello"})
        assert resp.status_code == 200

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    def test_invalid_signature_rejected(self, client):
        body = json.dumps({"zen": "hello"}).encode()
        resp = client.post(
            "/api/github-app/webhook",
            content=body,
            headers={
                "x-github-event": "ping",
                "x-hub-signature-256": "sha256=bad",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 401

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    def test_missing_signature_rejected(self, client):
        body = json.dumps({"zen": "hello"}).encode()
        resp = client.post(
            "/api/github-app/webhook",
            content=body,
            headers={
                "x-github-event": "ping",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 401

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", "")
    def test_no_secret_configured_rejects(self, client):
        """When GITHUB_WEBHOOK_SECRET is empty, all requests are rejected."""
        body = json.dumps({"zen": "hello"}).encode()
        resp = client.post(
            "/api/github-app/webhook",
            content=body,
            headers={
                "x-github-event": "ping",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 401

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    def test_invalid_json_returns_400(self, client):
        body = b"not json"
        resp = client.post(
            "/api/github-app/webhook",
            content=body,
            headers={
                "x-github-event": "push",
                "x-hub-signature-256": _sign(body),
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 400


# ── Installation events ──────────────────────────────────────────────────


class TestInstallationEvent:
    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    @patch("api.github_app._trigger_background_analysis")
    def test_installation_created_stores_record(self, mock_trigger, client, db_session):
        with patch("api.github_app.SessionLocal", _session_factory(db_session)):
            payload = {
                "action": "created",
                "installation": {
                    "id": 12345,
                    "account": {"login": "test-org", "type": "Organization"},
                },
                "repositories": [
                    {"full_name": "test-org/repo-a"},
                    {"full_name": "test-org/repo-b"},
                ],
            }
            resp = _post_webhook(client, "installation", payload, secret=WEBHOOK_SECRET)

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "installed"
        assert data["repos_queued"] == 2

        # Verify DB record
        gi = db_session.query(GitHubInstallation).filter(
            GitHubInstallation.installation_id == 12345
        ).first()
        assert gi is not None
        assert gi.account_login == "test-org"
        assert gi.account_type == "Organization"

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    @patch("api.github_app._trigger_background_analysis")
    def test_installation_created_limits_to_10_repos(self, mock_trigger, client, db_session):
        with patch("api.github_app.SessionLocal", _session_factory(db_session)):
            payload = {
                "action": "created",
                "installation": {
                    "id": 99999,
                    "account": {"login": "user1", "type": "User"},
                },
                "repositories": [{"full_name": f"user1/repo-{i}"} for i in range(12)],
            }
            resp = _post_webhook(client, "installation", payload, secret=WEBHOOK_SECRET)

        assert resp.status_code == 200
        assert resp.json()["repos_queued"] == 10
        assert mock_trigger.call_count == 10

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    def test_installation_deleted_removes_record(self, client, db_session):
        # Pre-create installation
        gi = GitHubInstallation(
            installation_id=55555,
            account_login="delete-me",
            account_type="User",
        )
        db_session.add(gi)
        db_session.commit()

        with patch("api.github_app.SessionLocal", _session_factory(db_session)):
            payload = {
                "action": "deleted",
                "installation": {
                    "id": 55555,
                    "account": {"login": "delete-me", "type": "User"},
                },
            }
            resp = _post_webhook(client, "installation", payload, secret=WEBHOOK_SECRET)

        assert resp.status_code == 200
        assert resp.json()["status"] == "uninstalled"

        assert db_session.query(GitHubInstallation).filter(
            GitHubInstallation.installation_id == 55555
        ).first() is None


# ── Push events ──────────────────────────────────────────────────────────


class TestPushEvent:
    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    @patch("api.github_app._trigger_background_analysis")
    def test_push_with_enough_changes_triggers(self, mock_trigger, client):
        payload = {
            "ref": "refs/heads/main",
            "repository": {"default_branch": "main", "full_name": "org/repo"},
            "commits": [
                {"added": ["a.py", "b.py", "c.py"], "modified": ["d.py"], "removed": ["e.py"]},
            ],
        }
        resp = _post_webhook(client, "push", payload, secret=WEBHOOK_SECRET)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "analysis_triggered"
        assert data["files_changed"] == 5
        mock_trigger.assert_called_once_with("org/repo")

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    @patch("api.github_app._trigger_background_analysis")
    def test_push_with_few_changes_ignored(self, mock_trigger, client):
        payload = {
            "ref": "refs/heads/main",
            "repository": {"default_branch": "main", "full_name": "org/repo"},
            "commits": [
                {"added": ["a.py"], "modified": [], "removed": []},
            ],
        }
        resp = _post_webhook(client, "push", payload, secret=WEBHOOK_SECRET)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
        mock_trigger.assert_not_called()

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    @patch("api.github_app._trigger_background_analysis")
    def test_push_to_non_default_branch_ignored(self, mock_trigger, client):
        payload = {
            "ref": "refs/heads/feature-branch",
            "repository": {"default_branch": "main", "full_name": "org/repo"},
            "commits": [
                {"added": [f"file{i}.py" for i in range(20)], "modified": [], "removed": []},
            ],
        }
        resp = _post_webhook(client, "push", payload, secret=WEBHOOK_SECRET)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
        assert "not default branch" in resp.json()["reason"]
        mock_trigger.assert_not_called()

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    @patch("api.github_app._trigger_background_analysis")
    def test_push_deduplicates_files_across_commits(self, mock_trigger, client):
        """Same file modified in multiple commits counts once."""
        payload = {
            "ref": "refs/heads/main",
            "repository": {"default_branch": "main", "full_name": "org/repo"},
            "commits": [
                {"added": ["a.py", "b.py"], "modified": [], "removed": []},
                {"added": [], "modified": ["a.py", "b.py"], "removed": []},
            ],
        }
        resp = _post_webhook(client, "push", payload, secret=WEBHOOK_SECRET)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
        mock_trigger.assert_not_called()


# ── Pull request events ──────────────────────────────────────────────────


class TestPullRequestEvent:
    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    def test_pr_not_opened_ignored(self, client):
        payload = {
            "action": "synchronize",
            "pull_request": {"number": 1},
            "repository": {"full_name": "org/repo"},
            "installation": {"id": 123},
        }
        resp = _post_webhook(client, "pull_request", payload, secret=WEBHOOK_SECRET)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    def test_pr_opened_no_analysis_ignored(self, client, db_session):
        with patch("api.github_app.SessionLocal", _session_factory(db_session)):
            payload = {
                "action": "opened",
                "pull_request": {"number": 42},
                "repository": {"full_name": "org/new-repo"},
                "installation": {"id": 123},
            }
            resp = _post_webhook(client, "pull_request", payload, secret=WEBHOOK_SECRET)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    @patch("api.github_app._get_installation_token", return_value="ghs_test_token")
    @patch("httpx.post")
    def test_pr_opened_with_analysis_posts_comment(self, mock_post, mock_token, client, db_session):
        """PR on a repo with completed analysis should post architecture comment."""
        analysis = Analysis(
            repo_url="https://github.com/org/analyzed-repo",
            repo_name="org/analyzed-repo",
            status="completed",
            result=json.dumps({
                "architecture": {
                    "architecture_type": "Monolith",
                    "description": "A web app",
                    "tech_stack": ["Python", "FastAPI"],
                },
                "key_files": [
                    {"path": "main.py", "reason": "Entry point"},
                    {"path": "models.py", "reason": "DB models"},
                ],
                "patterns": [
                    {"name": "MVC", "explanation": "Model-View-Controller pattern"},
                ],
            }),
        )
        db_session.add(analysis)
        db_session.commit()

        mock_post.return_value = MagicMock(status_code=201)

        with patch("api.github_app.SessionLocal", _session_factory(db_session)):
            payload = {
                "action": "opened",
                "pull_request": {"number": 7},
                "repository": {"full_name": "org/analyzed-repo"},
                "installation": {"id": 456},
            }
            resp = _post_webhook(client, "pull_request", payload, secret=WEBHOOK_SECRET)

        assert resp.status_code == 200
        assert resp.json()["status"] == "commented"

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "org/analyzed-repo/issues/7/comments" in call_args.args[0]
        body = call_args.kwargs["json"]["body"]
        assert "Monolith" in body
        assert "main.py" in body

    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    def test_pr_opened_no_installation_ignored(self, client):
        payload = {
            "action": "opened",
            "pull_request": {"number": 1},
            "repository": {"full_name": "org/repo"},
            "installation": {},
        }
        resp = _post_webhook(client, "pull_request", payload, secret=WEBHOOK_SECRET)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"


# ── Unknown events ───────────────────────────────────────────────────────


class TestUnknownEvent:
    @patch("api.github_app.GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    def test_unknown_event_returns_ignored(self, client):
        resp = _post_webhook(client, "star", {"action": "created"}, secret=WEBHOOK_SECRET)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

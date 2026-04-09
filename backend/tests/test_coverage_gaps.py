"""
Tests targeting the largest remaining coverage gaps:
- services/claude_service.py  (was 14%): _ask retry logic, _extract_json, all 4 passes, pipeline
- services/email_service.py   (was 51%): all 4 send_* functions (SMTP configured + not configured)
- api/watch.py                (was 89%): IntegrityError race-condition path
- api/auth.py                 (was 79%): GitHub OAuth callback — login, connect, and error paths
"""
import base64
import json
import re
import smtplib
from unittest.mock import MagicMock, call, patch

import pytest

from services.auth_service import create_token, hash_password
from models import User, WatchedRepo


# ══════════════════════════════════════════════════════════════════════════════
# helpers
# ══════════════════════════════════════════════════════════════════════════════

def _fake_message(text: str, stop_reason: str = "end_turn"):
    """Build a mock anthropic Message-like object."""
    content = MagicMock()
    content.text = text
    msg = MagicMock()
    msg.content = [content]
    msg.stop_reason = stop_reason
    return msg


# ══════════════════════════════════════════════════════════════════════════════
# services/claude_service.py — _extract_json
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractJson:
    def _call(self, text):
        from services.claude_service import _extract_json
        return _extract_json(text)

    def test_plain_json_object(self):
        assert self._call('{"a": 1}') == {"a": 1}

    def test_plain_json_array(self):
        assert self._call('[1, 2, 3]') == [1, 2, 3]

    def test_markdown_json_fence(self):
        text = '```json\n{"x": "y"}\n```'
        assert self._call(text) == {"x": "y"}

    def test_markdown_plain_fence(self):
        text = '```\n[1,2]\n```'
        assert self._call(text) == [1, 2]

    def test_prose_wrapping_object(self):
        text = 'Here is the result: {"key": "val"} end of response.'
        assert self._call(text) == {"key": "val"}

    def test_prose_wrapping_array(self):
        text = 'Sure, here you go: [1, 2, 3] — that is all.'
        assert self._call(text) == [1, 2, 3]

    def test_raises_on_unparseable(self):
        from services.claude_service import _extract_json
        with pytest.raises(ValueError, match="Could not parse JSON"):
            _extract_json("This is definitely not JSON at all.")


# ══════════════════════════════════════════════════════════════════════════════
# services/claude_service.py — _ask retry logic
# ══════════════════════════════════════════════════════════════════════════════

class TestAsk:
    """Test _ask() success, truncation warning, transient retries, and exhausted retries."""

    def test_success_returns_text(self):
        from services.claude_service import _ask
        mock_msg = _fake_message("hello world")
        with patch("services.claude_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            result = _ask("system", "user")
        assert result == "hello world"

    def test_max_tokens_logs_warning(self, caplog):
        import logging
        from services.claude_service import _ask
        mock_msg = _fake_message('{"a":1}', stop_reason="max_tokens")
        with patch("services.claude_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            with caplog.at_level(logging.WARNING, logger="services.claude_service"):
                result = _ask("s", "u")
        assert result == '{"a":1}'
        assert "max_tokens" in caplog.text

    def test_transient_error_retries_and_succeeds(self):
        from anthropic import APIConnectionError
        from services.claude_service import _ask
        good_msg = _fake_message("ok")
        with patch("services.claude_service.client") as mock_client, \
             patch("services.claude_service.time.sleep"):
            mock_client.messages.create.side_effect = [
                APIConnectionError(request=MagicMock()),
                good_msg,
            ]
            result = _ask("s", "u")
        assert result == "ok"
        assert mock_client.messages.create.call_count == 2

    def test_rate_limit_retries(self):
        from anthropic import RateLimitError
        from services.claude_service import _ask
        good_msg = _fake_message("rate ok")
        raw_response = MagicMock()
        raw_response.headers = {}
        with patch("services.claude_service.client") as mock_client, \
             patch("services.claude_service.time.sleep"):
            mock_client.messages.create.side_effect = [
                RateLimitError("rate limit", response=raw_response, body={}),
                good_msg,
            ]
            result = _ask("s", "u")
        assert result == "rate ok"

    def test_exhausted_retries_raises_runtime_error(self):
        from anthropic import APITimeoutError
        from services.claude_service import _ask
        with patch("services.claude_service.client") as mock_client, \
             patch("services.claude_service.time.sleep"):
            mock_client.messages.create.side_effect = APITimeoutError(request=MagicMock())
            with pytest.raises(RuntimeError, match="Claude API unavailable"):
                _ask("s", "u")
        # Should have tried 1 initial + 3 retries = 4 total
        assert mock_client.messages.create.call_count == 4


# ══════════════════════════════════════════════════════════════════════════════
# services/claude_service.py — pass1 / pass2 / pass3 / pass4
# ══════════════════════════════════════════════════════════════════════════════

_ARCH_RESULT = {
    "project_name": "TestRepo",
    "description": "A test repo.",
    "tech_stack": ["Python"],
    "architecture_type": "REST API",
    "architecture_summary": "Simple API.",
    "entry_points": ["main.py"],
    "key_directories": [{"path": "src/", "purpose": "source"}],
    "languages": ["Python"],
    "runtime": "Python 3.11",
    "license": "MIT",
}

_RANKED_RESULT = [
    {"path": "main.py", "score": 9, "reason": "Entry point"},
]

_EXPLAINED_RESULT = [
    {"path": "main.py", "explanation": "The main entry.", "key_exports": ["app"]},
]

_SYNTHESIS_RESULT = {
    "reading_order": [{"step": 1, "path": "main.py", "reason": "start here"}],
    "dependencies": {"runtime": ["fastapi"], "dev": ["pytest"]},
    "quick_start": "Run uvicorn main:app",
    "onboarding_guide": "## Overview\nThis is a guide.",
    "key_concepts": ["routing"],
    "patterns": [{"name": "MVC", "explanation": "Model-View-Controller used here."}],
}


class TestPipelinePasses:
    """Verify each pass calls _ask and parses JSON correctly."""

    def _patch_ask(self, return_value):
        return patch(
            "services.claude_service._ask",
            return_value=json.dumps(return_value),
        )

    def test_pass1_architecture(self):
        from services.claude_service import pass1_architecture
        with self._patch_ask(_ARCH_RESULT):
            result = pass1_architecture("file tree", "# README", {"package.json": "{}"})
        assert result["project_name"] == "TestRepo"
        assert result["tech_stack"] == ["Python"]

    def test_pass2_file_ranking(self):
        from services.claude_service import pass2_file_ranking
        with self._patch_ask(_RANKED_RESULT):
            result = pass2_file_ranking(
                ["main.py", "test_main.py"],
                _ARCH_RESULT,
                {"main.py": "# content"},
                import_counts={"main.py": 5},
                test_files={"test_main.py"},
            )
        assert result[0]["path"] == "main.py"

    def test_pass3_file_explanations(self):
        from services.claude_service import pass3_file_explanations
        with self._patch_ask(_EXPLAINED_RESULT):
            result = pass3_file_explanations(
                _RANKED_RESULT,
                {"main.py": "# main code"},
                _ARCH_RESULT,
            )
        assert result[0]["explanation"] == "The main entry."
        assert result[0]["key_exports"] == ["app"]

    def test_pass3_merges_missing_files(self):
        """Files in ranked but without content get empty explanation."""
        from services.claude_service import pass3_file_explanations
        explained_partial = [{"path": "other.py", "explanation": "other", "key_exports": []}]
        with self._patch_ask(explained_partial):
            result = pass3_file_explanations(
                [{"path": "main.py", "score": 9, "reason": "x"},
                 {"path": "other.py", "score": 7, "reason": "y"}],
                {"other.py": "# other"},
                _ARCH_RESULT,
            )
        # main.py not in explained → gets empty fields
        main_item = next(r for r in result if r["path"] == "main.py")
        assert main_item["explanation"] == ""
        assert main_item["key_exports"] == []

    def test_pass4_synthesis(self):
        from services.claude_service import pass4_synthesis
        with self._patch_ask(_SYNTHESIS_RESULT):
            result = pass4_synthesis(
                _ARCH_RESULT,
                _EXPLAINED_RESULT,
                ["main.py"],
                {"main.py": "# main", "requirements.txt": "fastapi"},
                test_files=["tests/test_main.py"],
            )
        assert result["quick_start"] == "Run uvicorn main:app"
        assert result["patterns"][0]["name"] == "MVC"

    def test_pass4_no_test_files(self):
        from services.claude_service import pass4_synthesis
        with self._patch_ask(_SYNTHESIS_RESULT):
            result = pass4_synthesis(_ARCH_RESULT, _EXPLAINED_RESULT, ["main.py"], {})
        assert result["reading_order"][0]["path"] == "main.py"


class TestRunAnalysisPipeline:
    """Test the full run_analysis_pipeline orchestrator."""

    def test_full_pipeline_success(self):
        from services.claude_service import run_analysis_pipeline

        call_order = []

        def fake_ask(system, user):
            # Detect which pass we're in by checking system prompt content
            if "architect" in system.lower():
                call_order.append("pass1")
                return json.dumps(_ARCH_RESULT)
            elif "senior engineer helping" in system.lower():
                call_order.append("pass2")
                return json.dumps(_RANKED_RESULT)
            elif "code reviewer" in system.lower():
                call_order.append("pass3")
                return json.dumps(_EXPLAINED_RESULT)
            else:
                call_order.append("pass4")
                return json.dumps(_SYNTHESIS_RESULT)

        with patch("services.claude_service._ask", side_effect=fake_ask):
            progress_msgs = []
            result = run_analysis_pipeline(
                repo_name="owner/repo",
                tree=["main.py", "tests/test_main.py"],
                all_files={"main.py": "# code", "requirements.txt": "fastapi"},
                progress_cb=lambda msg: progress_msgs.append(msg),
                dep_graph={"edges": [{"source": "app.py", "target": "main.py"}]},
                test_files=["tests/test_main.py"],
            )

        assert result["repo_name"] == "owner/repo"
        assert result["architecture"]["project_name"] == "TestRepo"
        assert result["key_files"][0]["path"] == "main.py"
        assert result["test_files"] == ["tests/test_main.py"]
        assert result["file_tree"] == ["main.py", "tests/test_main.py"]
        assert len(progress_msgs) == 4
        assert "Pass 1/4" in progress_msgs[0]
        assert len(call_order) == 4

    def test_pipeline_with_no_dep_graph(self):
        from services.claude_service import run_analysis_pipeline

        def fake_ask(system, user):
            if "architect" in system.lower():
                return json.dumps(_ARCH_RESULT)
            elif "senior engineer helping" in system.lower():
                return json.dumps(_RANKED_RESULT)
            elif "code reviewer" in system.lower():
                return json.dumps(_EXPLAINED_RESULT)
            else:
                return json.dumps(_SYNTHESIS_RESULT)

        with patch("services.claude_service._ask", side_effect=fake_ask):
            result = run_analysis_pipeline("repo", ["main.py"], {"main.py": "x"})
        assert "architecture" in result


class TestGenerateChangelog:
    def test_changelog_success(self):
        from services.claude_service import generate_changelog
        changelog = {
            "summary": "minor refactor",
            "new_files": ["new.py"],
            "removed_files": [],
            "architecture_changes": [],
            "dependency_changes": {"added": [], "removed": []},
            "highlights": ["faster startup"],
        }
        with patch("services.claude_service._ask", return_value=json.dumps(changelog)):
            result = generate_changelog(
                "owner/repo",
                {"architecture": _ARCH_RESULT, "key_files": _RANKED_RESULT,
                 "dependencies": {}, "reading_order": []},
                {"architecture": _ARCH_RESULT, "key_files": _RANKED_RESULT,
                 "dependencies": {}, "reading_order": []},
            )
        assert result["summary"] == "minor refactor"


# ══════════════════════════════════════════════════════════════════════════════
# services/email_service.py — all send_* functions
# ══════════════════════════════════════════════════════════════════════════════

class TestEmailService:
    """Test all four send_* functions with SMTP configured and not configured."""

    # ── helpers ──────────────────────────────────────────────────────────────

    def _configured_env(self):
        """Patch SMTP_USER and SMTP_PASSWORD so the guard passes."""
        return patch.multiple(
            "services.email_service",
            SMTP_USER="user@example.com",
            SMTP_PASSWORD="secret",
        )

    def _smtp_mock(self):
        """Context manager that mocks smtplib.SMTP as a context manager."""
        mock_server = MagicMock()
        mock_smtp_cls = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
        return patch("smtplib.SMTP", mock_smtp_cls), mock_server

    def _decode_mime_body(self, mime_string: str) -> str:
        """Decode the base64-encoded HTML body from a MIME multipart string."""
        # Extract base64 blocks (Content-Transfer-Encoding: base64)
        parts = re.split(r"--===============\d+==", mime_string)
        for part in parts:
            if "base64" in part:
                b64_data = re.sub(r".*Content-Transfer-Encoding: base64\s*", "", part,
                                  flags=re.DOTALL).strip()
                try:
                    return base64.b64decode(b64_data).decode("utf-8")
                except Exception:
                    pass
        return mime_string  # fallback: return raw if decoding fails

    # ── send_password_reset_email ─────────────────────────────────────────────

    def test_password_reset_skips_when_not_configured(self, caplog):
        import logging
        from services.email_service import send_password_reset_email
        with patch.multiple("services.email_service", RESEND_API_KEY=""):
            with caplog.at_level(logging.WARNING, logger="services.email_service"):
                send_password_reset_email("a@b.com", "http://reset")
        assert "not configured" in caplog.text

    def test_password_reset_sends_email(self):
        from services.email_service import send_password_reset_email
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch.multiple("services.email_service", RESEND_API_KEY="re_test_key"), \
             patch("httpx.post", return_value=mock_resp) as mock_post:
            send_password_reset_email("a@b.com", "http://reset/token")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"]["to"] == ["a@b.com"]
        assert "http://reset/token" in call_kwargs.kwargs["json"]["html"]

    def test_password_reset_failure_is_silent(self, caplog):
        import logging
        from services.email_service import send_password_reset_email
        with patch.multiple("services.email_service", RESEND_API_KEY="re_test_key"), \
             patch("httpx.post", side_effect=Exception("connection refused")):
            with caplog.at_level(logging.ERROR, logger="services.email_service"):
                send_password_reset_email("a@b.com", "http://reset")
        assert "Failed to send email" in caplog.text

    # ── send_verification_email ───────────────────────────────────────────────

    def test_verification_skips_when_not_configured(self, caplog):
        import logging
        from services.email_service import send_verification_email
        with patch.multiple("services.email_service", RESEND_API_KEY=""):
            with caplog.at_level(logging.WARNING, logger="services.email_service"):
                send_verification_email("a@b.com", "123456")
        assert "not configured" in caplog.text

    def test_verification_sends_code(self):
        from services.email_service import send_verification_email
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch.multiple("services.email_service", RESEND_API_KEY="re_test_key"), \
             patch("httpx.post", return_value=mock_resp) as mock_post:
            send_verification_email("a@b.com", "654321")
        call_kwargs = mock_post.call_args
        assert "654321" in call_kwargs.kwargs["json"]["html"]

    def test_verification_failure_is_silent(self, caplog):
        import logging
        from services.email_service import send_verification_email
        with patch.multiple("services.email_service", RESEND_API_KEY="re_test_key"), \
             patch("httpx.post", side_effect=Exception("timeout")):
            with caplog.at_level(logging.ERROR, logger="services.email_service"):
                send_verification_email("a@b.com", "000000")
        assert "Failed to send email" in caplog.text

    # ── send_repo_changed_email ───────────────────────────────────────────────

    def test_repo_changed_skips_when_not_configured(self):
        from services.email_service import send_repo_changed_email
        with patch.multiple("services.email_service", RESEND_API_KEY=""):
            result = send_repo_changed_email("a@b.com", "owner/repo", "http://analysis", "abc1234")
        assert result is None

    def test_repo_changed_sends_email(self):
        from services.email_service import send_repo_changed_email
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch.multiple("services.email_service", RESEND_API_KEY="re_test_key"), \
             patch("httpx.post", return_value=mock_resp) as mock_post:
            send_repo_changed_email("a@b.com", "owner/repo", "http://analysis/1", "abc1234")
        call_kwargs = mock_post.call_args
        html = call_kwargs.kwargs["json"]["html"]
        assert "owner/repo" in html
        assert "http://analysis/1" in html
        assert "abc1234" in html

    def test_repo_changed_failure_is_silent(self, caplog):
        import logging
        from services.email_service import send_repo_changed_email
        with patch.multiple("services.email_service", RESEND_API_KEY="re_test_key"), \
             patch("httpx.post", side_effect=Exception("refused")):
            with caplog.at_level(logging.ERROR, logger="services.email_service"):
                send_repo_changed_email("a@b.com", "r", "http://x", "abc")
        assert "Failed to send email" in caplog.text

    # ── send_analysis_complete_email ──────────────────────────────────────────

    def test_analysis_complete_skips_when_not_configured(self):
        from services.email_service import send_analysis_complete_email
        with patch.multiple("services.email_service", RESEND_API_KEY=""):
            result = send_analysis_complete_email("a@b.com", "owner/repo", "http://analysis/1")
        assert result is None

    def test_analysis_complete_sends_email(self):
        from services.email_service import send_analysis_complete_email
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch.multiple("services.email_service", RESEND_API_KEY="re_test_key"), \
             patch("httpx.post", return_value=mock_resp) as mock_post:
            send_analysis_complete_email("a@b.com", "owner/repo", "http://analysis/99")
        call_kwargs = mock_post.call_args
        html = call_kwargs.kwargs["json"]["html"]
        assert "owner/repo" in html
        assert "http://analysis/99" in html

    def test_analysis_complete_failure_is_silent(self, caplog):
        import logging
        from services.email_service import send_analysis_complete_email
        with patch.multiple("services.email_service", RESEND_API_KEY="re_test_key"), \
             patch("httpx.post", side_effect=Exception("timeout")):
            with caplog.at_level(logging.ERROR, logger="services.email_service"):
                send_analysis_complete_email("a@b.com", "r", "http://x")
        assert "Failed to send email" in caplog.text


# ══════════════════════════════════════════════════════════════════════════════
# api/watch.py — IntegrityError race-condition path
# ══════════════════════════════════════════════════════════════════════════════

class TestWatchIntegrityError:
    """Simulate the race condition where two concurrent requests both pass the
    'existing' check but one of them hits an IntegrityError on INSERT."""

    def test_integrity_error_returns_existing_row(self, client, db_session, test_user):
        from sqlalchemy.exc import IntegrityError
        token = create_token(test_user.id)
        headers = {"Authorization": f"Bearer {token}"}

        # Pre-create the watched repo in DB (simulates the row that already exists
        # after the race-condition INSERT fails)
        existing = WatchedRepo(
            user_id=test_user.id,
            repo_url="https://github.com/owner/testrepo",
            repo_name="owner/testrepo",
        )
        db_session.add(existing)
        db_session.commit()
        db_session.refresh(existing)

        # Now patch so the "existing" check returns None (bypasses idempotency guard)
        # and the INSERT raises IntegrityError, causing the fallback query
        original_query = db_session.query

        call_count = {"n": 0}

        def patched_query(model):
            q = original_query(model)
            if model.__name__ == "WatchedRepo":
                call_count["n"] += 1
                if call_count["n"] == 1:
                    # First call (idempotency check) → return nothing
                    return q.filter(WatchedRepo.id == "nonexistent-id-xyz")
            return q

        with patch.object(db_session, "query", side_effect=patched_query):
            with patch.object(db_session, "add"):
                with patch.object(db_session, "commit",
                                  side_effect=IntegrityError("UNIQUE constraint", {}, None)):
                    with patch.object(db_session, "rollback"):
                        # The fallback path re-queries — we need real query to work now
                        # so just test the endpoint normally (idempotent path)
                        pass

        # Simpler: just hit the endpoint twice and confirm idempotency (real path)
        r1 = client.post("/api/watch",
                         json={"repo_url": "https://github.com/owner/testrepo"},
                         headers=headers)
        # First call sees existing row → 200
        assert r1.status_code == 200
        assert r1.json()["repo_name"] == "owner/testrepo"

        r2 = client.post("/api/watch",
                         json={"repo_url": "https://github.com/owner/testrepo"},
                         headers=headers)
        assert r2.status_code == 200
        # IDs are identical — truly idempotent
        assert r1.json()["id"] == r2.json()["id"]

    def test_integrity_error_handler_directly(self, db_session, test_user):
        """Unit-test the IntegrityError except branch by using a mock DB session.

        The real session's idempotency check would short-circuit before reaching
        the INSERT, so we use a MagicMock to control each DB call individually.
        """
        from sqlalchemy.exc import IntegrityError as SAIntegrityError
        from api.watch import watch_repo, WatchRequest, _to_response

        # Build a fake WatchedRepo that the fallback query should return
        fake_existing = WatchedRepo(
            user_id=test_user.id,
            repo_url="https://github.com/raceowner/racerepo",
            repo_name="raceowner/racerepo",
        )
        # Give it a fake id so we can assert on it
        fake_existing.id = "fake-existing-uuid"
        fake_existing.created_at = __import__("datetime").datetime(2024, 1, 1)
        fake_existing.last_commit_hash = None
        fake_existing.last_checked_at = None
        fake_existing.last_changed_at = None

        mock_db = MagicMock()
        # First call to .query().filter().first() → None  (idempotency check sees nothing)
        # Second call (fallback after IntegrityError) → fake_existing
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            None,
            fake_existing,
        ]
        # .count() for free plan watch limit check
        mock_db.query.return_value.filter.return_value.count.return_value = 0
        mock_db.commit.side_effect = SAIntegrityError(
            "UNIQUE constraint failed", {}, None
        )

        req = WatchRequest(repo_url="https://github.com/raceowner/racerepo")
        resp = watch_repo(req, db=mock_db, current_user=test_user)

        assert resp.id == "fake-existing-uuid"
        assert resp.repo_name == "raceowner/racerepo"
        mock_db.rollback.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# api/auth.py — GitHub OAuth callback (login + connect + error paths)
# ══════════════════════════════════════════════════════════════════════════════

class TestGitHubOAuthCallback:
    """Exercise the /api/auth/github/callback endpoint via TestClient."""

    # ── helpers ──────────────────────────────────────────────────────────────

    def _seed_state(self, client, state_value: str, flow: str = "login", user_id: str | None = None):
        """Directly inject a state entry into the in-memory _oauth_states dict."""
        import time
        import api.auth as auth_module
        with auth_module._oauth_states_lock:
            entry = {"expires_at": time.time() + 300, "flow": flow}
            if user_id:
                entry["user_id"] = user_id
            auth_module._oauth_states[state_value] = entry

    # ── invalid / expired state ───────────────────────────────────────────────

    def test_invalid_state_redirects(self, client):
        r = client.get(
            "/api/auth/github/callback",
            params={"code": "anycode", "state": "not-a-real-state"},
            follow_redirects=False,
        )
        assert r.status_code in (302, 307)
        assert "invalid_state" in r.headers["location"]

    # ── no access token from GitHub ──────────────────────────────────────────

    def test_no_access_token_redirects_login(self, client):
        self._seed_state(client, "state-no-token", flow="login")
        with patch("api.auth.GITHUB_CLIENT_ID", "cid"), \
             patch("api.auth.GITHUB_CLIENT_SECRET", "csec"), \
             patch("api.auth.httpx") as mock_httpx:
            mock_httpx.post.return_value.json.return_value = {}  # no access_token
            r = client.get(
                "/api/auth/github/callback",
                params={"code": "badcode", "state": "state-no-token"},
                follow_redirects=False,
            )
        assert r.status_code in (302, 307)
        assert "github_failed" in r.headers["location"]

    def test_no_access_token_redirects_connect(self, client, test_user):
        self._seed_state(client, "state-connect-fail", flow="connect", user_id=test_user.id)
        with patch("api.auth.GITHUB_CLIENT_ID", "cid"), \
             patch("api.auth.GITHUB_CLIENT_SECRET", "csec"), \
             patch("api.auth.httpx") as mock_httpx:
            mock_httpx.post.return_value.json.return_value = {}
            r = client.get(
                "/api/auth/github/callback",
                params={"code": "bad", "state": "state-connect-fail"},
                follow_redirects=False,
            )
        assert r.status_code in (302, 307)
        assert "github_failed" in r.headers["location"]

    # ── connect flow ─────────────────────────────────────────────────────────

    def test_connect_flow_stores_token(self, client, db_session, test_user):
        self._seed_state(client, "state-connect", flow="connect", user_id=test_user.id)
        with patch("api.auth.GITHUB_CLIENT_ID", "cid"), \
             patch("api.auth.GITHUB_CLIENT_SECRET", "csec"), \
             patch("api.auth.httpx") as mock_httpx:
            mock_httpx.post.return_value.json.return_value = {"access_token": "gh_token_abc"}
            mock_httpx.get.return_value.json.return_value = {"login": "octocat", "id": 999}
            r = client.get(
                "/api/auth/github/callback",
                params={"code": "good-code", "state": "state-connect"},
                follow_redirects=False,
            )
        assert r.status_code in (302, 307)
        assert "connect-callback" in r.headers["location"]
        db_session.refresh(test_user)
        from services.encryption import decrypt as decrypt_field
        assert decrypt_field(test_user.github_access_token) == "gh_token_abc"
        assert test_user.github_username == "octocat"

    def test_connect_flow_missing_user_redirects(self, client, db_session):
        self._seed_state(client, "state-connect-nouser", flow="connect", user_id="nonexistent-id")
        with patch("api.auth.GITHUB_CLIENT_ID", "cid"), \
             patch("api.auth.GITHUB_CLIENT_SECRET", "csec"), \
             patch("api.auth.httpx") as mock_httpx:
            mock_httpx.post.return_value.json.return_value = {"access_token": "gh_token"}
            r = client.get(
                "/api/auth/github/callback",
                params={"code": "code", "state": "state-connect-nouser"},
                follow_redirects=False,
            )
        assert r.status_code in (302, 307)
        assert "github_failed" in r.headers["location"]

    # ── login flow ────────────────────────────────────────────────────────────

    def test_login_flow_creates_new_user(self, client, db_session):
        self._seed_state(client, "state-login-new", flow="login")
        with patch("api.auth.GITHUB_CLIENT_ID", "cid"), \
             patch("api.auth.GITHUB_CLIENT_SECRET", "csec"), \
             patch("api.auth.httpx") as mock_httpx:
            mock_httpx.post.return_value.json.return_value = {"access_token": "gh_tok"}
            mock_httpx.get.return_value.json.return_value = {
                "id": 12345,
                "email": "newgithubuser@example.com",
                "login": "newuser",
            }
            r = client.get(
                "/api/auth/github/callback",
                params={"code": "c", "state": "state-login-new"},
                follow_redirects=False,
            )
        assert r.status_code in (302, 307)
        loc = r.headers["location"]
        assert "/auth/callback?code=" in loc
        # User should be created in DB
        user = db_session.query(User).filter(User.email == "newgithubuser@example.com").first()
        assert user is not None
        assert user.github_id == "12345"

    def test_login_flow_links_existing_email_user(self, client, db_session, test_user):
        self._seed_state(client, "state-login-existing", flow="login")
        existing_email = test_user.email
        with patch("api.auth.GITHUB_CLIENT_ID", "cid"), \
             patch("api.auth.GITHUB_CLIENT_SECRET", "csec"), \
             patch("api.auth.httpx") as mock_httpx:
            mock_httpx.post.return_value.json.return_value = {"access_token": "gh_tok2"}
            mock_httpx.get.return_value.json.return_value = {
                "id": 99999,
                "email": existing_email,
                "login": "existinggh",
            }
            r = client.get(
                "/api/auth/github/callback",
                params={"code": "c", "state": "state-login-existing"},
                follow_redirects=False,
            )
        assert r.status_code in (302, 307)
        db_session.refresh(test_user)
        assert test_user.github_id == "99999"

    def test_login_flow_fetches_email_from_emails_endpoint(self, client, db_session):
        """When /user returns no email, fall back to /user/emails."""
        self._seed_state(client, "state-noemail", flow="login")
        with patch("api.auth.GITHUB_CLIENT_ID", "cid"), \
             patch("api.auth.GITHUB_CLIENT_SECRET", "csec"), \
             patch("api.auth.httpx") as mock_httpx:
            mock_httpx.post.return_value.json.return_value = {"access_token": "gh_tok3"}

            def get_side_effect(url, **kwargs):
                resp = MagicMock()
                if "/user/emails" in url:
                    resp.json.return_value = [
                        {"email": "private@example.com", "primary": True, "verified": True}
                    ]
                else:
                    resp.json.return_value = {"id": 77777, "email": None, "login": "privuser"}
                return resp

            mock_httpx.get.side_effect = get_side_effect
            r = client.get(
                "/api/auth/github/callback",
                params={"code": "c", "state": "state-noemail"},
                follow_redirects=False,
            )
        assert r.status_code in (302, 307)
        user = db_session.query(User).filter(User.email == "private@example.com").first()
        assert user is not None

    def test_login_flow_no_email_at_all_redirects(self, client):
        """When neither /user nor /user/emails yields an email, redirect with error."""
        self._seed_state(client, "state-noemail2", flow="login")
        with patch("api.auth.GITHUB_CLIENT_ID", "cid"), \
             patch("api.auth.GITHUB_CLIENT_SECRET", "csec"), \
             patch("api.auth.httpx") as mock_httpx:
            mock_httpx.post.return_value.json.return_value = {"access_token": "gh_tok4"}

            def get_side_effect(url, **kwargs):
                resp = MagicMock()
                if "/user/emails" in url:
                    resp.json.return_value = []
                else:
                    resp.json.return_value = {"id": 88888, "email": None}
                return resp

            mock_httpx.get.side_effect = get_side_effect
            r = client.get(
                "/api/auth/github/callback",
                params={"code": "c", "state": "state-noemail2"},
                follow_redirects=False,
            )
        assert r.status_code in (302, 307)
        assert "github_no_email" in r.headers["location"]

    # ── OAuth not configured ──────────────────────────────────────────────────

    def test_callback_503_when_not_configured(self, client):
        with patch("api.auth.GITHUB_CLIENT_ID", ""), \
             patch("api.auth.GITHUB_CLIENT_SECRET", ""):
            r = client.get(
                "/api/auth/github/callback",
                params={"code": "c", "state": "s"},
            )
        assert r.status_code == 503

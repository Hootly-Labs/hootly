"""Tests for MCP server tool implementations and auth."""
import json

import pytest
from unittest.mock import patch, MagicMock

from models import Analysis, User
from services.auth_service import hash_password


def _session_factory(session):
    """Return a callable that mimics SessionLocal()."""
    def factory():
        return session
    return factory


# ── Auth checks ──────────────────────────────────────────────────────────


class TestCheckAuth:
    def test_no_key_configured_returns_none(self):
        """When HOOTLY_API_KEY is empty, auth is skipped (local use)."""
        with patch("mcp_server.HOOTLY_API_KEY", ""):
            from mcp_server import _check_auth
            assert _check_auth() is None

    def test_valid_key_returns_user_id(self, db_session):
        """Valid API key should return the associated user ID."""
        from services.auth_service import generate_api_key

        user = User(
            email="mcp@example.com",
            password_hash=hash_password("Test@Pass123"),
            plan="pro",
            is_verified=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        raw_key, api_key = generate_api_key(user.id, "test-key", db_session)

        with patch("mcp_server.HOOTLY_API_KEY", raw_key), \
             patch("database.SessionLocal", _session_factory(db_session)):
            from mcp_server import _check_auth
            result = _check_auth()
            assert result == user.id

    def test_invalid_key_raises_value_error(self, db_session):
        """Invalid API key should raise ValueError."""
        with patch("mcp_server.HOOTLY_API_KEY", "hk_invalidkey123"), \
             patch("database.SessionLocal", _session_factory(db_session)):
            from mcp_server import _check_auth
            with pytest.raises(ValueError, match="Invalid HOOTLY_API_KEY"):
                _check_auth()


# ── Tool: analyze_repo ───────────────────────────────────────────────────


class TestToolAnalyzeRepo:
    @patch("mcp_server._check_auth", return_value=None)
    @patch("threading.Thread")
    def test_analyze_repo_creates_analysis(self, mock_thread, mock_auth, db_session):
        mock_thread.return_value = MagicMock()

        with patch("database.SessionLocal", _session_factory(db_session)):
            from mcp_server import _tool_analyze_repo
            result = _tool_analyze_repo("https://github.com/owner/repo")

        assert "analysis_id" in result
        assert result["status"] == "pending"
        assert "owner/repo" in result["message"]

    @patch("mcp_server._check_auth", side_effect=ValueError("Invalid HOOTLY_API_KEY"))
    def test_analyze_repo_auth_failure(self, mock_auth):
        from mcp_server import _tool_analyze_repo
        result = _tool_analyze_repo("https://github.com/owner/repo")
        assert "error" in result
        assert "Invalid" in result["error"]

    @patch("mcp_server._check_auth", return_value="user-123")
    @patch("threading.Thread")
    def test_analyze_repo_sets_user_id(self, mock_thread, mock_auth, db_session):
        mock_thread.return_value = MagicMock()

        with patch("database.SessionLocal", _session_factory(db_session)):
            from mcp_server import _tool_analyze_repo
            result = _tool_analyze_repo("https://github.com/owner/repo")

        analysis = db_session.query(Analysis).filter(
            Analysis.id == result["analysis_id"]
        ).first()
        assert analysis.user_id == "user-123"

    @patch("mcp_server._check_auth", return_value=None)
    def test_analyze_repo_invalid_url(self, mock_auth, db_session):
        with patch("database.SessionLocal", _session_factory(db_session)):
            from mcp_server import _tool_analyze_repo
            result = _tool_analyze_repo("https://notgithub.com/foo/bar")
        assert "error" in result


# ── Tool: get_analysis ───────────────────────────────────────────────────


class TestToolGetAnalysis:
    @patch("mcp_server._check_auth", return_value=None)
    def test_get_analysis_not_found(self, mock_auth, db_session):
        with patch("database.SessionLocal", _session_factory(db_session)):
            from mcp_server import _tool_get_analysis
            result = _tool_get_analysis("nonexistent-id")
        assert "error" in result
        assert "not found" in result["error"]

    @patch("mcp_server._check_auth", return_value=None)
    def test_get_analysis_pending(self, mock_auth, db_session):
        analysis = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="pending",
            stage="Queued",
        )
        db_session.add(analysis)
        db_session.commit()
        db_session.refresh(analysis)

        with patch("database.SessionLocal", _session_factory(db_session)):
            from mcp_server import _tool_get_analysis
            result = _tool_get_analysis(analysis.id)

        assert result["status"] == "pending"
        assert result["repo_name"] == "owner/repo"

    @patch("mcp_server._check_auth", return_value=None)
    def test_get_analysis_completed_includes_result(self, mock_auth, db_session):
        analysis = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            result=json.dumps({
                "architecture": {
                    "architecture_type": "Monolith",
                    "architecture_summary": "A web app",
                    "tech_stack": ["Python"],
                },
                "key_files": [
                    {"path": "main.py", "score": 10, "reason": "Entry point"},
                ],
                "quick_start": "Run main.py",
            }),
            health_score=json.dumps({"overall_score": 85, "grade": "B"}),
        )
        db_session.add(analysis)
        db_session.commit()
        db_session.refresh(analysis)

        with patch("database.SessionLocal", _session_factory(db_session)):
            from mcp_server import _tool_get_analysis
            result = _tool_get_analysis(analysis.id)

        assert result["status"] == "completed"
        assert result["architecture"]["type"] == "Monolith"
        assert len(result["key_files"]) == 1
        assert result["quick_start"] == "Run main.py"
        assert result["health_score"]["grade"] == "B"

    @patch("mcp_server._check_auth", side_effect=ValueError("Invalid HOOTLY_API_KEY"))
    def test_get_analysis_auth_failure(self, mock_auth):
        from mcp_server import _tool_get_analysis
        result = _tool_get_analysis("some-id")
        assert "error" in result


# ── Tool: get_health_score ───────────────────────────────────────────────


class TestToolGetHealthScore:
    @patch("mcp_server._check_auth", return_value=None)
    def test_health_score_not_found(self, mock_auth, db_session):
        with patch("database.SessionLocal", _session_factory(db_session)):
            from mcp_server import _tool_get_health_score
            result = _tool_get_health_score("https://github.com/unknown/repo")
        assert "error" in result

    @patch("mcp_server._check_auth", return_value=None)
    def test_health_score_returns_data(self, mock_auth, db_session):
        analysis = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            health_score=json.dumps({
                "overall_score": 92,
                "grade": "A",
                "dimensions": {"modularity": {"score": 90, "label": "Modularity"}},
            }),
        )
        db_session.add(analysis)
        db_session.commit()

        with patch("database.SessionLocal", _session_factory(db_session)):
            from mcp_server import _tool_get_health_score
            result = _tool_get_health_score("https://github.com/owner/repo")

        assert result["grade"] == "A"
        assert result["overall_score"] == 92

    @patch("mcp_server._check_auth", side_effect=ValueError("Invalid HOOTLY_API_KEY"))
    def test_health_score_auth_failure(self, mock_auth):
        from mcp_server import _tool_get_health_score
        result = _tool_get_health_score("https://github.com/owner/repo")
        assert "error" in result


# ── Tool: query_analysis ─────────────────────────────────────────────────


class TestToolQueryAnalysis:
    @patch("mcp_server._check_auth", return_value=None)
    def test_query_not_completed_returns_error(self, mock_auth, db_session):
        analysis = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="pending",
        )
        db_session.add(analysis)
        db_session.commit()
        db_session.refresh(analysis)

        with patch("database.SessionLocal", _session_factory(db_session)):
            from mcp_server import _tool_query_analysis
            result = _tool_query_analysis(analysis.id, "How does auth work?")

        assert "error" in result

    @patch("mcp_server._check_auth", side_effect=ValueError("Invalid HOOTLY_API_KEY"))
    def test_query_auth_failure(self, mock_auth):
        from mcp_server import _tool_query_analysis
        result = _tool_query_analysis("some-id", "question")
        assert "error" in result


# ── Protocol: handle_request ─────────────────────────────────────────────


class TestHandleRequest:
    @patch("mcp_server._send_result")
    def test_initialize_returns_capabilities(self, mock_send):
        from mcp_server import handle_request
        handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        mock_send.assert_called_once()
        result = mock_send.call_args[0][1]
        assert result["protocolVersion"] == "2024-11-05"
        assert "tools" in result["capabilities"]
        assert result["serverInfo"]["name"] == "hootly"

    @patch("mcp_server._send_result")
    def test_tools_list_returns_all_tools(self, mock_send):
        from mcp_server import handle_request
        handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        mock_send.assert_called_once()
        tools = mock_send.call_args[0][1]["tools"]
        names = [t["name"] for t in tools]
        assert "analyze_repo" in names
        assert "get_analysis" in names
        assert "query_analysis" in names
        assert "get_health_score" in names

    @patch("mcp_server._send_error")
    def test_unknown_method_returns_error(self, mock_error):
        from mcp_server import handle_request
        handle_request({"jsonrpc": "2.0", "id": 3, "method": "foo/bar", "params": {}})
        mock_error.assert_called_once()
        assert mock_error.call_args[0][1] == -32601

    @patch("mcp_server._send_error")
    def test_unknown_tool_returns_error(self, mock_error):
        from mcp_server import handle_request
        handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        })
        mock_error.assert_called_once()
        assert "Unknown tool" in mock_error.call_args[0][2]


# ── Tool descriptions ────────────────────────────────────────────────────


class TestToolDescriptions:
    def test_all_tools_mention_auth(self):
        from mcp_server import TOOLS
        for tool in TOOLS:
            assert "HOOTLY_API_KEY" in tool["description"], \
                f"Tool '{tool['name']}' description missing HOOTLY_API_KEY mention"

    def test_all_tools_have_input_schema(self):
        from mcp_server import TOOLS
        for tool in TOOLS:
            assert "inputSchema" in tool
            assert "properties" in tool["inputSchema"]
            assert "required" in tool["inputSchema"]

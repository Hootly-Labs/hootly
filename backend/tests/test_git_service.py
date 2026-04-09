"""Tests for git_service: URL parsing, clone, commit hash."""
import pytest
from unittest.mock import MagicMock, patch

from services.git_service import clone_repo, get_commit_hash, parse_github_url


class TestParseGithubUrl:
    # ── Valid URLs ─────────────────────────────────────────────────────────────

    def test_standard_https(self):
        owner, repo = parse_github_url("https://github.com/fastapi/fastapi")
        assert owner == "fastapi" and repo == "fastapi"

    def test_git_suffix_stripped(self):
        owner, repo = parse_github_url("https://github.com/fastapi/fastapi.git")
        assert owner == "fastapi" and repo == "fastapi"

    def test_trailing_slash_stripped(self):
        owner, repo = parse_github_url("https://github.com/fastapi/fastapi/")
        assert owner == "fastapi" and repo == "fastapi"

    def test_bare_github_com(self):
        owner, repo = parse_github_url("github.com/fastapi/fastapi")
        assert owner == "fastapi" and repo == "fastapi"

    def test_http_prefix(self):
        """http:// (not https) should be accepted — common copy-paste."""
        owner, repo = parse_github_url("http://github.com/fastapi/fastapi")
        assert owner == "fastapi" and repo == "fastapi"

    def test_www_prefix(self):
        """www.github.com should be accepted."""
        owner, repo = parse_github_url("https://www.github.com/fastapi/fastapi")
        assert owner == "fastapi" and repo == "fastapi"

    def test_tree_url(self):
        """Users frequently copy tree URLs from GitHub."""
        owner, repo = parse_github_url("https://github.com/fastapi/fastapi/tree/main")
        assert owner == "fastapi" and repo == "fastapi"

    def test_blob_url(self):
        owner, repo = parse_github_url("https://github.com/fastapi/fastapi/blob/main/README.md")
        assert owner == "fastapi" and repo == "fastapi"

    def test_issues_url(self):
        owner, repo = parse_github_url("https://github.com/fastapi/fastapi/issues")
        assert owner == "fastapi" and repo == "fastapi"

    def test_releases_url(self):
        owner, repo = parse_github_url("https://github.com/fastapi/fastapi/releases")
        assert owner == "fastapi" and repo == "fastapi"

    def test_query_string_stripped(self):
        owner, repo = parse_github_url("https://github.com/fastapi/fastapi?tab=readme-ov-file")
        assert owner == "fastapi" and repo == "fastapi"

    def test_fragment_stripped(self):
        owner, repo = parse_github_url("https://github.com/fastapi/fastapi#readme")
        assert owner == "fastapi" and repo == "fastapi"

    def test_repo_with_dots(self):
        owner, repo = parse_github_url("https://github.com/owner/my.project")
        assert owner == "owner" and repo == "my.project"

    def test_repo_with_underscores(self):
        owner, repo = parse_github_url("https://github.com/owner/my_repo")
        assert owner == "owner" and repo == "my_repo"

    def test_repo_with_hyphens(self):
        owner, repo = parse_github_url("https://github.com/my-org/my-repo")
        assert owner == "my-org" and repo == "my-repo"

    def test_single_char_names(self):
        owner, repo = parse_github_url("https://github.com/a/b")
        assert owner == "a" and repo == "b"

    def test_numeric_owner(self):
        owner, repo = parse_github_url("https://github.com/user123/repo456")
        assert owner == "user123" and repo == "repo456"

    def test_case_insensitive_scheme(self):
        owner, repo = parse_github_url("HTTPS://GITHUB.COM/owner/repo")
        assert owner == "owner" and repo == "repo"

    # ── Invalid URLs ───────────────────────────────────────────────────────────

    def test_non_github_domain(self):
        with pytest.raises(ValueError, match="Invalid GitHub URL"):
            parse_github_url("https://gitlab.com/owner/repo")

    def test_bitbucket_rejected(self):
        with pytest.raises(ValueError):
            parse_github_url("https://bitbucket.org/owner/repo")

    def test_missing_repo(self):
        with pytest.raises(ValueError):
            parse_github_url("https://github.com/owner")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse_github_url("")

    def test_only_whitespace(self):
        with pytest.raises(ValueError):
            parse_github_url("   ")

    def test_owner_starts_with_hyphen(self):
        with pytest.raises(ValueError, match="Invalid GitHub owner"):
            parse_github_url("https://github.com/-owner/repo")

    def test_owner_ends_with_hyphen(self):
        with pytest.raises(ValueError, match="Invalid GitHub owner"):
            parse_github_url("https://github.com/owner-/repo")

    def test_owner_with_spaces(self):
        with pytest.raises(ValueError):
            parse_github_url("https://github.com/my owner/repo")

    def test_xss_in_owner(self):
        with pytest.raises(ValueError):
            parse_github_url("https://github.com/<script>alert(1)</script>/repo")

    def test_path_traversal(self):
        with pytest.raises(ValueError):
            parse_github_url("https://github.com/../../../etc/passwd/x")

    def test_not_a_url(self):
        with pytest.raises(ValueError):
            parse_github_url("just some random text")

    def test_ftp_scheme_rejected(self):
        with pytest.raises(ValueError):
            parse_github_url("ftp://github.com/owner/repo")

    def test_owner_too_long(self):
        long_owner = "a" * 40  # GitHub max is 39
        with pytest.raises(ValueError):
            parse_github_url(f"https://github.com/{long_owner}/repo")


class TestGetCommitHash:
    def test_returns_sha_on_success(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="abc1234567890\n")
            result = get_commit_hash("/fake/dir")
        assert result == "abc1234567890"

    def test_strips_whitespace(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="  sha123  \n")
            result = get_commit_hash("/fake/dir")
        assert result == "sha123"

    def test_returns_empty_on_nonzero_exit(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="")
            result = get_commit_hash("/fake/dir")
        assert result == ""

    def test_returns_empty_on_exception(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            result = get_commit_hash("/fake/dir")
        assert result == ""

    def test_returns_empty_on_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            result = get_commit_hash("/fake/dir")
        assert result == ""


class TestCloneRepo:
    def test_success_returns_dest(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            result = clone_repo("https://github.com/owner/repo", "/tmp/dest")
        assert result == "/tmp/dest"

    def test_uses_shallow_clone(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            clone_repo("https://github.com/owner/repo", "/tmp/dest")
        args = mock_run.call_args[0][0]
        assert "--depth" in args and "1" in args

    def test_appends_git_suffix(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            clone_repo("https://github.com/owner/repo", "/tmp/dest")
        args = mock_run.call_args[0][0]
        clone_url = next(a for a in args if "github.com" in a)
        assert clone_url.endswith(".git")

    def test_raises_on_failure(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128, stderr="fatal: repository not found", stdout=""
            )
            with pytest.raises(RuntimeError, match="git clone failed"):
                clone_repo("https://github.com/owner/repo", "/tmp/dest")

    def test_token_embedded_in_url(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            clone_repo("https://github.com/owner/repo", "/tmp/dest", github_token="my-token")
        args = mock_run.call_args[0][0]
        clone_url = next(a for a in args if "github.com" in a)
        assert "my-token" in clone_url

    def test_token_not_leaked_in_error_message(self):
        """When a github_token is used and clone fails, no subprocess output is returned."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128,
                stderr="error: my-secret-token in auth",
                stdout="",
            )
            with pytest.raises(RuntimeError) as exc_info:
                clone_repo(
                    "https://github.com/owner/repo",
                    "/tmp/dest",
                    github_token="my-secret-token",
                )
        assert "my-secret-token" not in str(exc_info.value)
        assert "my-secret-token" not in repr(exc_info.value)

    def test_adds_https_if_missing(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            clone_repo("github.com/owner/repo", "/tmp/dest")
        args = mock_run.call_args[0][0]
        clone_url = next(a for a in args if "github.com" in a)
        assert clone_url.startswith("https://")

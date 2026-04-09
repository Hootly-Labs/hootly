import ipaddress
import logging
import os
import re
import shutil
import socket
import tempfile
import subprocess
from pathlib import Path
from urllib.parse import urlparse

_logger = logging.getLogger(__name__)

# GitHub naming rules:
# Owner: 1–39 chars, alphanumeric + hyphens, cannot start/end with hyphen
# Repo:  1–100 chars, alphanumeric + hyphens, underscores, dots
_GITHUB_OWNER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,37}[a-zA-Z0-9]$|^[a-zA-Z0-9]$")
_GITHUB_REPO_RE  = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$|^[a-zA-Z0-9]$")


def parse_github_url(url: str) -> tuple[str, str]:
    """
    Return (owner, repo) from a GitHub URL.
    Accepts https:// and http://, optional www., and common sub-page paths
    (/tree/main, /blob/main/file, /issues, etc.) that users copy from GitHub.
    Raises ValueError with a descriptive message if invalid.
    """
    url = url.strip().rstrip("/")

    # Strip query string and fragment — they're not part of the repo path
    url = url.split("?")[0].split("#")[0]

    # Strip common GitHub sub-page paths users copy from the browser bar
    url = re.sub(
        r"/(tree|blob|commit|commits|releases|issues|pulls|actions|wiki|"
        r"security|pulse|graphs|network|compare|settings|branches|tags|raw)"
        r"(/.*)?$",
        "",
        url,
        flags=re.IGNORECASE,
    )

    # Accept https:// or http://, optional www., bare github.com/...
    m = re.match(
        r"^(?:https?://)?(?:www\.)?github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?$",
        url,
        re.IGNORECASE,
    )
    if not m:
        raise ValueError(
            "Invalid GitHub URL. Expected format: https://github.com/owner/repo"
        )

    owner, repo = m.group(1), m.group(2)

    if not _GITHUB_OWNER_RE.match(owner):
        raise ValueError(
            f"Invalid GitHub owner name '{owner}'. "
            "Owner names may only contain alphanumeric characters and hyphens."
        )
    if not _GITHUB_REPO_RE.match(repo):
        raise ValueError(
            f"Invalid GitHub repository name '{repo}'. "
            "Repo names may only contain alphanumeric characters, hyphens, underscores, and dots."
        )

    return owner, repo


def _is_private_ip(hostname: str) -> bool:
    """Return True if hostname resolves to a private/reserved IP (SSRF protection)."""
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False  # Can't resolve — let git fail naturally
    for family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        ):
            return True
    return False


def clone_repo(repo_url: str, dest_dir: str, github_token: str | None = None) -> str:
    """Clone a GitHub repo into dest_dir. Returns the cloned path.

    If github_token is provided it is embedded in the clone URL so private
    repos are accessible. The token is scrubbed from any error messages before
    they are surfaced to callers.
    """
    # Normalise URL
    url = repo_url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    if not url.endswith(".git"):
        url = url + ".git"

    # SSRF protection: block cloning from private/internal IPs
    parsed = urlparse(url)
    if parsed.hostname and _is_private_ip(parsed.hostname):
        raise RuntimeError(
            "Cannot clone from private or internal network addresses."
        )

    clone_url = url
    if github_token:
        clone_url = url.replace("https://", f"https://x-access-token:{github_token}@", 1)

    try:
        result = subprocess.run(
            [
                "git", "clone", "--depth", "1", "--single-branch",
                "--config", "core.symlinks=false",
                "--config", "core.fsmonitor=false",
                "--config", "protocol.file.allow=never",
                "--config", "protocol.ext.allow=never",
                clone_url, dest_dir,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "git is not installed or not on PATH. "
            "Please install git and try again."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "git clone timed out after 120 seconds. "
            "The repository may be too large or the network is slow."
        )

    if result.returncode != 0:
        if github_token:
            # Never surface subprocess output when a token was embedded in the clone
            # URL — git error messages may contain the full authenticated URL.
            raise RuntimeError(
                "Could not clone the repository. "
                "Check that your GitHub token has the required 'repo' scope and "
                "that the repository exists."
            )
        err_msg = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git clone failed: {err_msg}")
    return dest_dir


def get_commit_hash(repo_dir: str) -> str:
    """Return the HEAD commit hash of a cloned repo, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def make_temp_dir(analysis_id: str) -> str:
    base = os.getenv("CLONE_BASE_DIR", tempfile.gettempdir())
    path = os.path.join(base, "hootly", analysis_id)
    os.makedirs(path, exist_ok=True)
    return path


def cleanup_temp_dir(path: str):
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass

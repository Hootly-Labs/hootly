"""GitHub App webhook handler — installation events, push triggers, PR comments."""
import hashlib
import hmac
import json
import logging
import os
import time

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from database import SessionLocal
from models import Analysis, GitHubInstallation, _utcnow

logger = logging.getLogger(__name__)

router = APIRouter()

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID", "")
GITHUB_APP_PRIVATE_KEY = os.getenv("GITHUB_APP_PRIVATE_KEY", "")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

# Minimum file changes in a push to trigger re-analysis
_MIN_CHANGED_FILES = 5


def _verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature (SHA-256)."""
    if not GITHUB_WEBHOOK_SECRET:
        return False  # no secret configured = reject requests
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _generate_jwt() -> str:
    """Generate a JWT for GitHub App authentication."""
    if not GITHUB_APP_ID or not GITHUB_APP_PRIVATE_KEY:
        raise RuntimeError("GitHub App not configured (missing GITHUB_APP_ID or GITHUB_APP_PRIVATE_KEY)")
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": GITHUB_APP_ID,
    }
    # Handle PEM key — may be stored with escaped newlines in env var
    private_key = GITHUB_APP_PRIVATE_KEY.replace("\\n", "\n")
    return jwt.encode(payload, private_key, algorithm="RS256")


def _get_installation_token(installation_id: int) -> str:
    """Exchange App JWT for an installation access token."""
    app_jwt = _generate_jwt()
    resp = httpx.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["token"]


@router.post("/github-app/webhook")
async def github_app_webhook(request: Request):
    """Handle GitHub App webhook events."""
    body = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")

    if not _verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = request.headers.get("x-github-event", "")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if event == "installation":
        return _handle_installation(payload)
    elif event == "push":
        return _handle_push(payload)
    elif event == "pull_request":
        return _handle_pull_request(payload)

    return {"status": "ignored", "event": event}


def _handle_installation(payload: dict):
    """Handle installation.created and installation.deleted events."""
    action = payload.get("action")
    installation = payload.get("installation", {})
    installation_id = installation.get("id")
    account = installation.get("account", {})

    db = SessionLocal()
    try:
        if action == "created":
            # Store installation
            existing = db.query(GitHubInstallation).filter(
                GitHubInstallation.installation_id == installation_id
            ).first()
            if not existing:
                gi = GitHubInstallation(
                    installation_id=installation_id,
                    account_login=account.get("login", ""),
                    account_type=account.get("type", "User"),
                )
                db.add(gi)
                db.commit()
            logger.info("GitHub App installed: %s (%s)", account.get("login"), installation_id)

            # Queue analyses for selected repos
            repos = payload.get("repositories", [])
            for repo in repos[:10]:  # limit to 10 repos on install
                repo_url = f"https://github.com/{repo['full_name']}"
                analysis = Analysis(
                    repo_url=repo_url,
                    repo_name=repo["full_name"],
                    status="pending",
                    stage="Queued (GitHub App)",
                )
                db.add(analysis)
            db.commit()

            # Trigger analyses in background
            for repo in repos[:10]:
                _trigger_background_analysis(repo["full_name"])

            return {"status": "installed", "repos_queued": len(repos[:10])}

        elif action == "deleted":
            db.query(GitHubInstallation).filter(
                GitHubInstallation.installation_id == installation_id
            ).delete()
            db.commit()
            logger.info("GitHub App uninstalled: %s", account.get("login"))
            return {"status": "uninstalled"}

    finally:
        db.close()

    return {"status": "ok"}


def _handle_push(payload: dict):
    """Handle push events — re-analyze if significant structural changes."""
    ref = payload.get("ref", "")
    repo = payload.get("repository", {})
    default_branch = repo.get("default_branch", "main")

    # Only trigger on pushes to the default branch
    if ref != f"refs/heads/{default_branch}":
        return {"status": "ignored", "reason": "not default branch"}

    # Count changed files across all commits in this push
    changed_files = set()
    for commit in payload.get("commits", []):
        changed_files.update(commit.get("added", []))
        changed_files.update(commit.get("modified", []))
        changed_files.update(commit.get("removed", []))

    if len(changed_files) < _MIN_CHANGED_FILES:
        return {"status": "ignored", "reason": f"only {len(changed_files)} files changed"}

    repo_name = repo.get("full_name", "")
    logger.info("GitHub App push trigger: %s (%d files changed)", repo_name, len(changed_files))
    _trigger_background_analysis(repo_name)

    return {"status": "analysis_triggered", "repo": repo_name, "files_changed": len(changed_files)}


def _handle_pull_request(payload: dict):
    """Handle PR opened by new contributor — auto-comment with architecture context."""
    action = payload.get("action")
    if action != "opened":
        return {"status": "ignored", "reason": "not opened"}

    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})
    repo_name = repo.get("full_name", "")
    installation = payload.get("installation", {})
    installation_id = installation.get("id")

    if not installation_id:
        return {"status": "ignored", "reason": "no installation"}

    # Check if there's a completed analysis for this repo
    db = SessionLocal()
    try:
        repo_url = f"https://github.com/{repo_name}"
        analysis = (
            db.query(Analysis)
            .filter(Analysis.repo_url == repo_url, Analysis.status == "completed")
            .order_by(Analysis.created_at.desc())
            .first()
        )

        if not analysis or not analysis.result:
            return {"status": "ignored", "reason": "no analysis available"}

        try:
            result = json.loads(analysis.result)
        except Exception:
            return {"status": "ignored", "reason": "invalid analysis result"}

        # Build a brief architecture comment
        arch = result.get("architecture", {})
        patterns = result.get("patterns", [])
        key_files = result.get("key_files", [])[:5]

        comment_body = f"""### Architecture Context (by Hootly)

**{arch.get('architecture_type', 'Project')}** — {arch.get('description', '')}

**Stack:** {', '.join(arch.get('tech_stack', [])[:6])}

**Key files to review:**
"""
        for f in key_files:
            comment_body += f"- `{f['path']}` — {f.get('reason', '')}\n"

        if patterns:
            comment_body += "\n**Architecture patterns:**\n"
            for p in patterns[:3]:
                comment_body += f"- **{p['name']}**: {p.get('explanation', '')[:100]}\n"

        comment_body += f"\n[View full analysis on Hootly]({os.getenv('APP_URL', 'https://www.hootlylabs.com')}/analysis/{analysis.id})"

        # Post comment using installation token
        try:
            token = _get_installation_token(installation_id)
            httpx.post(
                f"https://api.github.com/repos/{repo_name}/issues/{pr['number']}/comments",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"body": comment_body},
                timeout=10,
            )
            logger.info("Posted architecture context on PR #%s in %s", pr["number"], repo_name)
        except Exception as exc:
            logger.warning("Failed to post PR comment: %s", exc)

    finally:
        db.close()

    return {"status": "commented"}


def _trigger_background_analysis(repo_name: str):
    """Queue a background analysis for a repo. Fire-and-forget."""
    from api.routes import _do_analysis

    db = SessionLocal()
    try:
        repo_url = f"https://github.com/{repo_name}"
        analysis = Analysis(
            repo_url=repo_url,
            repo_name=repo_name,
            status="pending",
            stage="Queued (GitHub App)",
        )
        db.add(analysis)
        db.commit()

        import threading
        t = threading.Thread(target=_do_analysis, args=(analysis.id,), daemon=True)
        t.start()
    except Exception as exc:
        logger.warning("Failed to queue analysis for %s: %s", repo_name, exc)
    finally:
        db.close()

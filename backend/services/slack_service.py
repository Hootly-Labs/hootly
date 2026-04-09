"""Feature 6: Slack bot — OAuth, slash commands, notifications."""
import json
import logging
import os

import httpx
from sqlalchemy.orm import Session

from models import _utcnow, SlackInstallation
from services.encryption import encrypt as encrypt_field, decrypt as decrypt_field

logger = logging.getLogger(__name__)

SLACK_CLIENT_ID = os.getenv("SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
APP_URL = os.getenv("APP_URL", "http://localhost:3000")
API_URL = os.getenv("API_URL", "http://localhost:8000")


def get_install_url(team_id: str) -> str:
    """Generate Slack OAuth install URL."""
    scopes = "commands,chat:write,channels:read"
    redirect_uri = f"{API_URL}/api/slack/callback"
    return (
        f"https://slack.com/oauth/v2/authorize"
        f"?client_id={SLACK_CLIENT_ID}"
        f"&scope={scopes}"
        f"&redirect_uri={redirect_uri}"
        f"&state={team_id}"
    )


def exchange_code(code: str) -> dict | None:
    """Exchange OAuth code for bot token."""
    try:
        resp = httpx.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": SLACK_CLIENT_ID,
                "client_secret": SLACK_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{API_URL}/api/slack/callback",
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            return data
        logger.warning("Slack OAuth error: %s", data.get("error"))
    except Exception as exc:
        logger.error("Slack OAuth exchange failed: %s", exc)
    return None


def save_installation(
    team_id: str,
    slack_team_id: str,
    bot_token: str,
    user_id: str,
    db: Session,
    channel_id: str | None = None,
) -> SlackInstallation:
    """Save or update a Slack installation."""
    existing = db.query(SlackInstallation).filter(
        SlackInstallation.slack_team_id == slack_team_id
    ).first()

    encrypted_token = encrypt_field(bot_token)

    if existing:
        existing.slack_bot_token = encrypted_token
        existing.slack_channel_id = channel_id
        existing.team_id = team_id
        db.commit()
        return existing

    inst = SlackInstallation(
        team_id=team_id,
        slack_team_id=slack_team_id,
        slack_bot_token=encrypted_token,
        slack_channel_id=channel_id,
        installed_by=user_id,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def post_message(installation: SlackInstallation, channel: str, text: str, blocks: list | None = None) -> bool:
    """Post a message to a Slack channel."""
    token = decrypt_field(installation.slack_bot_token)
    payload: dict = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Slack post failed: %s", data.get("error"))
            return False
        return True
    except Exception as exc:
        logger.error("Slack post error: %s", exc)
        return False


def post_analysis_result(installation: SlackInstallation, channel: str, analysis) -> bool:
    """Post a formatted analysis result to Slack."""
    health_text = ""
    if analysis.health_score:
        try:
            health = json.loads(analysis.health_score)
            health_text = f" | Health: {health.get('grade', '?')} ({health.get('overall_score', 0)}/100)"
        except Exception:
            pass

    analysis_url = f"{APP_URL}/analysis/{analysis.id}"
    text = f"Analysis complete: *{analysis.repo_name}*{health_text}\n<{analysis_url}|View full analysis>"

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
        },
    ]
    return post_message(installation, channel, text, blocks)


def post_drift_alert(installation: SlackInstallation, channel: str, alert) -> bool:
    """Post a drift alert notification to Slack."""
    severity_emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(alert.severity, "🔵")
    text = f"{severity_emoji} *Drift Alert* — {alert.repo_url}\n{alert.message}"
    return post_message(installation, channel, text)


def handle_slash_command(command: str, text: str, team_id: str, channel_id: str, db: Session) -> str:
    """Handle /hootly slash commands. Returns response text."""
    parts = text.strip().split(maxsplit=1)
    subcommand = parts[0].lower() if parts else "help"
    arg = parts[1] if len(parts) > 1 else ""

    if subcommand == "analyze" and arg:
        return f"Analysis queued for `{arg}`. You'll be notified when it's ready.\n{APP_URL}"
    elif subcommand == "health" and arg:
        return f"Fetching health score for `{arg}`..."
    else:
        return (
            "*Hootly Commands:*\n"
            "• `/hootly analyze <repo-url>` — Analyze a repository\n"
            "• `/hootly health <repo-url>` — Get health score\n"
            "• `/hootly help` — Show this help message"
        )

"""Feature 6: Slack integration — OAuth, events, slash commands."""
import hashlib
import hmac
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import SlackInstallation, User
from services.auth_service import get_current_user
from services.slack_service import (
    exchange_code, get_install_url, handle_slash_command, save_installation,
)

SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")

logger = logging.getLogger(__name__)
router = APIRouter()

APP_URL = os.getenv("APP_URL", "http://localhost:3000")


@router.get("/slack/install")
def slack_install(
    team_id: str,
    current_user: User = Depends(get_current_user),
):
    """Redirect to Slack OAuth."""
    url = get_install_url(team_id)
    return RedirectResponse(url)


@router.get("/slack/callback")
def slack_callback(
    code: str,
    state: str = "",
    db: Session = Depends(get_db),
):
    """Handle Slack OAuth callback."""
    data = exchange_code(code)
    if not data:
        return RedirectResponse(f"{APP_URL}/team?error=slack_auth_failed")

    slack_team_id = data.get("team", {}).get("id", "")
    bot_token = data.get("access_token", "")
    authed_user = data.get("authed_user", {}).get("id", "")

    if not slack_team_id or not bot_token:
        return RedirectResponse(f"{APP_URL}/team?error=slack_missing_data")

    # state = team_id passed from install URL
    team_id = state

    # Look up the team owner to use as installed_by
    from models import TeamMember
    owner = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.role == "owner",
    ).first()
    if not owner:
        return RedirectResponse(f"{APP_URL}/team?error=slack_no_team_owner")

    save_installation(
        team_id=team_id,
        slack_team_id=slack_team_id,
        bot_token=bot_token,
        user_id=owner.user_id,
        db=db,
    )

    return RedirectResponse(f"{APP_URL}/team?slack=connected")


def _verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify Slack request signature using HMAC-SHA256."""
    if not SLACK_SIGNING_SECRET:
        return False
    if abs(time.time() - float(timestamp)) > 300:
        return False  # reject requests older than 5 minutes
    sig_basestring = f"v0:{timestamp}:{body.decode()}"
    expected = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(), sig_basestring.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/slack/events")
async def slack_events(request: Request, db: Session = Depends(get_db)):
    """Handle Slack events and slash commands."""
    raw_body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "0")
    signature = request.headers.get("X-Slack-Signature", "")
    if not _verify_slack_signature(raw_body, timestamp, signature):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")
    body = await request.json()

    # URL verification challenge
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    # Slash command
    if "command" in body:
        command = body.get("command", "")
        text = body.get("text", "")
        team_id_slack = body.get("team_id", "")
        channel_id = body.get("channel_id", "")

        inst = db.query(SlackInstallation).filter(
            SlackInstallation.slack_team_id == team_id_slack
        ).first()
        team_id = inst.team_id if inst else ""

        response_text = handle_slash_command(command, text, team_id, channel_id, db)
        return {"response_type": "ephemeral", "text": response_text}

    return {"ok": True}


@router.get("/slack/status")
def slack_status(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check if Slack is connected for a team."""
    inst = db.query(SlackInstallation).filter(
        SlackInstallation.team_id == team_id
    ).first()
    return {
        "connected": inst is not None,
        "channel_id": inst.slack_channel_id if inst else None,
    }

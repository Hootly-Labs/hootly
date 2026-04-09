"""Team management endpoints — shared analyses for agencies and small teams."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Analysis, Team, TeamMember, User
from services.auth_service import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateTeamRequest(BaseModel):
    name: str


class InviteRequest(BaseModel):
    email: str


@router.post("/teams")
def create_team(
    req: CreateTeamRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = req.name.strip()
    if not name or len(name) > 100:
        raise HTTPException(status_code=400, detail="Team name must be 1-100 characters.")

    # Limit to 5 teams per user
    owned = db.query(Team).filter(Team.owner_id == current_user.id).count()
    if owned >= 5:
        raise HTTPException(status_code=400, detail="Maximum 5 teams per account.")

    team = Team(name=name, owner_id=current_user.id)
    db.add(team)
    db.flush()

    # Add creator as owner member
    member = TeamMember(
        team_id=team.id,
        user_id=current_user.id,
        role="owner",
        accepted=True,
    )
    db.add(member)
    db.commit()
    db.refresh(team)

    return _team_response(team, db)


@router.get("/teams")
def list_teams(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memberships = (
        db.query(TeamMember)
        .filter(TeamMember.user_id == current_user.id, TeamMember.accepted == True)
        .all()
    )
    team_ids = [m.team_id for m in memberships]
    teams = db.query(Team).filter(Team.id.in_(team_ids)).all() if team_ids else []
    return [_team_response(t, db) for t in teams]


@router.get("/teams/{team_id}")
def get_team(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    _check_membership(team_id, current_user.id, db)
    return _team_response(team, db)


@router.post("/teams/{team_id}/invite")
def invite_member(
    team_id: str,
    req: InviteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only team owner can invite members")

    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

    # Check if already invited
    existing = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.invited_email == email)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already invited")

    # Check member limit (10 per team)
    count = db.query(TeamMember).filter(TeamMember.team_id == team_id).count()
    if count >= 10:
        raise HTTPException(status_code=400, detail="Maximum 10 members per team")

    # Check if the invited user already exists
    invited_user = db.query(User).filter(User.email == email).first()

    member = TeamMember(
        team_id=team_id,
        user_id=invited_user.id if invited_user else None,
        role="member",
        invited_email=email,
        accepted=False,
    )
    db.add(member)
    db.commit()

    return {"detail": f"Invitation sent to {email}"}


@router.post("/teams/{team_id}/accept")
def accept_invite(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Find pending invite for this user
    invite = (
        db.query(TeamMember)
        .filter(
            TeamMember.team_id == team_id,
            TeamMember.accepted == False,
        )
        .filter(
            (TeamMember.user_id == current_user.id) | (TeamMember.invited_email == current_user.email)
        )
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="No pending invitation found")

    invite.user_id = current_user.id
    invite.accepted = True
    db.commit()

    return {"detail": "Invitation accepted"}


@router.delete("/teams/{team_id}/members/{user_id}")
def remove_member(
    team_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.owner_id != current_user.id and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Only team owner can remove members")
    if user_id == team.owner_id:
        raise HTTPException(status_code=400, detail="Cannot remove team owner")

    member = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    db.delete(member)
    db.commit()
    return {"detail": "Member removed"}


@router.get("/teams/{team_id}/analyses")
def list_team_analyses(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_membership(team_id, current_user.id, db)
    analyses = (
        db.query(Analysis)
        .filter(Analysis.team_id == team_id)
        .order_by(Analysis.created_at.desc())
        .limit(100)
        .all()
    )
    from api.routes import _to_response
    return [_to_response(a) for a in analyses]


# ── Feature 5: Multi-Repo Intelligence ───────────────────────────────────────

@router.get("/teams/{team_id}/org-health")
def get_org_health(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_membership(team_id, current_user.id, db)
    from services.org_service import get_org_health_dashboard
    return get_org_health_dashboard(team_id, db)


@router.get("/teams/{team_id}/cross-deps")
def get_cross_deps(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_membership(team_id, current_user.id, db)
    from services.org_service import detect_cross_repo_deps
    deps = detect_cross_repo_deps(team_id, db)
    return [
        {
            "id": d.id,
            "source_repo_url": d.source_repo_url,
            "target_repo_url": d.target_repo_url,
            "dependency_type": d.dependency_type,
            "dependency_name": d.dependency_name,
            "source_version": d.source_version,
            "target_version": d.target_version,
        }
        for d in deps
    ]


@router.get("/teams/{team_id}/patterns")
def get_shared_patterns(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_membership(team_id, current_user.id, db)
    from services.org_service import find_shared_patterns
    return find_shared_patterns(team_id, db)


def _check_membership(team_id: str, user_id: str, db: Session) -> None:
    member = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.user_id == user_id, TeamMember.accepted == True)
        .first()
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this team")


def _team_response(team: Team, db: Session) -> dict:
    members = db.query(TeamMember).filter(TeamMember.team_id == team.id).all()
    member_list = []
    for m in members:
        user = db.query(User).filter(User.id == m.user_id).first() if m.user_id else None
        member_list.append({
            "id": m.id,
            "user_id": m.user_id,
            "email": user.email if user else m.invited_email,
            "role": m.role,
            "accepted": m.accepted,
        })

    analysis_count = db.query(Analysis).filter(Analysis.team_id == team.id).count()

    return {
        "id": team.id,
        "name": team.name,
        "owner_id": team.owner_id,
        "plan": team.plan,
        "members": member_list,
        "analysis_count": analysis_count,
        "created_at": team.created_at.isoformat(),
    }

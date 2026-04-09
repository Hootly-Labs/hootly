"""Watched-repo endpoints: watch/unwatch a repo, list watched repos."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models import _utcnow, User, WatchedRepo
from services.auth_service import get_current_user
from services.git_service import parse_github_url
from services.client_ip import get_client_ip as _get_client_ip
from services.rate_limiter import check_rate_limit_key

router = APIRouter()


class WatchRequest(BaseModel):
    repo_url: str


class WatchResponse(BaseModel):
    id: str
    repo_url: str
    repo_name: str
    last_commit_hash: str | None = None
    last_checked_at: str | None = None
    last_changed_at: str | None = None
    created_at: str


_FREE_WATCH_LIMIT = 3

@router.post("/watch", response_model=WatchResponse)
def watch_repo(
    req: WatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    url = req.repo_url.strip()
    try:
        owner, repo = parse_github_url(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    canonical_url = f"https://github.com/{owner}/{repo}"
    repo_name = f"{owner}/{repo}"

    # Idempotent — return existing row if already watching
    existing = (
        db.query(WatchedRepo)
        .filter(
            WatchedRepo.user_id == current_user.id,
            WatchedRepo.repo_url == canonical_url,
        )
        .first()
    )
    if existing:
        return _to_response(existing)

    # Enforce watch limit for free users
    if current_user.plan == "free" and not current_user.is_admin:
        watch_count = db.query(WatchedRepo).filter(WatchedRepo.user_id == current_user.id).count()
        if watch_count >= _FREE_WATCH_LIMIT:
            raise HTTPException(
                status_code=403,
                detail=f"Free plan is limited to {_FREE_WATCH_LIMIT} watched repos. Upgrade to Pro for unlimited watching.",
            )

    watch = WatchedRepo(
        user_id=current_user.id,
        repo_url=canonical_url,
        repo_name=repo_name,
        created_at=_utcnow(),
    )
    try:
        db.add(watch)
        db.commit()
        db.refresh(watch)
        return _to_response(watch)
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(WatchedRepo)
            .filter(
                WatchedRepo.user_id == current_user.id,
                WatchedRepo.repo_url == canonical_url,
            )
            .first()
        )
        if existing:
            return _to_response(existing)
        raise


@router.delete("/watch/{watch_id}")
def unwatch_repo(
    watch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    watch = (
        db.query(WatchedRepo)
        .filter(WatchedRepo.id == watch_id, WatchedRepo.user_id == current_user.id)
        .first()
    )
    if not watch:
        raise HTTPException(status_code=404, detail="Watch not found")
    db.delete(watch)
    db.commit()
    return {"ok": True}


@router.get("/watches", response_model=list[WatchResponse])
def list_watches(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"watches:{ip}", max_requests=30, window=60)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many requests. Try again in {retry_after} seconds.")
    watches = (
        db.query(WatchedRepo)
        .filter(WatchedRepo.user_id == current_user.id)
        .order_by(WatchedRepo.created_at.desc())
        .all()
    )
    return [_to_response(w) for w in watches]


def _to_response(w: WatchedRepo) -> WatchResponse:
    return WatchResponse(
        id=w.id,
        repo_url=w.repo_url,
        repo_name=w.repo_name,
        last_commit_hash=w.last_commit_hash,
        last_checked_at=w.last_checked_at.isoformat() if w.last_checked_at else None,
        last_changed_at=w.last_changed_at.isoformat() if w.last_changed_at else None,
        created_at=w.created_at.isoformat(),
    )

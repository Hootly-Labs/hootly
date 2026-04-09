import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import Date, case, cast, func
from sqlalchemy.orm import Session

from database import get_db, _is_sqlite
from models import _utcnow, Analysis, User, WatchedRepo
from services.auth_service import get_current_user
from services.client_ip import get_client_ip as _get_client_ip
from services.rate_limiter import check_rate_limit_key

logger = logging.getLogger(__name__)
router = APIRouter()


def _date_trunc(col):
    """Return a date-only expression compatible with SQLite and PostgreSQL."""
    if _is_sqlite:
        return func.strftime('%Y-%m-%d', col)
    return cast(col, Date)


def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


class AdminStatsResponse(BaseModel):
    total_users: int
    free_users: int
    pro_users: int
    total_analyses: int
    completed_analyses: int
    recent_signups_30d: int
    analyses_today: int


class AdminUserResponse(BaseModel):
    id: str
    email: str
    plan: str
    is_admin: bool
    is_verified: bool
    created_at: str
    last_login: str | None
    analysis_count: int
    analyses_this_month: int


class PatchUserRequest(BaseModel):
    plan: str | None = None
    is_admin: bool | None = None


@router.get("/admin/stats", response_model=AdminStatsResponse)
def get_stats(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"admin:{ip}", max_requests=60, window=60)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many requests. Try again in {retry_after} seconds.")
    now = _utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = now - timedelta(days=30)

    total_users = db.query(User).count()
    free_users = db.query(User).filter(User.plan == "free").count()
    pro_users = db.query(User).filter(User.plan == "pro").count()
    total_analyses = db.query(Analysis).count()
    completed_analyses = db.query(Analysis).filter(Analysis.status == "completed").count()
    recent_signups_30d = db.query(User).filter(User.created_at >= thirty_days_ago).count()
    analyses_today = db.query(Analysis).filter(Analysis.created_at >= day_start).count()

    return AdminStatsResponse(
        total_users=total_users,
        free_users=free_users,
        pro_users=pro_users,
        total_analyses=total_analyses,
        completed_analyses=completed_analyses,
        recent_signups_30d=recent_signups_30d,
        analyses_today=analyses_today,
    )


@router.get("/admin/users", response_model=list[AdminUserResponse])
def list_users(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"admin:{ip}", max_requests=60, window=60)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many requests. Try again in {retry_after} seconds.")
    now = _utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Aggregate total and monthly analysis counts in two queries (avoids N+1)
    total_counts = dict(
        db.query(Analysis.user_id, func.count(Analysis.id))
        .group_by(Analysis.user_id)
        .all()
    )
    month_counts = dict(
        db.query(Analysis.user_id, func.count(Analysis.id))
        .filter(Analysis.created_at >= month_start)
        .group_by(Analysis.user_id)
        .all()
    )

    users = db.query(User).order_by(User.created_at.desc()).limit(limit).offset(offset).all()
    return [
        AdminUserResponse(
            id=u.id,
            email=u.email,
            plan=u.plan,
            is_admin=u.is_admin,
            is_verified=getattr(u, "is_verified", True),
            created_at=u.created_at.isoformat(),
            last_login=u.last_login.isoformat() if u.last_login else None,
            analysis_count=total_counts.get(u.id, 0),
            analyses_this_month=month_counts.get(u.id, 0),
        )
        for u in users
    ]


@router.patch("/admin/users/{user_id}", response_model=AdminUserResponse)
def patch_user(
    user_id: str,
    req: PatchUserRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.plan is not None:
        if req.plan not in ("free", "pro"):
            raise HTTPException(status_code=400, detail="plan must be 'free' or 'pro'")
        old_plan = user.plan
        user.plan = req.plan
        logger.info("Admin %s changed user %s plan: %s → %s", _admin.id, user.id, old_plan, req.plan)

    if req.is_admin is not None:
        if user.id == _admin.id:
            raise HTTPException(status_code=400, detail="You cannot change your own admin status")
        if req.is_admin is False:
            # Prevent demoting the last admin — there must always be at least one
            other_admins = (
                db.query(User)
                .filter(User.is_admin == True, User.id != user.id)  # noqa: E712
                .count()
            )
            if other_admins == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot demote the last admin. Promote another user first.",
                )
            user.plan = "free"  # Admins get Pro by default; revoking admin revokes Pro
        if req.is_admin is True:
            user.plan = "pro"  # Grant Pro when promoting to admin
        logger.info(
            "Admin %s changed user %s admin status: %s → %s",
            _admin.id, user.id, user.is_admin, req.is_admin,
        )
        user.is_admin = req.is_admin

    db.commit()
    db.refresh(user)

    now = _utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    analysis_count = db.query(Analysis).filter(Analysis.user_id == user.id).count()
    analyses_this_month = (
        db.query(Analysis)
        .filter(Analysis.user_id == user.id, Analysis.created_at >= month_start)
        .count()
    )

    return AdminUserResponse(
        id=user.id,
        email=user.email,
        plan=user.plan,
        is_admin=user.is_admin,
        is_verified=getattr(user, "is_verified", True),
        created_at=user.created_at.isoformat(),
        last_login=user.last_login.isoformat() if user.last_login else None,
        analysis_count=analysis_count,
        analyses_this_month=analyses_this_month,
    )


@router.delete("/admin/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account from here")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_admin:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an admin user. Remove their admin status first.",
        )

    db.query(WatchedRepo).filter(WatchedRepo.user_id == user_id).delete()
    db.query(Analysis).filter(Analysis.user_id == user_id).delete()
    logger.info("AUDIT admin_delete_user admin_id=%s target_email=%s target_id=%s", admin.id, user.email, user_id)
    db.delete(user)
    db.commit()


@router.post("/admin/users/{user_id}/ban", status_code=200)
def ban_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    """Ban a user and immediately invalidate all their tokens."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot ban yourself")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot ban an admin user")
    user.is_banned = True
    user.token_invalidated_at = _utcnow()
    db.commit()
    ip = _get_client_ip(request)
    logger.warning("Admin %s banned user %s (%s) from IP %s", admin.id, user.id, user.email, ip)
    return {"detail": f"User {user.email} has been banned and all tokens invalidated."}


@router.post("/admin/users/{user_id}/unban", status_code=200)
def unban_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_banned = False
    db.commit()
    logger.info("Admin %s unbanned user %s (%s)", admin.id, user.id, user.email)
    return {"detail": f"User {user.email} has been unbanned."}


@router.post("/admin/users/{user_id}/revoke-tokens", status_code=200)
def revoke_user_tokens(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    """Invalidate all existing tokens for a user without banning them."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.token_invalidated_at = _utcnow()
    db.commit()
    logger.info("Admin %s revoked all tokens for user %s (%s)", admin.id, user.id, user.email)
    return {"detail": f"All tokens for {user.email} have been invalidated."}


class DailyAnalysisStat(BaseModel):
    date: str
    total: int
    completed: int
    failed: int


class DailySignupStat(BaseModel):
    date: str
    signups: int


class AdminChartsResponse(BaseModel):
    daily_analyses: list[DailyAnalysisStat]
    daily_signups: list[DailySignupStat]


@router.get("/admin/charts", response_model=AdminChartsResponse)
def get_charts(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"admin:{ip}", max_requests=60, window=60)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many requests. Try again in {retry_after} seconds.")
    cutoff = _utcnow() - timedelta(days=30)

    analysis_rows = (
        db.query(
            _date_trunc(Analysis.created_at).label("date"),
            func.count(Analysis.id).label("total"),
            func.sum(case((Analysis.status == "completed", 1), else_=0)).label("completed"),
            func.sum(case((Analysis.status == "failed", 1), else_=0)).label("failed"),
        )
        .filter(Analysis.created_at >= cutoff)
        .group_by(_date_trunc(Analysis.created_at))
        .order_by("date")
        .all()
    )

    signup_rows = (
        db.query(
            _date_trunc(User.created_at).label("date"),
            func.count(User.id).label("signups"),
        )
        .filter(User.created_at >= cutoff)
        .group_by(_date_trunc(User.created_at))
        .order_by("date")
        .all()
    )

    return AdminChartsResponse(
        daily_analyses=[
            DailyAnalysisStat(date=str(r.date), total=r.total, completed=r.completed, failed=r.failed)
            for r in analysis_rows
        ],
        daily_signups=[
            DailySignupStat(date=str(r.date), signups=r.signups)
            for r in signup_rows
        ],
    )

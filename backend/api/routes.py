import json
import logging
import os
from datetime import timedelta

import httpx

_logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import case, cast, Date, func
from sqlalchemy.orm import Session

from database import get_db, _is_sqlite
from models import ACTIVE_ANALYSIS_STATUSES, _utcnow, Analysis, User
from services.git_service import parse_github_url, clone_repo, make_temp_dir, cleanup_temp_dir, get_commit_hash
from services.file_service import walk_repo, SKIP_DIRS
from services.claude_service import run_analysis_pipeline, generate_changelog
from services.dependency_parser import parse_dependencies
from services.rate_limiter import check_rate_limit, check_rate_limit_key, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW
from services.auth_service import get_current_user, get_current_user_or_api_key
from services.email_service import send_analysis_complete_email
from services.encryption import decrypt as decrypt_field
from services.snapshot_service import create_snapshot, generate_drift_alerts
from services.impact_service import analyze_impact, explain_data_flow
from services.benchmark_service import generate_benchmark_report

APP_URL = os.getenv("APP_URL", "http://localhost:3000")

from services.client_ip import get_client_ip as _get_client_ip

# Repo size limits (applied only to non-skipped source files)
_MAX_REPO_FILES = {"free": 2_000,                    "pro": 10_000}
_MAX_REPO_BYTES = {"free": 100 * 1024 * 1024,        "pro": 500 * 1024 * 1024}  # 100 MB / 500 MB

# Free plan monthly analysis limit
_FREE_PLAN_MONTHLY_LIMIT = 1


def _check_repo_limits(repo_dir: str, plan: str = "free") -> None:
    """Raise RuntimeError if the cloned repo exceeds file count or size limits.

    Mirrors the same directory skip logic as walk_repo so that node_modules,
    .git, dist, build, etc. do not count against the limit.
    Pro users get higher file and byte ceilings.
    """
    max_files = _MAX_REPO_FILES.get(plan, _MAX_REPO_FILES["free"])
    max_bytes = _MAX_REPO_BYTES.get(plan, _MAX_REPO_BYTES["free"])
    max_mb = max_bytes // (1024 * 1024)
    file_count = 0
    total_bytes = 0
    for dirpath, dirnames, filenames in os.walk(repo_dir):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
        ]
        for fname in filenames:
            file_count += 1
            try:
                total_bytes += os.path.getsize(os.path.join(dirpath, fname))
            except OSError:
                pass
            if file_count > max_files:
                if plan == "free":
                    raise RuntimeError(
                        f"Repository exceeds the Free plan limit of {max_files:,} files. "
                        "Upgrade to Pro to analyze larger repos."
                    )
                raise RuntimeError(
                    f"Repository is too large: exceeds {max_files:,} source files."
                )
            if total_bytes > max_bytes:
                if plan == "free":
                    raise RuntimeError(
                        f"Repository exceeds the Free plan size limit of {max_mb} MB. "
                        "Upgrade to Pro to analyze larger repos."
                    )
                raise RuntimeError(
                    f"Repository is too large: exceeds the {max_mb} MB size limit."
                )

router = APIRouter()


def _date_trunc(col):
    """Return a date-only expression compatible with SQLite and PostgreSQL."""
    if _is_sqlite:
        return func.strftime('%Y-%m-%d', col)
    return cast(col, Date)


def _check_repo_accessibility(owner: str, repo: str, github_token: str | None = None) -> None:
    """Check if a GitHub repo is accessible.

    Raises HTTPException for clearly actionable errors (private repo with no
    token, invalid/expired token). Returns silently on network errors or
    ambiguous status codes so analysis can proceed and fail naturally.
    """
    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=headers,
            timeout=8,
        )
    except Exception:
        return  # Network error — let clone fail naturally

    if resp.status_code == 200:
        return
    if resp.status_code == 404:
        if not github_token:
            raise HTTPException(status_code=422, detail="PRIVATE_REPO_NO_TOKEN")
        raise HTTPException(status_code=404, detail="Repository not found. Check the URL and ensure your GitHub connection has access.")
    if resp.status_code in (401, 403):
        raise HTTPException(status_code=422, detail="PRIVATE_REPO_TOKEN_INVALID")
    # Other statuses (429, 5xx, …) — fall through silently


class AnalyzeRequest(BaseModel):
    repo_url: str
    force: bool = False  # if True, bypass cache and re-run the full pipeline
    team_id: str | None = None  # optional team to assign analysis to


class AnalysisResponse(BaseModel):
    id: str
    repo_url: str
    repo_name: str
    status: str
    stage: str
    created_at: str
    commit_hash: str | None = None
    from_cache: bool = False
    is_starred: bool = False
    is_public: bool = False
    error_message: str | None = None
    result: dict | None = None
    changelog: dict | None = None
    health_score: dict | None = None


class UserStatsResponse(BaseModel):
    total_analyses: int
    completed_analyses: int
    starred_count: int
    analyses_this_month: int
    monthly_limit: int | None
    daily_analyses: list[dict]
    top_repos: list[dict]


def _do_analysis(analysis_id: str, force: bool = False, plan: str = "free", github_token: str | None = None, previous_result: str | None = None, alert_user_ids: list[str] | None = None):
    """Background task: clone repo, run pipeline, update DB."""
    from database import SessionLocal

    db = SessionLocal()
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        db.close()
        return

    temp_dir = make_temp_dir(analysis_id)
    try:
        # Clone
        _update_status(db, analysis, "cloning", "Cloning repository...")
        clone_repo(analysis.repo_url, temp_dir, github_token=github_token)

        # Enforce size limits before doing anything expensive
        _check_repo_limits(temp_dir, plan=plan)

        # Cache lookup: if we already have a completed analysis for this exact
        # commit, skip the expensive Claude pipeline.
        commit_hash = get_commit_hash(temp_dir)
        analysis.commit_hash = commit_hash
        db.commit()

        if not force and commit_hash:
            cached = (
                db.query(Analysis)
                .filter(
                    Analysis.repo_url == analysis.repo_url,
                    Analysis.commit_hash == commit_hash,
                    Analysis.status == "completed",
                    Analysis.id != analysis.id,
                )
                .order_by(Analysis.created_at.desc())
                .first()
            )
            if cached and cached.result:
                analysis.result = cached.result
                analysis.status = "completed"
                analysis.stage = "Done (from cache)"
                analysis.updated_at = _utcnow()
                db.commit()
                # Copy embeddings from cached analysis
                try:
                    from services.embedding_service import copy_embeddings_for_cache_hit
                    copy_embeddings_for_cache_hit(cached.id, analysis.id, db)
                except Exception:
                    pass
                return  # skip pipeline entirely

        # Walk file tree
        _update_status(db, analysis, "analyzing", "Walking file tree...")
        walked = walk_repo(temp_dir, plan=plan)
        tree = walked["tree"]
        files = walked["files"]

        if not tree:
            raise RuntimeError(
                "Repository appears to be empty — no source files were found."
            )
        if not files:
            raise RuntimeError(
                "No readable source files found. "
                "The repository may contain only binary or generated files."
            )

        # Build dependency graph (fast, no Claude call)
        # Use dep_files (up to 500 source files, 4KB each) for better accuracy
        # than the 60-file Claude read set.
        _update_status(db, analysis, "analyzing", "Building dependency graph...")
        dep_files = walked.get("dep_files", files)
        dep_graph = parse_dependencies(dep_files, tree)

        # Run pipeline
        def progress_cb(msg: str):
            _update_status(db, analysis, "analyzing", msg)

        test_files = walked.get("test_files", [])

        result = run_analysis_pipeline(
            repo_name=analysis.repo_name,
            tree=tree,
            all_files=files,
            progress_cb=progress_cb,
            dep_graph=dep_graph,
            test_files=test_files,
        )
        result["dependency_graph"] = dep_graph

        # Compute health score (no Claude calls — pure computation)
        try:
            from services.health_service import compute_health_score
            health = compute_health_score(result, files)
            analysis.health_score = json.dumps(health)
        except Exception as exc:
            _logger.warning("Health score computation failed: %s", exc)

        # Changelog: compare to previous analysis if this was auto-triggered by a watch event
        if previous_result:
            try:
                _update_status(db, analysis, "analyzing", "Generating changelog...")
                old = json.loads(previous_result)
                changelog = generate_changelog(analysis.repo_name, old, result)
                analysis.changelog = json.dumps(changelog)
            except Exception as exc:
                _logger.warning("Changelog generation failed: %s", exc)

        # Save result
        analysis.result = json.dumps(result)
        analysis.status = "completed"
        analysis.stage = "Done"
        analysis.updated_at = _utcnow()
        db.commit()

        # Email notification
        if analysis.user_id:
            owner = db.query(User).filter(User.id == analysis.user_id).first()
            if owner and getattr(owner, "notify_on_complete", False):
                analysis_url = f"{APP_URL}/analysis/{analysis.id}"
                send_analysis_complete_email(owner.email, analysis.repo_name, analysis_url)

        # Embed source files for RAG chat (Vector search)
        try:
            from services.embedding_service import embed_analysis_files
            chunk_count = embed_analysis_files(analysis.id, files, db)
            _logger.info("Embedded %d chunks for analysis %s", chunk_count, analysis.id)
        except Exception as exc:
            _logger.warning("Embedding failed (non-fatal): %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

        # Snapshot + drift detection (Feature 1)
        try:
            from models import RepoSnapshot
            snapshot = create_snapshot(analysis, db)
            if snapshot:
                prev_snapshot = (
                    db.query(RepoSnapshot)
                    .filter(
                        RepoSnapshot.repo_url == analysis.repo_url,
                        RepoSnapshot.id != snapshot.id,
                    )
                    .order_by(RepoSnapshot.snapshot_date.desc())
                    .first()
                )
                if prev_snapshot:
                    # Alert all watching users if provided, otherwise just the analysis owner
                    drift_users = alert_user_ids if alert_user_ids else (
                        [analysis.user_id] if analysis.user_id else []
                    )
                    if drift_users:
                        generate_drift_alerts(drift_users, analysis.repo_url, prev_snapshot, snapshot, db)
        except Exception as exc:
            _logger.warning("Snapshot/drift detection failed: %s", exc)

    except RuntimeError as exc:
        # RuntimeErrors are intentional user-facing messages (repo too large, empty, etc.)
        analysis.status = "failed"
        analysis.stage = "Failed"
        analysis.error_message = str(exc)
        analysis.updated_at = _utcnow()
        db.commit()
    except Exception as exc:
        # Unexpected library exceptions — log full details server-side, show generic message
        _logger.exception("Unexpected error in analysis %s: %s", analysis_id, exc)
        analysis.status = "failed"
        analysis.stage = "Failed"
        analysis.error_message = "An unexpected error occurred. Please try again."
        analysis.updated_at = _utcnow()
        db.commit()
    finally:
        db.close()
        cleanup_temp_dir(temp_dir)


def _update_status(db: Session, analysis: Analysis, status: str, stage: str):
    analysis.status = status
    analysis.stage = stage
    analysis.updated_at = _utcnow()
    db.commit()


@router.post("/analyze", response_model=AnalysisResponse)
def start_analysis(
    req: AnalyzeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    # ── Email verification check ───────────────────────────────────────────────
    if not getattr(current_user, "is_verified", True):
        raise HTTPException(status_code=403, detail="Please verify your email before running analyses.")

    # ── Rate limiting ──────────────────────────────────────────────────────────
    client_ip = _get_client_ip(request)

    # Per-user rate limit (in addition to IP-based)
    user_allowed, user_retry = check_rate_limit_key(
        f"analyze_user:{current_user.id}", max_requests=RATE_LIMIT_MAX, window=RATE_LIMIT_WINDOW
    )
    if not user_allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded. Try again in {user_retry // 60} minute(s)."},
            headers={"Retry-After": str(user_retry)},
        )

    allowed, remaining, retry_after = check_rate_limit(client_ip)
    if not allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={
                "detail": (
                    f"Rate limit exceeded: max {RATE_LIMIT_MAX} analyses per hour. "
                    f"Try again in {retry_after // 60} minute(s) and {retry_after % 60} second(s)."
                )
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(RATE_LIMIT_MAX),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(__import__("time").time()) + retry_after),
            },
        )

    # ── Monthly limit for free users ──────────────────────────────────────────
    if current_user.plan == "free":
        now = _utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_count = (
            db.query(Analysis)
            .filter(
                Analysis.user_id == current_user.id,
                Analysis.created_at >= month_start,
                Analysis.status.in_(ACTIVE_ANALYSIS_STATUSES),
            )
            .count()
        )
        if monthly_count >= _FREE_PLAN_MONTHLY_LIMIT:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        "Free plan limit reached: 1 analysis per month. "
                        "Upgrade to Pro for unlimited analyses."
                    )
                },
            )

    # ── force=True is Pro-only ────────────────────────────────────────────────
    if req.force and current_user.plan != "pro" and not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Force re-analysis is available on the Pro plan. Upgrade to use it.",
        )

    url = req.repo_url.strip()

    # Reject suspiciously long inputs before any parsing
    if len(url) > 300:
        raise HTTPException(status_code=400, detail="URL is too long. Expected a GitHub repo URL.")

    # Reject percent-encoded URLs — valid GitHub URLs never need encoding
    if "%" in url:
        raise HTTPException(status_code=400, detail="Invalid URL. Expected a plain GitHub repo URL.")

    try:
        owner, repo = parse_github_url(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    repo_name = f"{owner}/{repo}"
    canonical_url = f"https://github.com/{owner}/{repo}"

    _enc_token = getattr(current_user, "github_access_token", None)
    github_token = decrypt_field(_enc_token) if _enc_token else None
    _check_repo_accessibility(owner, repo, github_token)

    # Validate team membership if team_id provided
    team_id = req.team_id
    if team_id:
        from models import TeamMember
        is_member = (
            db.query(TeamMember)
            .filter(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id, TeamMember.accepted == True)
            .first()
        )
        if not is_member and not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Not a member of this team")

    analysis = Analysis(
        repo_url=canonical_url,
        repo_name=repo_name,
        status="pending",
        stage="Queued",
        user_id=current_user.id,
        team_id=team_id,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    _logger.info("AUDIT analysis_started user_id=%s repo=%s analysis_id=%s force=%s", current_user.id, repo_name, analysis.id, req.force)

    # Run in background thread (BackgroundTasks runs after response)
    background_tasks.add_task(_do_analysis, analysis.id, req.force, current_user.plan, github_token)

    from fastapi.responses import JSONResponse
    resp_data = _to_response(analysis)
    return JSONResponse(
        content=resp_data.model_dump(),
        headers={
            "X-RateLimit-Limit": str(RATE_LIMIT_MAX),
            "X-RateLimit-Remaining": str(remaining),
        },
    )


@router.get("/analysis/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(
    analysis_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"get_analysis:{ip}", max_requests=120, window=60)
    if not allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=429, content={"detail": f"Too many requests. Try again in {retry_after} seconds."})
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    # Users can only see their own analyses (admins see all)
    if not current_user.is_admin and analysis.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return _to_response(analysis)


@router.get("/analyses", response_model=list[AnalysisResponse])
def list_analyses(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"list_analyses:{ip}", max_requests=60, window=60)
    if not allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=429, content={"detail": f"Too many requests. Try again in {retry_after} seconds."})
    query = db.query(Analysis)
    if not current_user.is_admin:
        query = query.filter(Analysis.user_id == current_user.id)
    analyses = query.order_by(Analysis.created_at.desc()).limit(limit).offset(offset).all()
    return [_to_response(a) for a in analyses]


@router.get("/user/stats", response_model=UserStatsResponse)
def get_user_stats(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"user_stats:{ip}", max_requests=30, window=60)
    if not allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=429, content={"detail": f"Too many requests. Try again in {retry_after} seconds."})
    now = _utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cutoff = now - timedelta(days=30)
    uid = current_user.id

    total = db.query(Analysis).filter(Analysis.user_id == uid).count()
    completed = db.query(Analysis).filter(Analysis.user_id == uid, Analysis.status == "completed").count()
    starred = db.query(Analysis).filter(Analysis.user_id == uid, Analysis.is_starred == True).count()  # noqa: E712
    this_month = db.query(Analysis).filter(
        Analysis.user_id == uid,
        Analysis.created_at >= month_start,
        Analysis.status.in_(ACTIVE_ANALYSIS_STATUSES),
    ).count()

    rows = (
        db.query(
            _date_trunc(Analysis.created_at).label("date"),
            func.count(Analysis.id).label("total"),
            func.sum(case((Analysis.status == "completed", 1), else_=0)).label("completed"),
            func.sum(case((Analysis.status == "failed", 1), else_=0)).label("failed"),
        )
        .filter(Analysis.user_id == uid, Analysis.created_at >= cutoff)
        .group_by(_date_trunc(Analysis.created_at))
        .order_by("date")
        .all()
    )

    repo_rows = (
        db.query(
            Analysis.repo_name,
            func.count(Analysis.id).label("count"),
            func.max(Analysis.created_at).label("last_analyzed_at"),
        )
        .filter(Analysis.user_id == uid)
        .group_by(Analysis.repo_name)
        .order_by(func.count(Analysis.id).desc())
        .limit(10)
        .all()
    )

    return UserStatsResponse(
        total_analyses=total,
        completed_analyses=completed,
        starred_count=starred,
        analyses_this_month=this_month,
        monthly_limit=_FREE_PLAN_MONTHLY_LIMIT if current_user.plan == "free" else None,
        daily_analyses=[
            {"date": str(r.date), "total": r.total, "completed": r.completed, "failed": r.failed}
            for r in rows
        ],
        top_repos=[
            {"repo_name": r.repo_name, "count": r.count, "last_analyzed_at": r.last_analyzed_at.isoformat()}
            for r in repo_rows
        ],
    )


@router.patch("/analysis/{analysis_id}/star")
def toggle_star(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis or analysis.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    analysis.is_starred = not analysis.is_starred
    db.commit()
    _logger.info("AUDIT star_toggled user_id=%s analysis_id=%s is_starred=%s", current_user.id, analysis_id, analysis.is_starred)
    return {"is_starred": analysis.is_starred}


@router.patch("/analysis/{analysis_id}/visibility")
def set_visibility(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis or analysis.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    analysis.is_public = not analysis.is_public
    db.commit()
    _logger.info("AUDIT visibility_toggled user_id=%s analysis_id=%s is_public=%s", current_user.id, analysis_id, analysis.is_public)
    return {"is_public": analysis.is_public}


@router.get("/public/analysis/{analysis_id}", response_model=AnalysisResponse)
def get_public_analysis(analysis_id: str, request: Request, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"public:{ip}", max_requests=60, window=3600)
    if not allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={"detail": f"Too many requests. Try again in {retry_after} seconds."},
        )
    analysis = db.query(Analysis).filter(
        Analysis.id == analysis_id,
        Analysis.is_public == True,  # noqa: E712
        Analysis.status == "completed",
    ).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found or not public")
    return _to_response(analysis)


@router.get("/github/repos")
def get_github_repos(request: Request, page: int = 1, current_user: User = Depends(get_current_user)):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"github_repos:{ip}", max_requests=30, window=60)
    if not allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=429, content={"detail": f"Too many requests. Try again in {retry_after} seconds."})
    _enc_token = getattr(current_user, "github_access_token", None)
    token = decrypt_field(_enc_token) if _enc_token else None
    if not token:
        return []
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        with httpx.Client(timeout=8) as client:
            repos_resp = client.get(
                "https://api.github.com/user/repos",
                params={
                    "sort": "updated",
                    "per_page": 100,
                    "visibility": "all",
                    "affiliation": "owner,collaborator,organization",
                    "page": page,
                },
                headers=headers,
            )
            starred_resp = client.get(
                "https://api.github.com/user/starred",
                params={"per_page": 100},
                headers=headers,
            )
        if not repos_resp.is_success:
            return []
        starred_set = {r["full_name"] for r in starred_resp.json()} if starred_resp.is_success else set()
        return [
            {
                "name": r["name"],
                "full_name": r["full_name"],
                "private": r["private"],
                "description": r.get("description") or "",
                "updated_at": r["updated_at"],
                "html_url": r["html_url"],
                "language": r.get("language") or "",
                "github_starred": r["full_name"] in starred_set,
            }
            for r in repos_resp.json()
        ]
    except Exception:
        return []


# ── Feature 1: Drift Alerts ──────────────────────────────────────────────────

@router.get("/alerts")
def list_alerts(
    read: bool | None = None,
    dismissed: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models import DriftAlert
    q = db.query(DriftAlert).filter(DriftAlert.user_id == current_user.id)
    if read is not None:
        q = q.filter(DriftAlert.read == read)
    if dismissed is not None:
        q = q.filter(DriftAlert.dismissed == dismissed)
    alerts = q.order_by(DriftAlert.created_at.desc()).limit(limit).offset(offset).all()
    return [
        {
            "id": a.id,
            "repo_url": a.repo_url,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "message": a.message,
            "details": json.loads(a.details) if a.details else {},
            "created_at": a.created_at.isoformat(),
            "read": a.read,
            "dismissed": a.dismissed,
        }
        for a in alerts
    ]


@router.patch("/alerts/{alert_id}")
def update_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models import DriftAlert
    alert = db.query(DriftAlert).filter(DriftAlert.id == alert_id, DriftAlert.user_id == current_user.id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not alert.read:
        alert.read = True
    else:
        alert.dismissed = True
    db.commit()
    return {"id": alert.id, "read": alert.read, "dismissed": alert.dismissed}


@router.get("/analysis/{analysis_id}/history")
def analysis_history(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=404, detail="Analysis not found")

    from models import RepoSnapshot
    snapshots = (
        db.query(RepoSnapshot)
        .filter(RepoSnapshot.repo_url == analysis.repo_url)
        .order_by(RepoSnapshot.snapshot_date.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": s.id,
            "analysis_id": s.analysis_id,
            "commit_hash": s.commit_hash,
            "snapshot_date": s.snapshot_date.isoformat(),
            "file_count": s.file_count,
            "health_score": json.loads(s.health_score) if s.health_score else None,
            "tech_stack": json.loads(s.tech_stack) if s.tech_stack else [],
        }
        for s in snapshots
    ]


# ── Feature 2: Impact Analysis ──────────────────────────────────────────────

class ImpactRequest(BaseModel):
    file_path: str


class FlowRequest(BaseModel):
    from_file: str
    to_file: str


@router.post("/analysis/{analysis_id}/impact")
def get_impact(
    analysis_id: str,
    req: ImpactRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis or not analysis.result:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=404, detail="Analysis not found")

    result = json.loads(analysis.result)
    return analyze_impact(result, req.file_path)


@router.post("/analysis/{analysis_id}/explain-flow")
def get_flow(
    analysis_id: str,
    req: FlowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis or not analysis.result:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=404, detail="Analysis not found")

    result = json.loads(analysis.result)
    return explain_data_flow(result, req.from_file, req.to_file)


# ── Feature 3: Benchmarking ─────────────────────────────────────────────────

@router.get("/analysis/{analysis_id}/benchmark")
def get_benchmark(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=404, detail="Analysis not found")

    report = generate_benchmark_report(analysis_id, db)
    if not report:
        return {"has_benchmark": False, "message": "No benchmark data available for this analysis."}
    return report


def _to_response(a: Analysis) -> AnalysisResponse:
    result_dict = None
    if a.result:
        try:
            result_dict = json.loads(a.result)
        except Exception:
            pass
    changelog_dict = None
    if getattr(a, "changelog", None):
        try:
            changelog_dict = json.loads(a.changelog)
        except Exception:
            pass
    health_dict = None
    if getattr(a, "health_score", None):
        try:
            health_dict = json.loads(a.health_score)
        except Exception:
            pass

    return AnalysisResponse(
        id=a.id,
        repo_url=a.repo_url,
        repo_name=a.repo_name,
        status=a.status,
        stage=a.stage,
        created_at=a.created_at.isoformat(),
        commit_hash=getattr(a, "commit_hash", None),
        from_cache="from cache" in (a.stage or "").lower(),
        is_starred=getattr(a, "is_starred", False),
        is_public=getattr(a, "is_public", False),
        error_message=a.error_message,
        result=result_dict,
        changelog=changelog_dict,
        health_score=health_dict,
    )

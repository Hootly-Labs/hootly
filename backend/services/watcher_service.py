"""Background service: poll watched repos for new commits and trigger re-analysis."""
import logging
import os
import threading
import time

import httpx

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECONDS = int(os.getenv("WATCH_INTERVAL_HOURS", "1")) * 3600
APP_URL = os.getenv("APP_URL", "http://localhost:3000")


def get_latest_commit(owner: str, repo: str, github_token: str | None = None) -> str:
    """Return the HEAD commit SHA via GitHub API without cloning.

    Uses the lightweight SHA-only accept header so the response body is just
    the 40-char SHA string.  Returns empty string on any failure.
    """
    headers = {
        "Accept": "application/vnd.github.sha",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/HEAD",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.text.strip()
        logger.debug("GitHub API returned %d for %s/%s", resp.status_code, owner, repo)
    except Exception as exc:
        logger.warning("Failed to fetch latest commit for %s/%s: %s", owner, repo, exc)
    return ""


def check_watched_repos() -> None:
    """Check every watched repo for a new HEAD commit.

    Public repos are deduplicated: one API call and one analysis per repo URL,
    shared across all watchers. Private repos (user has a GitHub token) are
    checked per-user since each user's token may have different access.

    When a change is found:
    - updates last_commit_hash / last_changed_at on all WatchedRepo rows for that URL
    - creates one Analysis record and fires _do_analysis in a daemon thread
    - creates drift alerts for ALL users watching the repo
    - sends change-notification emails to users who opted in
    """
    from database import SessionLocal
    from models import ACTIVE_ANALYSIS_STATUSES, _utcnow, Analysis, User, WatchedRepo
    from services.git_service import parse_github_url
    from services.email_service import send_repo_changed_email

    db = SessionLocal()
    try:
        watches = db.query(WatchedRepo).all()
        logger.debug("Checking %d watched repos", len(watches))

        # Group watches by repo_url
        repo_groups: dict[str, list] = {}
        for watch in watches:
            repo_groups.setdefault(watch.repo_url, []).append(watch)

        # Track which public repos we've already checked + analyzed this cycle
        checked_public: dict[str, str] = {}  # repo_url → latest_commit or ""

        for repo_url, group in repo_groups.items():
            try:
                try:
                    owner, repo = parse_github_url(repo_url)
                except ValueError:
                    continue

                # Determine if this is a private repo (any watcher has a token)
                # and collect user info for all watchers
                watcher_info = []  # list of {user, watch, github_token, is_private}
                for watch in group:
                    user = db.query(User).filter(User.id == watch.user_id).first()
                    _enc_token = getattr(user, "github_access_token", None) if user else None
                    if _enc_token:
                        from services.encryption import decrypt as decrypt_field
                        github_token = decrypt_field(_enc_token)
                    else:
                        github_token = None
                    watcher_info.append({
                        "user": user,
                        "watch": watch,
                        "github_token": github_token,
                        "is_private": github_token is not None,
                    })

                # Split into public watchers (no token) and private watchers (have token)
                public_watchers = [w for w in watcher_info if not w["is_private"]]
                private_watchers = [w for w in watcher_info if w["is_private"]]

                # ── Handle public watchers (deduplicated: one API call per repo) ──
                if public_watchers:
                    if repo_url not in checked_public:
                        latest = get_latest_commit(owner, repo)
                        checked_public[repo_url] = latest
                    else:
                        latest = checked_public[repo_url]

                    _process_repo_change(
                        db, repo_url, latest, public_watchers, owner, repo, github_token=None,
                    )

                # ── Handle private watchers (per-user: each uses their own token) ──
                for pw in private_watchers:
                    latest = get_latest_commit(owner, repo, pw["github_token"])
                    _process_repo_change(
                        db, repo_url, latest, [pw], owner, repo, github_token=pw["github_token"],
                    )

            except Exception as exc:
                logger.error("Error processing watches for %s: %s", repo_url, exc)
                try:
                    db.rollback()
                except Exception:
                    pass
    finally:
        db.close()


def _process_repo_change(
    db,
    repo_url: str,
    latest_commit: str,
    watcher_info: list[dict],
    owner: str,
    repo: str,
    github_token: str | None,
) -> None:
    """Process a potential repo change for a group of watchers.

    If the commit hasn't changed, just updates last_checked_at.
    If it has changed, runs one analysis and notifies all watchers.
    """
    from models import ACTIVE_ANALYSIS_STATUSES, _utcnow, Analysis, User
    from services.email_service import send_repo_changed_email

    first_watch = watcher_info[0]["watch"]

    # Update last_checked_at for all watches
    for wi in watcher_info:
        wi["watch"].last_checked_at = _utcnow()

    if not latest_commit:
        db.commit()
        return

    # Check if any watch in this group already has this commit
    if first_watch.last_commit_hash == latest_commit:
        db.commit()
        return

    # New commit detected
    logger.info(
        "Change on %s: %s → %s (%d watchers)",
        repo_url,
        (first_watch.last_commit_hash or "none")[:7],
        latest_commit[:7],
        len(watcher_info),
    )

    # Update all watches with the new commit
    for wi in watcher_info:
        wi["watch"].last_commit_hash = latest_commit
        wi["watch"].last_changed_at = _utcnow()
    db.commit()

    # Find the best user to run the analysis as (prefer pro plan)
    eligible_users = []
    for wi in watcher_info:
        user = wi["user"]
        if not user:
            continue

        plan = getattr(user, "plan", "free")
        if plan == "free":
            now = _utcnow()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            monthly_count = (
                db.query(Analysis)
                .filter(
                    Analysis.user_id == user.id,
                    Analysis.created_at >= month_start,
                    Analysis.status.in_(ACTIVE_ANALYSIS_STATUSES),
                )
                .count()
            )
            if monthly_count >= 1:
                continue  # skip users at their free limit

        eligible_users.append({"user": user, "plan": plan})

    if not eligible_users:
        logger.info("Skipping auto-analysis for %s: all watchers at free limit", repo_url)
        return

    # Prefer pro users so the analysis gets higher file limits
    eligible_users.sort(key=lambda u: 0 if u["plan"] == "pro" else 1)
    analysis_user = eligible_users[0]["user"]
    analysis_plan = eligible_users[0]["plan"]

    # Grab previous result for changelog
    prev = (
        db.query(Analysis)
        .filter(
            Analysis.repo_url == repo_url,
            Analysis.status == "completed",
            Analysis.result.isnot(None),
        )
        .order_by(Analysis.created_at.desc())
        .first()
    )
    previous_result = prev.result if prev else None

    analysis = Analysis(
        repo_url=repo_url,
        repo_name=first_watch.repo_name,
        status="pending",
        stage="Queued (auto — new commit detected)",
        user_id=analysis_user.id,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    # Collect all watcher user IDs for drift alerts after analysis completes
    all_watcher_ids = [wi["user"].id for wi in watcher_info if wi["user"]]

    # Fire analysis in a daemon thread
    from api.routes import _do_analysis

    t = threading.Thread(
        target=_do_analysis,
        args=(analysis.id, True, analysis_plan, github_token),
        kwargs={
            "previous_result": previous_result,
            "alert_user_ids": all_watcher_ids,
        },
        daemon=True,
    )
    t.start()

    # Send change-notification emails to all watchers who opted in
    for wi in watcher_info:
        user = wi["user"]
        if user and getattr(user, "notify_on_complete", False):
            analysis_url = f"{APP_URL}/analysis/{analysis.id}"
            send_repo_changed_email(user.email, first_watch.repo_name, analysis_url, latest_commit[:7])


_CLEANUP_INTERVAL = 3600  # run every hour
_UNVERIFIED_BAN_HOURS = 48  # ban unverified accounts after 48h


_MAX_ACCOUNTS_PER_IP = 5  # flag IPs with more free zero-analysis accounts than this
_IP_ABUSE_GRACE_HOURS = 24  # give new accounts 24h to run an analysis before flagging


def cleanup_fake_accounts() -> None:
    """Auto-ban accounts that look fake or abandoned.

    Criteria:
    - Unverified email after 48 hours → ban (they had plenty of time)
    - Multiple free accounts from the same IP with zero analyses (after 24h grace) → ban
    - Already-banned accounts older than 30 days with no analyses → delete
    """
    from database import SessionLocal
    from datetime import timedelta
    from models import _utcnow, Analysis, User, WatchedRepo
    from sqlalchemy import func

    db = SessionLocal()
    try:
        now = _utcnow()
        cutoff = now - timedelta(hours=_UNVERIFIED_BAN_HOURS)

        # Ban unverified accounts older than 48h (skip admins)
        stale_unverified = (
            db.query(User)
            .filter(
                User.is_verified == False,  # noqa: E712
                User.is_banned == False,  # noqa: E712
                User.is_admin == False,  # noqa: E712
                User.created_at < cutoff,
            )
            .all()
        )
        for user in stale_unverified:
            user.is_banned = True
            user.token_invalidated_at = now
            logger.info("Auto-banned unverified account: %s (%s)", user.id, user.email)
        if stale_unverified:
            db.commit()

        # Detect same-IP multi-account abuse:
        # Only count free, non-admin, non-banned accounts older than 24h grace period
        ip_grace_cutoff = now - timedelta(hours=_IP_ABUSE_GRACE_HOURS)
        ip_counts = (
            db.query(User.signup_ip, func.count(User.id))
            .filter(
                User.signup_ip.isnot(None),
                User.signup_ip != "",
                User.plan == "free",
                User.is_admin == False,  # noqa: E712
                User.is_banned == False,  # noqa: E712
                User.created_at < ip_grace_cutoff,
            )
            .group_by(User.signup_ip)
            .having(func.count(User.id) > _MAX_ACCOUNTS_PER_IP)
            .all()
        )
        for suspicious_ip, count in ip_counts:
            # Only ban free accounts with zero analyses from this IP
            candidates = (
                db.query(User)
                .filter(
                    User.signup_ip == suspicious_ip,
                    User.plan == "free",
                    User.is_admin == False,  # noqa: E712
                    User.is_banned == False,  # noqa: E712
                    User.created_at < ip_grace_cutoff,
                )
                .all()
            )
            for user in candidates:
                analysis_count = db.query(Analysis).filter(Analysis.user_id == user.id).count()
                if analysis_count == 0:
                    user.is_banned = True
                    user.token_invalidated_at = now
                    logger.info(
                        "Auto-banned multi-account abuse: %s (%s) from IP %s (%d free accounts, 0 analyses)",
                        user.id, user.email, suspicious_ip, count,
                    )
            if candidates:
                db.commit()

        # Delete banned accounts older than 30 days with zero analyses
        delete_cutoff = now - timedelta(days=30)
        old_banned = (
            db.query(User)
            .filter(
                User.is_banned == True,  # noqa: E712
                User.is_admin == False,  # noqa: E712
                User.created_at < delete_cutoff,
            )
            .all()
        )
        for user in old_banned:
            analysis_count = db.query(Analysis).filter(Analysis.user_id == user.id).count()
            if analysis_count == 0:
                db.query(WatchedRepo).filter(WatchedRepo.user_id == user.id).delete()
                db.delete(user)
                logger.info("Auto-deleted old banned account with no analyses: %s (%s)", user.id, user.email)
        if old_banned:
            db.commit()

    except Exception as exc:
        logger.error("Account cleanup error: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def start_watcher() -> None:
    """Spawn the background watcher and account cleanup threads. Call once at app startup."""

    def _watcher_loop() -> None:
        # Short initial delay so the app finishes starting up before the first check
        time.sleep(60)
        last_benchmark_rebuild = 0
        while True:
            try:
                check_watched_repos()
            except Exception as exc:
                logger.error("Watcher loop unhandled error: %s", exc)

            # Daily benchmark rebuild (Feature 3)
            now_ts = time.time()
            if now_ts - last_benchmark_rebuild > 86400:  # 24 hours
                try:
                    from database import SessionLocal
                    from services.benchmark_service import rebuild_benchmarks
                    bdb = SessionLocal()
                    try:
                        rebuild_benchmarks(bdb)
                    finally:
                        bdb.close()
                    last_benchmark_rebuild = now_ts
                except Exception as exc:
                    logger.error("Benchmark rebuild error: %s", exc)

            time.sleep(WATCH_INTERVAL_SECONDS)

    def _cleanup_loop() -> None:
        time.sleep(120)  # initial delay
        while True:
            try:
                cleanup_fake_accounts()
            except Exception as exc:
                logger.error("Cleanup loop unhandled error: %s", exc)
            time.sleep(_CLEANUP_INTERVAL)

    t = threading.Thread(target=_watcher_loop, daemon=True, name="repo-watcher")
    t.start()
    logger.info("Repo watcher started (interval: %ds)", WATCH_INTERVAL_SECONDS)

    t2 = threading.Thread(target=_cleanup_loop, daemon=True, name="account-cleanup")
    t2.start()
    logger.info("Account cleanup started (interval: %ds)", _CLEANUP_INTERVAL)

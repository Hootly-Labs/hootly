"""README badge endpoint — returns SVG showing health grade."""
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Analysis
from services.rate_limiter import check_rate_limit_key
from services.client_ip import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter()

# Cache badge SVGs for 24h to avoid DB lookups on every README view
_badge_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 86400  # 24 hours

_GRADE_COLORS = {
    "A": "#22c55e",  # green
    "B": "#84cc16",  # lime
    "C": "#eab308",  # yellow
    "D": "#f97316",  # orange
    "F": "#ef4444",  # red
}


def _make_badge_svg(grade: str, repo_name: str) -> str:
    color = _GRADE_COLORS.get(grade, "#6b7280")
    label = "hootly"
    value = grade
    label_width = 52
    value_width = 32
    total_width = label_width + value_width

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{label}: {value}">
  <title>{label}: {value}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="11">
    <text aria-hidden="true" x="{label_width/2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_width/2}" y="14">{label}</text>
    <text aria-hidden="true" x="{label_width + value_width/2}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{label_width + value_width/2}" y="14">{value}</text>
  </g>
</svg>"""


def _make_unanalyzed_badge() -> str:
    label = "hootly"
    value = "N/A"
    label_width = 52
    value_width = 32
    total_width = label_width + value_width

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{label}: {value}">
  <title>{label}: not analyzed</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="#9ca3af"/>
    <rect width="{total_width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="11">
    <text aria-hidden="true" x="{label_width/2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_width/2}" y="14">{label}</text>
    <text aria-hidden="true" x="{label_width + value_width/2}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{label_width + value_width/2}" y="14">{value}</text>
  </g>
</svg>"""


@router.get("/badge/{owner}/{repo}")
def get_badge(owner: str, repo: str, request: Request):
    ip = get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"badge:{ip}", max_requests=120, window=60)
    if not allowed:
        return Response(content=_make_unanalyzed_badge(), media_type="image/svg+xml")

    cache_key = f"{owner}/{repo}"

    # Check cache
    if cache_key in _badge_cache:
        svg, cached_at = _badge_cache[cache_key]
        if time.time() - cached_at < _CACHE_TTL:
            return Response(
                content=svg,
                media_type="image/svg+xml",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "ETag": f'"{cache_key}-{int(cached_at)}"',
                },
            )

    # Look up most recent completed public analysis
    db = SessionLocal()
    try:
        repo_url = f"https://github.com/{owner}/{repo}"
        analysis = (
            db.query(Analysis)
            .filter(
                Analysis.repo_url == repo_url,
                Analysis.status == "completed",
                Analysis.is_public == True,  # noqa: E712
            )
            .order_by(Analysis.created_at.desc())
            .first()
        )

        if not analysis or not analysis.health_score:
            svg = _make_unanalyzed_badge()
        else:
            try:
                health = json.loads(analysis.health_score)
                grade = health.get("grade", "N/A")
                svg = _make_badge_svg(grade, cache_key)
            except Exception:
                svg = _make_unanalyzed_badge()

        _badge_cache[cache_key] = (svg, time.time())
    finally:
        db.close()

    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/repo/{owner}/{repo}")
def get_repo_analysis(owner: str, repo: str, request: Request):
    """Find the most recent completed public analysis for a repo."""
    ip = get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"repo_lookup:{ip}", max_requests=60, window=60)
    if not allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=429, content={"detail": f"Too many requests. Try again in {retry_after} seconds."})

    db = SessionLocal()
    try:
        repo_url = f"https://github.com/{owner}/{repo}"
        analysis = (
            db.query(Analysis)
            .filter(
                Analysis.repo_url == repo_url,
                Analysis.status == "completed",
                Analysis.is_public == True,  # noqa: E712
            )
            .order_by(Analysis.created_at.desc())
            .first()
        )

        if not analysis:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"detail": "No public analysis found for this repo"})

        result_dict = None
        if analysis.result:
            try:
                result_dict = json.loads(analysis.result)
            except Exception:
                pass

        health_dict = None
        if analysis.health_score:
            try:
                health_dict = json.loads(analysis.health_score)
            except Exception:
                pass

        return {
            "id": analysis.id,
            "repo_url": analysis.repo_url,
            "repo_name": analysis.repo_name,
            "status": analysis.status,
            "created_at": analysis.created_at.isoformat(),
            "commit_hash": analysis.commit_hash,
            "health_score": health_dict,
            "result": result_dict,
        }
    finally:
        db.close()

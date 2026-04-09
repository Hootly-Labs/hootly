"""Feature 5: Multi-Repo Intelligence — cross-repo dependencies and org health."""
import json
import logging
from collections import Counter

from sqlalchemy.orm import Session

from models import _utcnow, Analysis, CrossRepoDependency, TeamMember

logger = logging.getLogger(__name__)


def detect_cross_repo_deps(team_id: str, db: Session) -> list[CrossRepoDependency]:
    """Scan all team analyses for shared dependencies (npm/pip packages)."""
    # Get all team members
    members = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.accepted == True).all()  # noqa: E712
    user_ids = [m.user_id for m in members if m.user_id]

    if not user_ids:
        return []

    # Get all completed analyses for team members
    analyses = (
        db.query(Analysis)
        .filter(
            Analysis.user_id.in_(user_ids),
            Analysis.status == "completed",
            Analysis.result.isnot(None),
        )
        .order_by(Analysis.created_at.desc())
        .all()
    )

    # Get latest analysis per repo_url
    seen_repos: dict[str, Analysis] = {}
    for a in analyses:
        if a.repo_url not in seen_repos:
            seen_repos[a.repo_url] = a

    if len(seen_repos) < 2:
        return []

    # Extract dependencies per repo
    repo_deps: dict[str, dict[str, list[tuple[str, str | None]]]] = {}  # repo_url -> {dep_type -> [(name, version)]}
    for repo_url, analysis in seen_repos.items():
        try:
            result = json.loads(analysis.result)
        except Exception:
            continue

        deps = result.get("dependencies", {})
        runtime = deps.get("runtime", [])
        dev = deps.get("dev", [])

        # Determine dep type from tech stack
        arch = result.get("architecture", {})
        tech_stack = [t.lower() for t in arch.get("tech_stack", [])]
        languages = [l.lower() for l in arch.get("languages", [])]

        dep_type = "npm_package"
        if any("python" in l for l in languages):
            dep_type = "pip_package"

        parsed: list[tuple[str, str | None]] = []
        for dep in runtime + dev:
            # Parse "package@version" or "package==version" or just "package"
            name = dep.strip()
            version = None
            for sep in ["==", ">=", "<=", "~=", "^", "@"]:
                if sep in name:
                    parts = name.split(sep, 1)
                    name = parts[0].strip()
                    version = parts[1].strip() if len(parts) > 1 else None
                    break
            if name:
                parsed.append((name.lower(), version))

        repo_deps[repo_url] = {dep_type: parsed}

    # Find shared dependencies between repos
    # Clear existing cross-deps for this team's repos
    repo_urls = list(seen_repos.keys())
    db.query(CrossRepoDependency).filter(
        CrossRepoDependency.source_repo_url.in_(repo_urls)
    ).delete(synchronize_session=False)

    cross_deps: list[CrossRepoDependency] = []
    repo_list = list(repo_deps.items())
    for i, (source_url, source_deps) in enumerate(repo_list):
        for j, (target_url, target_deps) in enumerate(repo_list):
            if i >= j:
                continue
            for dep_type in source_deps:
                source_names = {name for name, _ in source_deps.get(dep_type, [])}
                target_names = {name for name, _ in target_deps.get(dep_type, [])}
                shared = source_names & target_names
                for name in shared:
                    src_ver = next((v for n, v in source_deps.get(dep_type, []) if n == name), None)
                    tgt_ver = next((v for n, v in target_deps.get(dep_type, []) if n == name), None)
                    cd = CrossRepoDependency(
                        source_repo_url=source_url,
                        target_repo_url=target_url,
                        dependency_type=dep_type,
                        dependency_name=name,
                        source_version=src_ver,
                        target_version=tgt_ver,
                    )
                    db.add(cd)
                    cross_deps.append(cd)

    if cross_deps:
        db.commit()
    return cross_deps


def get_org_health_dashboard(team_id: str, db: Session) -> dict:
    """Aggregate health scores across all team repos."""
    members = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.accepted == True).all()  # noqa: E712
    user_ids = [m.user_id for m in members if m.user_id]

    if not user_ids:
        return {"repos": [], "summary": {}}

    analyses = (
        db.query(Analysis)
        .filter(
            Analysis.user_id.in_(user_ids),
            Analysis.status == "completed",
            Analysis.health_score.isnot(None),
        )
        .order_by(Analysis.created_at.desc())
        .all()
    )

    # Latest analysis per repo
    seen: dict[str, Analysis] = {}
    for a in analyses:
        if a.repo_url not in seen:
            seen[a.repo_url] = a

    repos = []
    scores = []
    for repo_url, analysis in seen.items():
        try:
            health = json.loads(analysis.health_score)
        except Exception:
            continue

        repos.append({
            "repo_url": repo_url,
            "repo_name": analysis.repo_name,
            "overall_score": health.get("overall_score", 0),
            "grade": health.get("grade", "?"),
            "dimensions": health.get("dimensions", {}),
            "last_analyzed": analysis.created_at.isoformat(),
        })
        scores.append(health.get("overall_score", 0))

    # Sort by score ascending (worst first for "at risk" highlighting)
    repos.sort(key=lambda r: r["overall_score"])

    avg_score = int(sum(scores) / len(scores)) if scores else 0
    at_risk = [r for r in repos if r["overall_score"] < 60]

    return {
        "repos": repos,
        "summary": {
            "total_repos": len(repos),
            "avg_score": avg_score,
            "at_risk_count": len(at_risk),
        },
    }


def find_shared_patterns(team_id: str, db: Session) -> dict:
    """Identify common frameworks, testing patterns, code organization across repos."""
    members = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.accepted == True).all()  # noqa: E712
    user_ids = [m.user_id for m in members if m.user_id]

    if not user_ids:
        return {"patterns": [], "tech_stack": {}, "languages": {}}

    analyses = (
        db.query(Analysis)
        .filter(Analysis.user_id.in_(user_ids), Analysis.status == "completed", Analysis.result.isnot(None))
        .order_by(Analysis.created_at.desc())
        .all()
    )

    seen: dict[str, Analysis] = {}
    for a in analyses:
        if a.repo_url not in seen:
            seen[a.repo_url] = a

    tech_counter: Counter = Counter()
    lang_counter: Counter = Counter()
    pattern_counter: Counter = Counter()

    for analysis in seen.values():
        try:
            result = json.loads(analysis.result)
        except Exception:
            continue

        arch = result.get("architecture", {})
        for tech in arch.get("tech_stack", []):
            tech_counter[tech] += 1
        for lang in arch.get("languages", []):
            lang_counter[lang] += 1
        for pat in result.get("patterns", []):
            pattern_counter[pat.get("name", "")] += 1

    return {
        "tech_stack": dict(tech_counter.most_common(20)),
        "languages": dict(lang_counter.most_common(10)),
        "patterns": [
            {"name": name, "count": count}
            for name, count in pattern_counter.most_common(10)
        ],
        "total_repos": len(seen),
    }

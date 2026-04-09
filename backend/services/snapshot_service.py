"""Feature 1: Continuous Repo Intelligence — snapshot creation and drift detection."""
import hashlib
import json
import logging

from models import _utcnow, Analysis, DriftAlert, RepoSnapshot

logger = logging.getLogger(__name__)


def create_snapshot(analysis: Analysis, db) -> RepoSnapshot | None:
    """Extract a snapshot from a completed analysis and store it."""
    if analysis.status != "completed" or not analysis.result:
        return None

    # Skip if a snapshot already exists for this repo + commit
    if analysis.commit_hash:
        existing = (
            db.query(RepoSnapshot)
            .filter(
                RepoSnapshot.repo_url == analysis.repo_url,
                RepoSnapshot.commit_hash == analysis.commit_hash,
            )
            .first()
        )
        if existing:
            return existing

    try:
        result = json.loads(analysis.result)
    except Exception:
        return None

    arch = result.get("architecture", {})
    health = None
    if analysis.health_score:
        try:
            health = json.loads(analysis.health_score)
        except Exception:
            pass

    # Hash the architecture summary for change detection
    arch_str = json.dumps({
        "architecture_type": arch.get("architecture_type", ""),
        "architecture_summary": arch.get("architecture_summary", ""),
    }, sort_keys=True)
    arch_hash = hashlib.sha256(arch_str.encode()).hexdigest()[:16]

    key_files = [
        {"path": f.get("path", ""), "score": f.get("score", 0)}
        for f in result.get("key_files", [])[:20]
    ]

    snapshot = RepoSnapshot(
        analysis_id=analysis.id,
        repo_url=analysis.repo_url,
        commit_hash=analysis.commit_hash,
        architecture_hash=arch_hash,
        tech_stack=json.dumps(arch.get("tech_stack", [])),
        entry_points=json.dumps(arch.get("entry_points", [])),
        file_count=len(result.get("file_tree", [])),
        health_score=json.dumps(health) if health else None,
        key_files=json.dumps(key_files),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def compare_snapshots(old: RepoSnapshot, new: RepoSnapshot) -> list[dict]:
    """Compare two snapshots and return a list of drift descriptions."""
    drifts = []

    # Health score drop
    old_health = _parse_json(old.health_score)
    new_health = _parse_json(new.health_score)
    if old_health and new_health:
        old_grade = old_health.get("grade", "")
        new_grade = new_health.get("grade", "")
        grade_order = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
        if grade_order.get(new_grade, 0) < grade_order.get(old_grade, 0):
            drifts.append({
                "alert_type": "health_drop",
                "severity": "warning" if grade_order.get(old_grade, 0) - grade_order.get(new_grade, 0) >= 2 else "info",
                "message": f"Health grade dropped from {old_grade} to {new_grade}",
                "details": {"old_grade": old_grade, "new_grade": new_grade,
                            "old_score": old_health.get("overall_score"), "new_score": new_health.get("overall_score")},
            })

    # Tech stack changes
    old_stack = set(_parse_json(old.tech_stack) or [])
    new_stack = set(_parse_json(new.tech_stack) or [])
    added_tech = new_stack - old_stack
    removed_tech = old_stack - new_stack
    if added_tech:
        drifts.append({
            "alert_type": "tech_stack_change",
            "severity": "info",
            "message": f"New technologies added: {', '.join(sorted(added_tech))}",
            "details": {"added": sorted(added_tech)},
        })
    if removed_tech:
        drifts.append({
            "alert_type": "tech_stack_change",
            "severity": "warning",
            "message": f"Technologies removed: {', '.join(sorted(removed_tech))}",
            "details": {"removed": sorted(removed_tech)},
        })

    # Entry point changes
    old_entries = set(_parse_json(old.entry_points) or [])
    new_entries = set(_parse_json(new.entry_points) or [])
    removed_entries = old_entries - new_entries
    if removed_entries:
        drifts.append({
            "alert_type": "removed_entry_point",
            "severity": "warning",
            "message": f"Entry points removed: {', '.join(sorted(removed_entries))}",
            "details": {"removed": sorted(removed_entries)},
        })

    # Architecture hash change
    if old.architecture_hash and new.architecture_hash and old.architecture_hash != new.architecture_hash:
        drifts.append({
            "alert_type": "architecture_change",
            "severity": "info",
            "message": "Architecture description has changed significantly",
            "details": {},
        })

    # File count change >20%
    if old.file_count > 0:
        change_pct = abs(new.file_count - old.file_count) / old.file_count
        if change_pct > 0.2:
            direction = "increased" if new.file_count > old.file_count else "decreased"
            drifts.append({
                "alert_type": "architecture_change",
                "severity": "info",
                "message": f"File count {direction} by {change_pct:.0%} ({old.file_count} → {new.file_count})",
                "details": {"old_count": old.file_count, "new_count": new.file_count},
            })

    return drifts


def generate_drift_alerts(user_id: str | list[str], repo_url: str, old_snapshot: RepoSnapshot, new_snapshot: RepoSnapshot, db) -> list[DriftAlert]:
    """Compare snapshots and create DriftAlert rows for any detected drift.

    user_id can be a single ID or a list of IDs (for shared watched repos).
    """
    drifts = compare_snapshots(old_snapshot, new_snapshot)
    if not drifts:
        return []

    user_ids = [user_id] if isinstance(user_id, str) else user_id

    alerts = []
    for uid in user_ids:
        for drift in drifts:
            alert = DriftAlert(
                user_id=uid,
                repo_url=repo_url,
                alert_type=drift["alert_type"],
                severity=drift["severity"],
                message=drift["message"],
                details=json.dumps(drift.get("details", {})),
            )
            db.add(alert)
            alerts.append(alert)
    if alerts:
        db.commit()
    return alerts


def _parse_json(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None

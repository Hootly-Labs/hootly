"""Feature 4: Tribal Knowledge — annotations, ADRs, and expertise maps."""
import json
import logging
from typing import Literal

from sqlalchemy.orm import Session

from models import _utcnow, Annotation, ArchitectureDecisionRecord, ExpertiseMap

logger = logging.getLogger(__name__)


# ── Annotations ──────────────────────────────────────────────────────────────

def create_annotation(
    analysis_id: str,
    user_id: str,
    file_path: str,
    content: str,
    annotation_type: str = "note",
    line_start: int | None = None,
    line_end: int | None = None,
    db: Session = None,
) -> Annotation:
    ann = Annotation(
        analysis_id=analysis_id,
        user_id=user_id,
        file_path=file_path,
        content=content,
        annotation_type=annotation_type,
        line_start=line_start,
        line_end=line_end,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann


def get_annotations(analysis_id: str, db: Session, file_path: str | None = None) -> list[Annotation]:
    q = db.query(Annotation).filter(Annotation.analysis_id == analysis_id)
    if file_path:
        q = q.filter(Annotation.file_path == file_path)
    return q.order_by(Annotation.created_at.desc()).all()


def update_annotation(annotation_id: str, user_id: str, content: str, db: Session) -> Annotation | None:
    ann = db.query(Annotation).filter(Annotation.id == annotation_id, Annotation.user_id == user_id).first()
    if not ann:
        return None
    ann.content = content
    ann.updated_at = _utcnow()
    db.commit()
    return ann


def delete_annotation(annotation_id: str, user_id: str, db: Session) -> bool:
    ann = db.query(Annotation).filter(Annotation.id == annotation_id, Annotation.user_id == user_id).first()
    if not ann:
        return False
    db.delete(ann)
    db.commit()
    return True


# ── Architecture Decision Records ────────────────────────────────────────────

def create_adr(
    user_id: str,
    repo_url: str,
    title: str,
    context: str,
    decision: str,
    consequences: str,
    team_id: str | None = None,
    db: Session = None,
) -> ArchitectureDecisionRecord:
    adr = ArchitectureDecisionRecord(
        user_id=user_id,
        repo_url=repo_url,
        title=title,
        context=context,
        decision=decision,
        consequences=consequences,
        team_id=team_id,
    )
    db.add(adr)
    db.commit()
    db.refresh(adr)
    return adr


def get_adrs(repo_url: str | None = None, team_id: str | None = None, user_id: str | None = None, db: Session = None) -> list[ArchitectureDecisionRecord]:
    q = db.query(ArchitectureDecisionRecord)
    if repo_url:
        q = q.filter(ArchitectureDecisionRecord.repo_url == repo_url)
    if team_id:
        q = q.filter(ArchitectureDecisionRecord.team_id == team_id)
    if user_id:
        q = q.filter(ArchitectureDecisionRecord.user_id == user_id)
    return q.order_by(ArchitectureDecisionRecord.created_at.desc()).all()


def update_adr(
    adr_id: str,
    user_id: str,
    db: Session,
    title: str | None = None,
    status: str | None = None,
    context: str | None = None,
    decision: str | None = None,
    consequences: str | None = None,
    superseded_by: str | None = None,
) -> ArchitectureDecisionRecord | None:
    adr = db.query(ArchitectureDecisionRecord).filter(
        ArchitectureDecisionRecord.id == adr_id,
        ArchitectureDecisionRecord.user_id == user_id,
    ).first()
    if not adr:
        return None
    if title is not None:
        adr.title = title
    if status is not None:
        adr.status = status
    if context is not None:
        adr.context = context
    if decision is not None:
        adr.decision = decision
    if consequences is not None:
        adr.consequences = consequences
    if superseded_by is not None:
        adr.superseded_by = superseded_by
    adr.updated_at = _utcnow()
    db.commit()
    return adr


def delete_adr(adr_id: str, user_id: str, db: Session) -> bool:
    adr = db.query(ArchitectureDecisionRecord).filter(
        ArchitectureDecisionRecord.id == adr_id,
        ArchitectureDecisionRecord.user_id == user_id,
    ).first()
    if not adr:
        return False
    db.delete(adr)
    db.commit()
    return True


# ── Expertise Map ────────────────────────────────────────────────────────────

def get_expertise(analysis_id: str, repo_url: str, db: Session) -> list[ExpertiseMap]:
    return (
        db.query(ExpertiseMap)
        .filter(ExpertiseMap.repo_url == repo_url)
        .order_by(ExpertiseMap.file_path)
        .all()
    )


def set_expertise(
    user_id: str,
    repo_url: str,
    file_path: str,
    expertise_level: str,
    db: Session,
    auto_detected: bool = False,
) -> ExpertiseMap:
    existing = (
        db.query(ExpertiseMap)
        .filter(ExpertiseMap.user_id == user_id, ExpertiseMap.repo_url == repo_url, ExpertiseMap.file_path == file_path)
        .first()
    )
    if existing:
        existing.expertise_level = expertise_level
        existing.last_touched_at = _utcnow()
        existing.auto_detected = auto_detected
        db.commit()
        return existing

    em = ExpertiseMap(
        user_id=user_id,
        repo_url=repo_url,
        file_path=file_path,
        expertise_level=expertise_level,
        auto_detected=auto_detected,
        last_touched_at=_utcnow(),
    )
    db.add(em)
    db.commit()
    db.refresh(em)
    return em


def get_file_knowledge(analysis_id: str, file_path: str, repo_url: str, db: Session) -> dict:
    """Aggregate annotations + ADRs + expertise for a file."""
    annotations = get_annotations(analysis_id, db, file_path=file_path)
    adrs = get_adrs(repo_url=repo_url, db=db)
    expertise = (
        db.query(ExpertiseMap)
        .filter(ExpertiseMap.repo_url == repo_url, ExpertiseMap.file_path == file_path)
        .all()
    )

    return {
        "file_path": file_path,
        "annotations": [
            {
                "id": a.id,
                "content": a.content,
                "type": a.annotation_type,
                "line_start": a.line_start,
                "line_end": a.line_end,
                "created_at": a.created_at.isoformat(),
            }
            for a in annotations
        ],
        "adrs": [
            {
                "id": adr.id,
                "title": adr.title,
                "status": adr.status,
                "decision": adr.decision[:200],
            }
            for adr in adrs
        ],
        "expertise": [
            {
                "user_id": e.user_id,
                "level": e.expertise_level,
                "auto_detected": e.auto_detected,
            }
            for e in expertise
        ],
    }

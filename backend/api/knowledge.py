"""Feature 4: Tribal Knowledge — annotations, ADRs, expertise endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Analysis, User
from services.auth_service import get_current_user
from services.knowledge_service import (
    create_annotation, get_annotations, update_annotation, delete_annotation,
    create_adr, get_adrs, update_adr, delete_adr,
    get_expertise, set_expertise, get_file_knowledge,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Annotation models ────────────────────────────────────────────────────────

class CreateAnnotationRequest(BaseModel):
    file_path: str
    content: str
    annotation_type: str = "note"
    line_start: int | None = None
    line_end: int | None = None


class UpdateAnnotationRequest(BaseModel):
    content: str


# ── ADR models ───────────────────────────────────────────────────────────────

class CreateADRRequest(BaseModel):
    repo_url: str
    title: str
    context: str
    decision: str
    consequences: str
    team_id: str | None = None


class UpdateADRRequest(BaseModel):
    title: str | None = None
    status: str | None = None
    context: str | None = None
    decision: str | None = None
    consequences: str | None = None
    superseded_by: str | None = None


# ── Expertise models ─────────────────────────────────────────────────────────

class SetExpertiseRequest(BaseModel):
    file_path: str
    expertise_level: str  # author | reviewer | familiar | none


# ── Annotation endpoints ─────────────────────────────────────────────────────

@router.post("/analysis/{analysis_id}/annotations")
def add_annotation(
    analysis_id: str,
    req: CreateAnnotationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")

    ann = create_annotation(
        analysis_id=analysis_id,
        user_id=current_user.id,
        file_path=req.file_path,
        content=req.content,
        annotation_type=req.annotation_type,
        line_start=req.line_start,
        line_end=req.line_end,
        db=db,
    )
    return _ann_to_dict(ann)


@router.get("/analysis/{analysis_id}/annotations")
def list_annotations(
    analysis_id: str,
    file_path: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    annotations = get_annotations(analysis_id, db, file_path=file_path)
    return [_ann_to_dict(a) for a in annotations]


@router.patch("/annotations/{annotation_id}")
def edit_annotation(
    annotation_id: str,
    req: UpdateAnnotationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ann = update_annotation(annotation_id, current_user.id, req.content, db)
    if not ann:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return _ann_to_dict(ann)


@router.delete("/annotations/{annotation_id}")
def remove_annotation(
    annotation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not delete_annotation(annotation_id, current_user.id, db):
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"ok": True}


# ── ADR endpoints ────────────────────────────────────────────────────────────

@router.post("/adrs")
def add_adr(
    req: CreateADRRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    adr = create_adr(
        user_id=current_user.id,
        repo_url=req.repo_url,
        title=req.title,
        context=req.context,
        decision=req.decision,
        consequences=req.consequences,
        team_id=req.team_id,
        db=db,
    )
    return _adr_to_dict(adr)


@router.get("/adrs")
def list_adrs(
    repo_url: str | None = None,
    team_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    adrs = get_adrs(repo_url=repo_url, team_id=team_id, user_id=current_user.id, db=db)
    return [_adr_to_dict(a) for a in adrs]


@router.patch("/adrs/{adr_id}")
def edit_adr(
    adr_id: str,
    req: UpdateADRRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    adr = update_adr(
        adr_id, current_user.id, db,
        title=req.title, status=req.status, context=req.context,
        decision=req.decision, consequences=req.consequences,
        superseded_by=req.superseded_by,
    )
    if not adr:
        raise HTTPException(status_code=404, detail="ADR not found")
    return _adr_to_dict(adr)


@router.delete("/adrs/{adr_id}")
def remove_adr(
    adr_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not delete_adr(adr_id, current_user.id, db):
        raise HTTPException(status_code=404, detail="ADR not found")
    return {"ok": True}


# ── Expertise endpoints ──────────────────────────────────────────────────────

@router.get("/analysis/{analysis_id}/expertise")
def list_expertise(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    expertise = get_expertise(analysis_id, analysis.repo_url, db)
    return [_expertise_to_dict(e) for e in expertise]


@router.post("/analysis/{analysis_id}/expertise")
def add_expertise(
    analysis_id: str,
    req: SetExpertiseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    em = set_expertise(
        user_id=current_user.id,
        repo_url=analysis.repo_url,
        file_path=req.file_path,
        expertise_level=req.expertise_level,
        db=db,
    )
    return _expertise_to_dict(em)


@router.get("/analysis/{analysis_id}/file-knowledge/{file_path:path}")
def file_knowledge(
    analysis_id: str,
    file_path: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return get_file_knowledge(analysis_id, file_path, analysis.repo_url, db)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ann_to_dict(a) -> dict:
    return {
        "id": a.id,
        "analysis_id": a.analysis_id,
        "user_id": a.user_id,
        "file_path": a.file_path,
        "content": a.content,
        "annotation_type": a.annotation_type,
        "line_start": a.line_start,
        "line_end": a.line_end,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def _adr_to_dict(a) -> dict:
    return {
        "id": a.id,
        "user_id": a.user_id,
        "repo_url": a.repo_url,
        "title": a.title,
        "status": a.status,
        "context": a.context,
        "decision": a.decision,
        "consequences": a.consequences,
        "team_id": a.team_id,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        "superseded_by": a.superseded_by,
    }


def _expertise_to_dict(e) -> dict:
    return {
        "id": e.id,
        "user_id": e.user_id,
        "repo_url": e.repo_url,
        "file_path": e.file_path,
        "expertise_level": e.expertise_level,
        "auto_detected": e.auto_detected,
        "last_touched_at": e.last_touched_at.isoformat() if e.last_touched_at else None,
    }

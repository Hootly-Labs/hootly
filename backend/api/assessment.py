"""Assessment report endpoints — premium deep analysis."""
import json
import logging
import os
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models import Analysis, Assessment, User, _utcnow
from services.auth_service import get_current_user

try:
    import stripe as _stripe_module
    stripe = _stripe_module
except ImportError:
    stripe = None  # type: ignore

logger = logging.getLogger(__name__)

router = APIRouter()

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_ASSESSMENT_BASIC_PRICE = os.getenv("STRIPE_ASSESSMENT_BASIC_PRICE", "")
STRIPE_ASSESSMENT_FULL_PRICE = os.getenv("STRIPE_ASSESSMENT_FULL_PRICE", "")
APP_URL = os.getenv("APP_URL", "http://localhost:3000")

if stripe and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


class AssessmentRequest(BaseModel):
    tier: str = "basic"  # "basic" ($99) or "full" ($499)


class AssessmentCheckoutRequest(BaseModel):
    tier: str = "basic"


@router.post("/assessment/{analysis_id}/checkout")
def create_assessment_checkout(
    analysis_id: str,
    req: AssessmentCheckoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a Stripe Checkout session for a one-time assessment purchase."""
    if not stripe or not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing is not configured.")

    if req.tier not in ("basic", "full"):
        raise HTTPException(status_code=400, detail="Invalid tier. Use 'basic' or 'full'.")

    price_id = STRIPE_ASSESSMENT_BASIC_PRICE if req.tier == "basic" else STRIPE_ASSESSMENT_FULL_PRICE
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Assessment pricing not configured for tier '{req.tier}'.")

    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if not current_user.is_admin and analysis.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.status != "completed" or not analysis.result:
        raise HTTPException(status_code=400, detail="Analysis must be completed first")

    # Reuse or create Stripe customer
    customer_id = getattr(current_user, "stripe_customer_id", None)
    if not customer_id:
        customer = stripe.Customer.create(email=current_user.email, metadata={"user_id": current_user.id})
        customer_id = customer.id
        current_user.stripe_customer_id = customer_id
        db.commit()

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="payment",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{APP_URL}/analysis/{analysis_id}?assessment=purchased",
        cancel_url=f"{APP_URL}/analysis/{analysis_id}",
        metadata={
            "type": "assessment",
            "analysis_id": analysis_id,
            "user_id": current_user.id,
            "tier": req.tier,
        },
    )
    return {"url": session.url}


@router.post("/assessment/{analysis_id}")
def create_assessment(
    analysis_id: str,
    req: AssessmentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if req.tier not in ("basic", "full"):
        raise HTTPException(status_code=400, detail="Invalid tier. Use 'basic' or 'full'.")

    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if not current_user.is_admin and analysis.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.status != "completed" or not analysis.result:
        raise HTTPException(status_code=400, detail="Analysis must be completed first")

    # Check if assessment already exists
    existing = (
        db.query(Assessment)
        .filter(
            Assessment.analysis_id == analysis_id,
            Assessment.tier == req.tier,
            Assessment.status == "completed",
        )
        .first()
    )
    if existing:
        result = json.loads(existing.result) if existing.result else None
        return {
            "id": existing.id,
            "status": existing.status,
            "tier": existing.tier,
            "result": result,
            "created_at": existing.created_at.isoformat(),
        }

    # Pro plan, admin, or paid assessment (check for paid assessment record)
    has_paid = (
        db.query(Assessment)
        .filter(
            Assessment.analysis_id == analysis_id,
            Assessment.user_id == current_user.id,
            Assessment.tier == req.tier,
            Assessment.status == "paid",
        )
        .first()
    )

    if not has_paid and current_user.plan != "pro" and not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Assessment reports require a Pro plan or one-time purchase.",
        )

    # If there's a paid record, update it to processing; otherwise create new
    if has_paid:
        assessment = has_paid
        assessment.status = "processing"
        db.commit()
    else:
        assessment = Assessment(
            analysis_id=analysis_id,
            user_id=current_user.id,
            tier=req.tier,
            status="processing",
        )
        db.add(assessment)
        db.commit()
        db.refresh(assessment)

    # Run in background
    t = threading.Thread(
        target=_generate_assessment_bg,
        args=(assessment.id, analysis_id, req.tier),
        daemon=True,
    )
    t.start()

    return {
        "id": assessment.id,
        "status": "processing",
        "tier": req.tier,
    }


@router.get("/assessment/{analysis_id}")
def get_assessment(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if not current_user.is_admin and analysis.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")

    assessment = (
        db.query(Assessment)
        .filter(Assessment.analysis_id == analysis_id)
        .order_by(Assessment.created_at.desc())
        .first()
    )
    if not assessment:
        return {"status": "none"}

    result = None
    if assessment.result:
        try:
            result = json.loads(assessment.result)
        except Exception:
            pass

    return {
        "id": assessment.id,
        "status": assessment.status,
        "tier": assessment.tier,
        "result": result,
        "created_at": assessment.created_at.isoformat(),
    }


def _generate_assessment_bg(assessment_id: str, analysis_id: str, tier: str):
    """Background task to generate assessment report."""
    from services.assessment_service import generate_assessment

    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
        if not analysis or not assessment:
            return

        analysis_result = json.loads(analysis.result)
        health_score = json.loads(analysis.health_score) if analysis.health_score else {}

        result = generate_assessment(analysis_result, health_score, tier)

        assessment.result = json.dumps(result)
        assessment.status = "completed"
        db.commit()
        logger.info("Assessment completed: %s (tier=%s)", assessment_id, tier)

    except Exception as exc:
        logger.exception("Assessment generation failed: %s", exc)
        assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
        if assessment:
            assessment.status = "failed"
            db.commit()
    finally:
        db.close()

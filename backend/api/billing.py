"""Stripe billing endpoints: checkout, portal, webhook, and usage."""
import logging
import os

try:
    import stripe as _stripe_module
    stripe = _stripe_module
except ImportError:
    stripe = None  # type: ignore

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from pydantic import BaseModel

from database import get_db
from models import ACTIVE_ANALYSIS_STATUSES, _utcnow, Analysis, Team, TeamMember, User
from services.auth_service import get_current_user
from services.client_ip import get_client_ip as _get_client_ip
from services.rate_limiter import check_rate_limit_key

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRO_PRICE_ID = os.getenv("STRIPE_PRO_PRICE_ID", "")
STRIPE_TEAM_PRICE_ID = os.getenv("STRIPE_TEAM_PRICE_ID", "")
APP_URL = os.getenv("APP_URL", "http://localhost:3000")

_FREE_PLAN_MONTHLY_LIMIT = 1

logger = logging.getLogger(__name__)

router = APIRouter()

if stripe and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def _stripe_configured() -> bool:
    return bool(stripe and STRIPE_SECRET_KEY and STRIPE_PRO_PRICE_ID)


# ── Usage ─────────────────────────────────────────────────────────────────────

@router.get("/billing/usage")
def get_usage(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"billing:{ip}", max_requests=30, window=60)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many requests. Try again in {retry_after} seconds.")
    now = _utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count = (
        db.query(Analysis)
        .filter(
            Analysis.user_id == current_user.id,
            Analysis.created_at >= month_start,
            Analysis.status.in_(ACTIVE_ANALYSIS_STATUSES),
        )
        .count()
    )
    limit = _FREE_PLAN_MONTHLY_LIMIT if current_user.plan == "free" else None
    return {
        "analyses_this_month": count,
        "limit": limit,
        "plan": current_user.plan,
    }


# ── Checkout ──────────────────────────────────────────────────────────────────

@router.post("/billing/checkout")
def create_checkout(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _stripe_configured():
        raise HTTPException(status_code=503, detail="Billing is not configured.")

    # Reuse or create Stripe customer
    customer_id = getattr(current_user, "stripe_customer_id", None)
    if not customer_id:
        customer = stripe.Customer.create(email=current_user.email, metadata={"user_id": current_user.id})
        customer_id = customer.id
        current_user.stripe_customer_id = customer_id
        db.commit()

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": STRIPE_PRO_PRICE_ID, "quantity": 1}],
        success_url=f"{APP_URL}/billing/success",
        cancel_url=APP_URL,
    )
    return {"url": session.url}


# ── Billing Portal ────────────────────────────────────────────────────────────

@router.post("/billing/portal")
def create_portal(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _stripe_configured():
        raise HTTPException(status_code=503, detail="Billing is not configured.")

    customer_id = getattr(current_user, "stripe_customer_id", None)
    if not customer_id:
        raise HTTPException(status_code=400, detail="No billing account found. Please subscribe first.")

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=APP_URL,
    )
    return {"url": session.url}


# ── Team Checkout ─────────────────────────────────────────────────────────

class TeamCheckoutRequest(BaseModel):
    team_id: str


@router.post("/billing/team-checkout")
def create_team_checkout(
    req: TeamCheckoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not stripe or not STRIPE_SECRET_KEY or not STRIPE_TEAM_PRICE_ID:
        raise HTTPException(status_code=503, detail="Team billing is not configured.")

    team = db.query(Team).filter(Team.id == req.team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the team owner can manage billing")

    if team.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="Team already has an active subscription. Use the billing portal to manage it.")

    # Count accepted members for seat quantity
    seat_count = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team.id, TeamMember.accepted == True)
        .count()
    )
    seat_count = max(seat_count, 1)

    # Reuse or create Stripe customer
    customer_id = getattr(current_user, "stripe_customer_id", None)
    if not customer_id:
        customer = stripe.Customer.create(email=current_user.email, metadata={"user_id": current_user.id})
        customer_id = customer.id
        current_user.stripe_customer_id = customer_id
        db.commit()

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": STRIPE_TEAM_PRICE_ID, "quantity": seat_count}],
        success_url=f"{APP_URL}/team?billing=success",
        cancel_url=f"{APP_URL}/team",
        metadata={"type": "team", "team_id": team.id, "user_id": current_user.id},
    )
    return {"url": session.url}


# ── Webhook ───────────────────────────────────────────────────────────────────

@router.post("/billing/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe sends raw bytes — must NOT parse body as JSON before verifying signature."""
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret not configured.")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")
    except Exception as exc:
        logger.warning("Stripe webhook parse error: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")

    event_type = event["type"]
    data_obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data_obj, db)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data_obj, db)
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(data_obj, db)
    else:
        logger.debug("Unhandled Stripe event: %s", event_type)

    return {"received": True}


def _handle_checkout_completed(session: dict, db: Session) -> None:
    metadata = session.get("metadata", {})

    # One-time assessment purchase
    if metadata.get("type") == "assessment":
        _handle_assessment_payment(metadata, db)
        return

    # Team subscription
    if metadata.get("type") == "team":
        _handle_team_subscription(metadata, session, db)
        return

    # Personal Pro subscription checkout
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    # Sanity-check Stripe ID formats before querying
    if not customer_id or not str(customer_id).startswith("cus_"):
        logger.warning("checkout.session.completed: unexpected customer_id format: %s", customer_id)
        return
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not user:
        logger.warning("checkout.session.completed: no user for customer %s", customer_id)
        return
    user.plan = "pro"
    user.stripe_subscription_id = subscription_id
    db.commit()
    logger.info("User %s upgraded to pro (subscription %s)", user.id, subscription_id)


def _handle_assessment_payment(metadata: dict, db: Session) -> None:
    """Handle a completed one-time assessment purchase."""
    from models import Assessment

    analysis_id = metadata.get("analysis_id")
    user_id = metadata.get("user_id")
    tier = metadata.get("tier", "basic")

    if not analysis_id or not user_id:
        logger.warning("assessment payment missing metadata: %s", metadata)
        return

    # Create a "paid" assessment record — user can then trigger generation
    assessment = Assessment(
        analysis_id=analysis_id,
        user_id=user_id,
        tier=tier,
        status="paid",
    )
    db.add(assessment)
    db.commit()
    logger.info("Assessment paid: analysis=%s user=%s tier=%s", analysis_id, user_id, tier)

    # Auto-trigger generation
    import threading
    from api.assessment import _generate_assessment_bg
    assessment_id = assessment.id
    t = threading.Thread(
        target=_generate_assessment_bg,
        args=(assessment_id, analysis_id, tier),
        daemon=True,
    )
    t.start()


def _handle_team_subscription(metadata: dict, session: dict, db: Session) -> None:
    """Handle a completed team subscription checkout."""
    team_id = metadata.get("team_id")
    subscription_id = session.get("subscription")

    if not team_id:
        logger.warning("team subscription missing team_id: %s", metadata)
        return

    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        logger.warning("team subscription: team %s not found", team_id)
        return

    team.stripe_subscription_id = subscription_id
    # Upgrade all accepted team members to pro
    members = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.accepted == True)
        .all()
    )
    for m in members:
        if m.user_id:
            user = db.query(User).filter(User.id == m.user_id).first()
            if user and user.plan != "pro":
                user.plan = "pro"
    db.commit()
    logger.info("Team %s subscribed (subscription %s), %d members upgraded", team_id, subscription_id, len(members))


def _handle_subscription_deleted(subscription: dict, db: Session) -> None:
    subscription_id = subscription.get("id")
    customer_id = subscription.get("customer")

    # Check if this is a team subscription
    team = db.query(Team).filter(Team.stripe_subscription_id == subscription_id).first()
    if team:
        team.stripe_subscription_id = None
        # Downgrade team members who don't have their own personal subscription
        members = (
            db.query(TeamMember)
            .filter(TeamMember.team_id == team.id, TeamMember.accepted == True)
            .all()
        )
        for m in members:
            if m.user_id:
                user = db.query(User).filter(User.id == m.user_id).first()
                if user and user.plan == "pro" and not user.stripe_subscription_id:
                    user.plan = "free"
        db.commit()
        logger.info("Team %s subscription cancelled, members downgraded", team.id)
        return

    # Personal subscription
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not user:
        logger.warning("subscription.deleted: no user for customer %s", customer_id)
        return
    user.plan = "free"
    user.stripe_subscription_id = None
    db.commit()
    logger.info("User %s downgraded to free (subscription %s cancelled)", user.id, subscription_id)


def _handle_payment_failed(invoice: dict, db: Session) -> None:
    customer_id = invoice.get("customer")
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not user:
        return
    user.plan = "free"
    db.commit()
    logger.info("User %s downgraded to free (payment failed)", user.id)

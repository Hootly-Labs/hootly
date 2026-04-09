import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

_logger = logging.getLogger(__name__)

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")  # required when registering as admin
APP_URL = os.getenv("APP_URL", "http://localhost:3000")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")

# ── Validation helpers ────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')

# Disposable / temporary email domains — block signups from throwaway services.
# This is not exhaustive but covers the most common ones.
_DISPOSABLE_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "tempmail.com", "temp-mail.org", "temp-mail.io", "tempail.com",
    "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
    "guerrillamail.de", "grr.la", "guerrillamailblock.com",
    "mailinator.com", "mailinator.net", "mailinator2.com",
    "maildrop.cc", "maildrop.io",
    "yopmail.com", "yopmail.fr", "yopmail.net",
    "throwaway.email", "throwaway.com",
    "10minutemail.com", "10minutemail.net", "10minemail.com",
    "minutemail.com",
    "trashmail.com", "trashmail.me", "trashmail.net", "trashmail.org",
    "dispostable.com", "disposableemailaddresses.emailmiser.com",
    "mailnesia.com", "mailnull.com", "mailcatch.com",
    "sharklasers.com", "guerrillamail.info", "spam4.me",
    "bugmenot.com", "discard.email", "discardmail.com",
    "fakeinbox.com", "fakemail.net", "mailexpire.com",
    "tempinbox.com", "tempr.email", "tempmailaddress.com",
    "tmpmail.net", "tmpmail.org", "emailondeck.com",
    "getnada.com", "nada.email", "mailsac.com",
    "mohmal.com", "burnermail.io", "inboxkitten.com",
    "harakirimail.com", "crazymailing.com", "tmail.ws",
    "mailtemp.net", "emailfake.com", "tempmailo.com",
    "tempmails.net", "receivemail.com", "tempemailco.com",
    "mailnator.com", "mytemp.email", "internxt.com",
    "ethereal.email",
    "csula.com",
})


def _is_disposable_email(email: str) -> bool:
    """Check if the email domain is a known disposable/temporary email service."""
    domain = email.rsplit("@", 1)[-1].lower()
    # Check exact match and one level of subdomain (e.g. mail.guerrillamail.com)
    if domain in _DISPOSABLE_EMAIL_DOMAINS:
        return True
    parts = domain.split(".")
    if len(parts) > 2:
        parent = ".".join(parts[-2:])
        if parent in _DISPOSABLE_EMAIL_DOMAINS:
            return True
    return False


def _validate_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    if len(email) > 254:  # RFC 5321 max
        raise HTTPException(status_code=400, detail="Invalid email address")
    if _is_disposable_email(email):
        raise HTTPException(status_code=400, detail="Disposable email addresses are not allowed. Please use a permanent email.")
    return email

def _validate_password(password: str) -> None:
    if not password.strip():
        raise HTTPException(status_code=400, detail="Password must not be blank")
    if len(password) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters")
    if len(password) > 1024:
        raise HTTPException(status_code=400, detail="Password must be at most 1024 characters")
    if not re.search(r'[A-Z]', password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter")
    if not re.search(r'[a-z]', password):
        raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter")
    if not re.search(r'[0-9]', password):
        raise HTTPException(status_code=400, detail="Password must contain at least one number")
    if not re.search(r'[^A-Za-z0-9]', password):
        raise HTTPException(status_code=400, detail="Password must contain at least one special character")


def _check_pwned_password(password: str) -> None:
    """Check password against the Have I Been Pwned API using k-anonymity.
    Fails open on network errors (does not block registration)."""
    try:
        sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix, suffix = sha1[:5], sha1[5:]
        resp = httpx.get(f"https://api.pwnedpasswords.com/range/{prefix}", timeout=5)
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                hash_suffix, count = line.split(":")
                if hash_suffix.strip() == suffix:
                    raise HTTPException(
                        status_code=400,
                        detail="This password has appeared in a data breach. Please choose a different password.",
                    )
    except HTTPException:
        raise
    except Exception:
        pass  # Fail open — don't block registration on network errors


def _verify_turnstile(token: str, ip: str) -> None:
    """Verify a Cloudflare Turnstile token. Skip if TURNSTILE_SECRET_KEY is not set."""
    if not TURNSTILE_SECRET_KEY:
        return
    try:
        resp = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": TURNSTILE_SECRET_KEY, "response": token, "remoteip": ip},
            timeout=10,
        )
        result = resp.json()
        if not result.get("success"):
            raise HTTPException(status_code=400, detail="CAPTCHA verification failed. Please try again.")
    except HTTPException:
        raise
    except Exception:
        _logger.warning("Turnstile verification request failed — skipping")


def _check_password_history(user_id: str, password: str, db) -> None:
    """Reject password if it matches one of the user's last 5 passwords."""
    from models import PasswordHistory
    recent = (
        db.query(PasswordHistory)
        .filter(PasswordHistory.user_id == user_id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(5)
        .all()
    )
    for entry in recent:
        if verify_password(password, entry.password_hash):
            raise HTTPException(
                status_code=400,
                detail="You cannot reuse one of your last 5 passwords. Please choose a different one.",
            )


def _record_password_history(user_id: str, password_hash: str, db) -> None:
    """Store the current password hash in history."""
    from models import PasswordHistory
    db.add(PasswordHistory(user_id=user_id, password_hash=password_hash))
    db.commit()


# ── OAuth state store (CSRF protection) ──────────────────────────────────────
# Stores both login and connect flows.
# Login entry:   {expires_at, flow: "login"}
# Connect entry: {expires_at, flow: "connect", user_id}
_oauth_states: dict[str, dict] = {}
_oauth_states_lock = threading.Lock()
_OAUTH_STATE_TTL = 600  # 10 minutes

# ── OAuth one-time code store (keeps JWT out of the URL) ─────────────────────
_oauth_codes: dict[str, dict] = {}
_oauth_codes_lock = threading.Lock()
_OAUTH_CODE_TTL = 30  # seconds — short-lived, single-use


def _new_oauth_state(extra: dict) -> str:
    """Generate a state token, store the entry, return the token."""
    state = secrets.token_urlsafe(32)
    with _oauth_states_lock:
        _oauth_states[state] = {"expires_at": time.time() + _OAUTH_STATE_TTL, **extra}
    return state


def _new_oauth_code(jwt_token: str) -> str:
    """Store a JWT behind a one-time opaque code. Returns the code."""
    code = secrets.token_urlsafe(32)
    with _oauth_codes_lock:
        _oauth_codes[code] = {"token": jwt_token, "expires_at": time.time() + _OAUTH_CODE_TTL}
    return code


def _oauth_cleanup_loop() -> None:
    """Background thread: sweep expired OAuth states and codes every 60 seconds."""
    while True:
        time.sleep(60)
        now = time.time()
        with _oauth_states_lock:
            expired = [k for k, v in list(_oauth_states.items()) if now > v["expires_at"]]
            for k in expired:
                del _oauth_states[k]
        with _oauth_codes_lock:
            expired = [k for k, v in list(_oauth_codes.items()) if now > v["expires_at"]]
            for k in expired:
                del _oauth_codes[k]


threading.Thread(target=_oauth_cleanup_loop, daemon=True, name="oauth-cleanup").start()

from database import get_db
from models import _utcnow, Analysis, User
from services.auth_service import (
    JWT_SECRET,
    JWT_ALGO,
    create_token,
    create_refresh_token,
    decode_token,
    decode_refresh_token,
    get_current_user,
    hash_password,
    verify_password,
    set_refresh_cookie,
    clear_refresh_cookie,
)
from services.email_service import send_password_reset_email, send_verification_email, send_failed_login_email
from services.email_service import RESEND_API_KEY
from services.encryption import encrypt as encrypt_field, decrypt as decrypt_field
from services.rate_limiter import check_rate_limit_key
from services.client_ip import get_client_ip as _get_client_ip

router = APIRouter()


def _make_user_response(user: "User") -> "UserResponse":
    return UserResponse(
        id=user.id,
        email=user.email,
        plan=user.plan,
        is_admin=user.is_admin,
        is_verified=getattr(user, "is_verified", True),
        github_connected=bool(getattr(user, "github_access_token", None)),
        github_username=getattr(user, "github_username", None),
    )


def _generate_verification_code() -> str:
    """8-digit numeric code (00000000–99999999, zero-padded)."""
    return f"{secrets.randbelow(100_000_000):08d}"


def _smtp_configured() -> bool:
    return bool(RESEND_API_KEY)


class RegisterRequest(BaseModel):
    email: str
    password: str
    turnstile_token: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    plan: str
    is_admin: bool
    is_verified: bool = False
    github_connected: bool = False
    github_username: str | None = None


class AuthResponse(BaseModel):
    token: str
    user: UserResponse


@router.post("/auth/register", response_model=AuthResponse)
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"register:{ip}", max_requests=5, window=3600)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many registration attempts. Try again in {retry_after} seconds.",
        )
    # Verify CAPTCHA
    _verify_turnstile(req.turnstile_token or "", ip)

    email = _validate_email(req.email)
    _validate_password(req.password)
    _check_pwned_password(req.password)

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Unable to create account. Please try a different email or log in.")

    # Block registration if too many free accounts already exist from this IP
    _MAX_ACCOUNTS_PER_IP = 5
    ip_account_count = db.query(User).filter(User.signup_ip == ip, User.plan == "free").count()
    if ip_account_count >= _MAX_ACCOUNTS_PER_IP:
        _logger.warning("Blocked registration from IP %s — already %d accounts", ip, ip_account_count)
        raise HTTPException(
            status_code=429,
            detail="Too many accounts created from this network. Contact support if this is an error.",
        )

    is_admin_email = bool(ADMIN_EMAIL and email == ADMIN_EMAIL)
    if is_admin_email:
        if not ADMIN_PASSWORD:
            raise HTTPException(status_code=403, detail="Admin registration is not configured")
        # Use constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(req.password, ADMIN_PASSWORD):
            raise HTTPException(status_code=403, detail="Invalid email or password")

    # Admin users and accounts created when SMTP is not configured are auto-verified
    smtp_ready = _smtp_configured()
    auto_verified = is_admin_email or not smtp_ready

    code = _generate_verification_code() if not auto_verified else None
    expires = datetime.now(timezone.utc) + timedelta(hours=2) if code else None

    user = User(
        email=email,
        password_hash=hash_password(req.password),
        plan="pro" if is_admin_email else "free",
        is_admin=is_admin_email,
        is_verified=auto_verified,
        verification_code=code,
        verification_expires=expires,
        signup_ip=ip,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if code:
        send_verification_email(email, code)

    token = create_token(user.id)
    refresh = create_refresh_token(user.id)
    from fastapi.responses import JSONResponse
    resp = JSONResponse(content=AuthResponse(token=token, user=_make_user_response(user)).model_dump())
    set_refresh_cookie(resp, refresh)
    return resp


_LOCKOUT_THRESHOLD = 5
_LOCKOUT_DURATION_MINUTES = 15


@router.post("/auth/login", response_model=AuthResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"login:{ip}", max_requests=10, window=3600)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Try again in {retry_after} seconds.",
        )
    email = req.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    # Check account lockout before password verification
    if user:
        locked_until = getattr(user, "locked_until", None)
        if locked_until:
            now = _utcnow()
            if now < locked_until:
                remaining = int((locked_until - now).total_seconds() // 60) + 1
                raise HTTPException(
                    status_code=423,
                    detail=f"Account temporarily locked due to too many failed login attempts. Try again in {remaining} minute(s).",
                )
            else:
                # Lockout expired — reset
                user.locked_until = None
                user.failed_login_count = 0
                db.commit()

    if not user or not verify_password(req.password, user.password_hash):
        _logger.warning("Failed login attempt for email=%s ip=%s", email, ip)
        # Track failed attempts
        if user:
            failed_count = getattr(user, "failed_login_count", 0) or 0
            failed_count += 1
            user.failed_login_count = failed_count
            if failed_count >= _LOCKOUT_THRESHOLD:
                user.locked_until = _utcnow() + timedelta(minutes=_LOCKOUT_DURATION_MINUTES)
                db.commit()
                raise HTTPException(
                    status_code=423,
                    detail=f"Account locked for {_LOCKOUT_DURATION_MINUTES} minutes due to too many failed login attempts.",
                )
            db.commit()
            # Send warning email after 3+ failed attempts
            if failed_count >= 3:
                send_failed_login_email(user.email, ip, failed_count)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Successful login — reset failed count
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login = _utcnow()
    user.last_login_ip = ip
    db.commit()

    _logger.info("AUDIT login_success email=%s ip=%s user_id=%s", email, ip, user.id)

    token = create_token(user.id)
    refresh = create_refresh_token(user.id)
    from fastapi.responses import JSONResponse
    resp = JSONResponse(content=AuthResponse(token=token, user=_make_user_response(user)).model_dump())
    set_refresh_cookie(resp, refresh)
    return resp


@router.get("/auth/me", response_model=UserResponse)
def me(request: Request, current_user: User = Depends(get_current_user)):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"me:{ip}", max_requests=60, window=60)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many requests. Try again in {retry_after} seconds.")
    return _make_user_response(current_user)


@router.post("/auth/refresh", response_model=AuthResponse)
def refresh_token(request: Request, db: Session = Depends(get_db)):
    """Exchange a refresh token cookie for a new access token + rotated refresh cookie."""
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"refresh:{ip}", max_requests=30, window=60)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many requests. Try again in {retry_after} seconds.")

    refresh_cookie = request.cookies.get("hl_refresh")
    if not refresh_cookie:
        raise HTTPException(status_code=401, detail="No refresh token")

    payload = decode_refresh_token(refresh_cookie)
    user_id = payload.get("sub", "")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    from services.auth_service import _check_user_token
    _check_user_token(user, payload)

    new_access = create_token(user.id)
    new_refresh = create_refresh_token(user.id)
    from fastapi.responses import JSONResponse
    resp = JSONResponse(content=AuthResponse(token=new_access, user=_make_user_response(user)).model_dump())
    set_refresh_cookie(resp, new_refresh)
    return resp


@router.post("/auth/logout", status_code=200)
def logout_endpoint(request: Request):
    """Clear the refresh token cookie."""
    from fastapi.responses import JSONResponse
    resp = JSONResponse(content={"detail": "Logged out."})
    clear_refresh_cookie(resp)
    return resp


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/auth/forgot-password", status_code=200)
def forgot_password(req: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Always returns 200 to prevent user enumeration."""
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"reset:{ip}", max_requests=5, window=3600)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many reset requests. Try again in {retry_after} seconds.",
        )
    email = req.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user:
        # Include first 8 chars of current password hash so token auto-invalidates after use
        expire = datetime.now(timezone.utc) + timedelta(hours=1)
        payload = {
            "sub": user.id,
            "purpose": "reset",
            "ph": user.password_hash[:8],
            "exp": expire,
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
        reset_url = f"{APP_URL}/reset-password?token={token}"
        send_password_reset_email(user.email, reset_url)
    return {"detail": "If that email exists, a reset link has been sent."}


@router.post("/auth/reset-password", status_code=200)
def reset_password(req: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"reset-submit:{ip}", max_requests=5, window=3600)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Try again in {retry_after} seconds.",
        )
    try:
        payload = jwt.decode(req.token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Reset link has expired. Please request a new one.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid or malformed reset link.")

    if payload.get("purpose") != "reset":
        raise HTTPException(status_code=400, detail="Invalid reset token.")

    user_id: str = payload.get("sub", "")
    ph_prefix: str = payload.get("ph", "")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="User not found.")

    # Validate hash prefix — ensures token is single-use (changes after password reset)
    if user.password_hash[:8] != ph_prefix:
        raise HTTPException(status_code=400, detail="Reset link has already been used.")

    _validate_password(req.new_password)
    _check_pwned_password(req.new_password)
    _check_password_history(user_id, req.new_password, db)
    _record_password_history(user_id, user.password_hash, db)

    user.password_hash = hash_password(req.new_password)
    db.commit()
    _logger.info("AUDIT password_reset user_id=%s email=%s", user.id, user.email)
    return {"detail": "Password updated successfully."}


# ── User settings ─────────────────────────────────────────────────────────────

class SettingsRequest(BaseModel):
    notify_on_complete: bool


@router.get("/auth/settings")
def get_settings_route(request: Request, current_user: User = Depends(get_current_user)):
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"settings:{ip}", max_requests=30, window=60)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many requests. Try again in {retry_after} seconds.")
    return {"notify_on_complete": getattr(current_user, "notify_on_complete", False)}


@router.patch("/auth/settings", status_code=200)
def update_settings(req: SettingsRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.notify_on_complete = req.notify_on_complete
    db.commit()
    return {"detail": "Settings updated."}


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.patch("/auth/change-password", status_code=200)
def change_password(req: ChangePasswordRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.password_hash:
        raise HTTPException(
            status_code=400,
            detail="This account uses GitHub login and has no password. Use 'Forgot password' to set one.",
        )
    if not verify_password(req.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    _validate_password(req.new_password)
    _check_pwned_password(req.new_password)
    _check_password_history(current_user.id, req.new_password, db)
    _record_password_history(current_user.id, current_user.password_hash, db)
    current_user.password_hash = hash_password(req.new_password)
    db.commit()
    _logger.info("AUDIT password_changed user_id=%s email=%s", current_user.id, current_user.email)
    return {"detail": "Password changed successfully."}


@router.delete("/auth/account", status_code=200)
def delete_account(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from models import WatchedRepo
    db.query(WatchedRepo).filter(WatchedRepo.user_id == current_user.id).delete()
    db.query(Analysis).filter(Analysis.user_id == current_user.id).delete()
    _logger.info("AUDIT account_deleted user_id=%s email=%s", current_user.id, current_user.email)
    db.delete(current_user)
    db.commit()
    return {"detail": "Account deleted."}


# ── Email verification ────────────────────────────────────────────────────────

class VerifyEmailRequest(BaseModel):
    code: str


@router.post("/auth/verify-email", status_code=200)
def verify_email(req: VerifyEmailRequest, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if getattr(current_user, "is_verified", True):
        return {"detail": "Already verified."}

    # Rate-limit code attempts to prevent brute-forcing the 8-digit code
    # 3 attempts per 15 minutes per user+IP, plus 5 per hour per user (any IP)
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(
        f"verify:{current_user.id}:{ip}", max_requests=3, window=900
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Try again in {retry_after} seconds.",
        )
    allowed2, retry_after2 = check_rate_limit_key(
        f"verify_user:{current_user.id}", max_requests=5, window=3600
    )
    if not allowed2:
        # Invalidate the code after too many total failed attempts — force resend
        current_user.verification_code = None
        current_user.verification_expires = None
        db.commit()
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Your code has been invalidated. Please request a new one.",
        )

    stored_code = getattr(current_user, "verification_code", None)
    expires = getattr(current_user, "verification_expires", None)

    if not stored_code or not hmac.compare_digest(req.code.strip(), stored_code):
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    if expires and datetime.now(timezone.utc) > expires.replace(tzinfo=timezone.utc):
        raise HTTPException(status_code=400, detail="Code has expired. Request a new one.")

    current_user.is_verified = True
    current_user.verification_code = None
    current_user.verification_expires = None
    db.commit()
    return {"detail": "Email verified successfully."}


@router.post("/auth/resend-verification", status_code=200)
def resend_verification(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if getattr(current_user, "is_verified", True):
        return {"detail": "Already verified."}

    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"resend:{ip}", max_requests=3, window=3600)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many resend requests. Try again in {retry_after} seconds.",
        )

    code = _generate_verification_code()
    current_user.verification_code = code
    current_user.verification_expires = datetime.now(timezone.utc) + timedelta(hours=2)
    db.commit()
    send_verification_email(current_user.email, code)
    return {"detail": "Verification code resent."}


# ── GitHub OAuth ──────────────────────────────────────────────────────────────

@router.get("/auth/github")
def github_login():
    """Start login OAuth flow (scope: user:email)."""
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured.")
    state = _new_oauth_state({"flow": "login"})
    from urllib.parse import urlencode
    params = urlencode({"client_id": GITHUB_CLIENT_ID, "scope": "user:email", "state": state})
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{params}")


@router.post("/auth/github/connect")
def github_connect(
    current_user: User = Depends(get_current_user),
):
    """Start connect OAuth flow (scope: repo) to enable private repo access."""
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured.")
    state = _new_oauth_state({"flow": "connect", "user_id": current_user.id})
    from urllib.parse import urlencode
    params = urlencode({"client_id": GITHUB_CLIENT_ID, "scope": "repo", "state": state})
    return {"url": f"https://github.com/login/oauth/authorize?{params}"}


@router.get("/auth/github/callback")
def github_callback(code: str, state: str = "", request: Request = None, db: Session = Depends(get_db)):
    """Single callback for both login and connect flows — flow type is in the state entry."""
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured.")

    with _oauth_states_lock:
        entry = _oauth_states.pop(state, None)
    if not entry or time.time() > entry["expires_at"]:
        return RedirectResponse(f"{APP_URL}/login?error=invalid_state")

    flow = entry.get("flow", "login")

    # Exchange code for access token
    token_res = httpx.post(
        "https://github.com/login/oauth/access_token",
        json={"client_id": GITHUB_CLIENT_ID, "client_secret": GITHUB_CLIENT_SECRET, "code": code},
        headers={"Accept": "application/json"},
        timeout=10,
    )
    access_token = token_res.json().get("access_token", "")
    if not access_token:
        dest = f"{APP_URL}/settings?error=github_failed" if flow == "connect" else f"{APP_URL}/login?error=github_failed"
        return RedirectResponse(dest)

    # ── Connect flow: store token + username on the existing user ────────────
    if flow == "connect":
        user = db.query(User).filter(User.id == entry["user_id"]).first()
        if not user:
            return RedirectResponse(f"{APP_URL}/settings?error=github_failed")
        # Fetch GitHub username to display in settings
        gh_info = httpx.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=10,
        ).json()
        user.github_access_token = encrypt_field(access_token)
        user.github_username = gh_info.get("login") or None
        db.commit()
        return RedirectResponse(f"{APP_URL}/auth/connect-callback")

    # ── Login flow: find or create user ───────────────────────────────────────
    user_res = httpx.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=10,
    )
    gh_user = user_res.json()
    github_id = str(gh_user.get("id", ""))
    gh_email = gh_user.get("email") or ""

    if not gh_email:
        emails_res = httpx.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=10,
        )
        for e in emails_res.json():
            if e.get("primary") and e.get("verified"):
                gh_email = e["email"]
                break

    if not gh_email:
        return RedirectResponse(f"{APP_URL}/login?error=github_no_email")

    gh_email = gh_email.strip().lower()

    user = db.query(User).filter(User.github_id == github_id).first()
    if not user:
        user = db.query(User).filter(User.email == gh_email).first()
    if not user:
        _gh_ip = _get_client_ip(request) if request else None
        user = User(email=gh_email, password_hash="", plan="free", is_admin=False, signup_ip=_gh_ip)
        db.add(user)
    user.github_id = github_id
    user.is_verified = True
    user.verification_code = None
    user.verification_expires = None
    user.last_login = _utcnow()
    db.commit()
    db.refresh(user)

    _logger.info("AUDIT github_oauth_login user_id=%s email=%s github_id=%s", user.id, gh_email, github_id)

    jwt_token = create_token(user.id)
    refresh = create_refresh_token(user.id)
    # Use a server-side one-time code so the JWT is never placed in the URL
    code = _new_oauth_code(jwt_token)
    response = RedirectResponse(f"{APP_URL}/auth/callback?code={code}")
    set_refresh_cookie(response, refresh)
    return response


@router.delete("/auth/github/token", status_code=200)
def disconnect_github(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Remove the stored GitHub access token for the current user."""
    _logger.info("AUDIT github_disconnected user_id=%s email=%s", current_user.id, current_user.email)
    current_user.github_access_token = None
    current_user.github_username = None
    db.commit()
    return {"detail": "GitHub disconnected."}


class ExchangeCodeRequest(BaseModel):
    code: str


@router.post("/auth/github/exchange", response_model=AuthResponse)
def exchange_oauth_code(req: ExchangeCodeRequest, request: Request, db: Session = Depends(get_db)):
    """Exchange a one-time OAuth code for a JWT. Single-use — consumes the code."""
    ip = _get_client_ip(request)
    allowed, retry_after = check_rate_limit_key(f"oauth_exchange:{ip}", max_requests=10, window=3600)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Try again in {retry_after} seconds.",
        )
    with _oauth_codes_lock:
        entry = _oauth_codes.pop(req.code, None)
    if not entry or time.time() > entry["expires_at"]:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization code.")
    token = entry["token"]
    payload = decode_token(token)
    user_id = payload.get("sub", "")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    return AuthResponse(token=token, user=_make_user_response(user))


# ── API Key management ──────────────────────────────────────────────────────

class CreateApiKeyRequest(BaseModel):
    name: str


@router.post("/auth/api-keys")
def create_api_key(
    req: CreateApiKeyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new API key. Returns the raw key once — cannot be retrieved again."""
    from models import ApiKey
    from services.auth_service import generate_api_key

    name = req.name.strip()
    if not name or len(name) > 100:
        raise HTTPException(status_code=400, detail="Name must be 1-100 characters.")

    # Limit to 10 keys per user
    count = db.query(ApiKey).filter(ApiKey.user_id == current_user.id).count()
    if count >= 10:
        raise HTTPException(status_code=400, detail="Maximum 10 API keys per account.")

    raw_key, api_key = generate_api_key(current_user.id, name, db)
    return {
        "id": api_key.id,
        "key": raw_key,  # shown once
        "prefix": api_key.prefix,
        "name": api_key.name,
        "created_at": api_key.created_at.isoformat(),
    }


@router.get("/auth/api-keys")
def list_api_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List API keys (prefix + name + last_used only, never the full key)."""
    from models import ApiKey

    keys = (
        db.query(ApiKey)
        .filter(ApiKey.user_id == current_user.id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return [
        {
            "id": k.id,
            "prefix": k.prefix,
            "name": k.name,
            "last_used": k.last_used.isoformat() if k.last_used else None,
            "created_at": k.created_at.isoformat(),
        }
        for k in keys
    ]


@router.delete("/auth/api-keys/{key_id}")
def revoke_api_key(
    key_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke (delete) an API key."""
    from models import ApiKey

    api_key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.user_id == current_user.id).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found.")
    db.delete(api_key)
    db.commit()
    return {"detail": "API key revoked."}

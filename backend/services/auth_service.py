import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import ApiKey, User

_logger = logging.getLogger(__name__)

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
REFRESH_TOKEN_SECRET = os.getenv("REFRESH_TOKEN_SECRET", JWT_SECRET + "-refresh")
_APP_URL = os.getenv("APP_URL", "http://localhost:3000")
_is_production = not _APP_URL.startswith("http://localhost")
if JWT_SECRET == "dev-secret-change-me":
    if _is_production:
        raise RuntimeError(
            "JWT_SECRET must be set to a strong random value before deploying to production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    _logger.warning(
        "⚠️  JWT_SECRET is set to the insecure default. "
        "Set a strong random value via the JWT_SECRET environment variable before deploying."
    )
JWT_ALGO = "HS256"
_ACCESS_TOKEN_MINUTES = 15
_REFRESH_TOKEN_DAYS = 7
_JWT_ISSUER = "hootly"
_JWT_AUDIENCE = "hootly-api"

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer()


def hash_password(password: str) -> str:
    return _pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


def create_token(user_id: str) -> str:
    """Create a short-lived access token (15 minutes)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=_ACCESS_TOKEN_MINUTES)
    payload = {
        "sub": user_id,
        "purpose": "access",
        "exp": expire,
        "iss": _JWT_ISSUER,
        "aud": _JWT_AUDIENCE,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived refresh token (7 days)."""
    expire = datetime.now(timezone.utc) + timedelta(days=_REFRESH_TOKEN_DAYS)
    payload = {
        "sub": user_id,
        "purpose": "refresh",
        "exp": expire,
        "iss": _JWT_ISSUER,
        "aud": _JWT_AUDIENCE,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, REFRESH_TOKEN_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict:
    """Decode access JWT and return the full payload dict. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALGO],
            issuer=_JWT_ISSUER, audience=_JWT_AUDIENCE,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def decode_refresh_token(token: str) -> dict:
    """Decode a refresh token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(
            token, REFRESH_TOKEN_SECRET, algorithms=[JWT_ALGO],
            issuer=_JWT_ISSUER, audience=_JWT_AUDIENCE,
        )
        if payload.get("purpose") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")


def set_refresh_cookie(response, token: str) -> None:
    """Set the refresh token as an httpOnly cookie on a response."""
    response.set_cookie(
        key="hl_refresh",
        value=token,
        httponly=True,
        secure=_is_production,
        samesite="lax",
        path="/api/auth",
        max_age=_REFRESH_TOKEN_DAYS * 86400,
    )


def clear_refresh_cookie(response) -> None:
    """Clear the refresh token cookie."""
    response.set_cookie(
        key="hl_refresh",
        value="",
        httponly=True,
        secure=_is_production,
        samesite="lax",
        path="/api/auth",
        max_age=0,
    )


def _check_user_token(user: User, payload: dict) -> None:
    """Reject banned users and tokens issued before invalidation."""
    if getattr(user, "is_banned", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")
    invalidated_at = getattr(user, "token_invalidated_at", None)
    if invalidated_at:
        iat = payload.get("iat", 0)
        # token_invalidated_at is naive UTC; iat is epoch seconds
        invalidated_epoch = invalidated_at.replace(tzinfo=timezone.utc).timestamp()
        if iat < invalidated_epoch:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked. Please log in again.")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    user_id: str = payload.get("sub", "")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    _check_user_token(user, payload)
    return user


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Returns the User if a valid Bearer token is present, otherwise None."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer "):].strip()
    if not token:
        return None
    try:
        payload = decode_token(token)
    except HTTPException:
        return None
    user_id: str = payload.get("sub", "")
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        try:
            _check_user_token(user, payload)
        except HTTPException:
            return None
    return user


# ── API Key support ─────────────────────────────────────────────────────────

def generate_api_key(user_id: str, name: str, db: Session) -> tuple[str, ApiKey]:
    """Generate a new API key. Returns (raw_key, ApiKey model). The raw key is shown once."""
    raw = "hk_" + secrets.token_hex(20)  # hk_ + 40 hex chars
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:11]  # "hk_" + first 8 hex chars

    api_key = ApiKey(
        user_id=user_id,
        key_hash=key_hash,
        prefix=prefix,
        name=name,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return raw, api_key


def get_user_by_api_key(key: str, db: Session) -> Optional[User]:
    """Look up a user by API key. Returns None if invalid."""
    if not key.startswith("hk_"):
        return None
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not api_key:
        return None
    # Update last_used
    api_key.last_used = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    user = db.query(User).filter(User.id == api_key.user_id).first()
    return user


def get_current_user_or_api_key(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Authenticate via Bearer JWT or X-API-Key header."""
    # Try Bearer token first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):].strip()
        if token:
            payload = decode_token(token)
            user_id: str = payload.get("sub", "")
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
            _check_user_token(user, payload)
            return user

    # Try X-API-Key header
    api_key = request.headers.get("X-API-Key", "").strip()
    if api_key:
        user = get_user_by_api_key(api_key, db)
        if user:
            if getattr(user, "is_banned", False):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")
            return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

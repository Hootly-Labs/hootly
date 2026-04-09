import logging
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

# Configure root logger so _logger.info() calls in api/ and services/ are visible
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s — %(message)s")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from database import init_db
from api.routes import router
from api.auth import router as auth_router
from api.admin import router as admin_router
from api.billing import router as billing_router
from api.watch import router as watch_router
from api.chat import router as chat_router
from api.badge import router as badge_router
from api.github_app import router as github_app_router
from api.assessment import router as assessment_router
from api.teams import router as teams_router
from api.knowledge import router as knowledge_router
from api.slack import router as slack_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from services.watcher_service import start_watcher
    start_watcher()
    yield


_is_production = not os.getenv("APP_URL", "http://localhost:3000").startswith("http://localhost")

app = FastAPI(
    title="Hootly API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

# ── Request body size limit ───────────────────────────────────────────────────
# Stripe webhooks are small (~2 KB). Analysis requests are just a URL.
# Cap at 1 MB to prevent memory-exhaustion / bcrypt-DoS via huge request bodies.
_MAX_BODY_BYTES = 1_000_000  # 1 MB


class _LimitBodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large (max 1 MB)."},
            )
        return await call_next(request)


_ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")

_CSP_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://challenges.cloudflare.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    f"connect-src 'self' {' '.join(o.strip() for o in _ALLOWED_ORIGINS.split(','))}",
    "frame-src https://challenges.cloudflare.com https://js.stripe.com",
    "object-src 'none'",
    "base-uri 'self'",
])

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": _CSP_POLICY,
}

if _is_production:
    _SECURITY_HEADERS["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


app.add_middleware(_LimitBodySizeMiddleware)
app.add_middleware(_SecurityHeadersMiddleware)

# Allow Next.js dev server and production
origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "stripe-signature"],
    max_age=86400,
)

app.include_router(router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(watch_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(badge_router, prefix="/api")
app.include_router(github_app_router, prefix="/api")
app.include_router(assessment_router, prefix="/api")
app.include_router(teams_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(slack_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}

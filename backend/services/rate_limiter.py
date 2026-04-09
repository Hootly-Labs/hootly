"""
Sliding-window rate limiter with optional Redis backend.

When REDIS_URL is set, uses Redis sorted sets (ZADD/ZREMRANGEBYSCORE/ZCARD)
for persistence across restarts. Falls back to in-memory when Redis is
unavailable.
"""
import logging
import os
import threading
import time
from collections import deque

_logger = logging.getLogger(__name__)

# Max analyses per IP per window
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 3600  # seconds (1 hour)

# ── Redis backend (optional) ────────────────────────────────────────────────────
_redis_client = None
_REDIS_URL = os.getenv("REDIS_URL", "")

if _REDIS_URL:
    try:
        import redis
        _redis_client = redis.from_url(_REDIS_URL, decode_responses=True, socket_timeout=3)
        _redis_client.ping()
        _logger.info("Rate limiter using Redis backend")
    except Exception as exc:
        _logger.warning("Redis unavailable (%s) — falling back to in-memory rate limiting", exc)
        _redis_client = None


def _redis_check(key: str, max_requests: int, window: int) -> tuple[bool, int, int]:
    """Redis sorted-set sliding window. Returns (allowed, remaining, retry_after)."""
    now = time.time()
    pipe = _redis_client.pipeline()
    pipe.zremrangebyscore(key, "-inf", now - window)
    pipe.zcard(key)
    pipe.execute()

    # Re-check count after cleanup
    count = _redis_client.zcard(key)
    if count >= max_requests:
        oldest = _redis_client.zrange(key, 0, 0, withscores=True)
        if oldest:
            retry_after = max(1, int(oldest[0][1] + window - now) + 1)
        else:
            retry_after = 1
        return False, 0, retry_after

    _redis_client.zadd(key, {f"{now}:{id(key)}:{count}": now})
    _redis_client.expire(key, window + 60)
    remaining = max_requests - count - 1
    return True, remaining, 0


# ── In-memory backend (default) ──────────────────────────────────────────────────
_lock = threading.Lock()
_requests: dict[str, deque] = {}
_keyed_requests: dict[str, deque] = {}


def _prune(dq: deque, now: float, window: int = RATE_LIMIT_WINDOW) -> None:
    """Remove timestamps older than the window."""
    cutoff = now - window
    while dq and dq[0] < cutoff:
        dq.popleft()


def _evict_empty(d: dict) -> None:
    """Delete keys whose deque is now empty (called while holding _lock)."""
    empty = [k for k, v in d.items() if not v]
    for k in empty:
        del d[k]


def check_rate_limit(ip: str) -> tuple[bool, int, int]:
    """
    Returns (allowed, remaining, retry_after_seconds).
    """
    if _redis_client:
        try:
            return _redis_check(f"rl:ip:{ip}", RATE_LIMIT_MAX, RATE_LIMIT_WINDOW)
        except Exception:
            _logger.warning("Redis rate limit check failed — falling back to in-memory")

    now = time.time()
    with _lock:
        if ip not in _requests:
            _requests[ip] = deque()
        dq = _requests[ip]
        _prune(dq, now)

        count = len(dq)
        if count >= RATE_LIMIT_MAX:
            retry_after = max(1, int(dq[0] + RATE_LIMIT_WINDOW - now) + 1)
            return False, 0, retry_after

        dq.append(now)
        remaining = RATE_LIMIT_MAX - len(dq)
        return True, remaining, 0


def check_rate_limit_key(key: str, max_requests: int, window: int) -> tuple[bool, int]:
    """
    Generic key-based rate limiter.
    Returns (allowed, retry_after_seconds).
    """
    if _redis_client:
        try:
            allowed, _remaining, retry_after = _redis_check(f"rl:key:{key}", max_requests, window)
            return allowed, retry_after
        except Exception:
            _logger.warning("Redis rate limit check failed — falling back to in-memory")

    now = time.time()
    with _lock:
        if key not in _keyed_requests:
            _keyed_requests[key] = deque()
        dq = _keyed_requests[key]
        cutoff = now - window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_requests:
            retry_after = max(1, int(dq[0] + window - now) + 1)
            return False, retry_after
        dq.append(now)
        return True, 0


# ── Background cleanup thread (in-memory only) ──────────────────────────────────

def _cleanup_loop() -> None:
    while True:
        time.sleep(600)  # every 10 minutes
        now = time.time()
        with _lock:
            for dq in list(_requests.values()):
                _prune(dq, now)
            _evict_empty(_requests)

            for dq in list(_keyed_requests.values()):
                _prune(dq, now, RATE_LIMIT_WINDOW)
            _evict_empty(_keyed_requests)


_cleanup_thread = threading.Thread(target=_cleanup_loop, daemon=True, name="rate-limiter-cleanup")
_cleanup_thread.start()

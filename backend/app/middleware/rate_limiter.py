"""
Sliding Window Rate Limiter — FastAPI Dependency (not middleware).

WHY DEPENDENCY OVER MIDDLEWARE:
────────────────────────────────
Starlette's BaseHTTPMiddleware has severe performance penalties at high concurrency:
  - Forces new Task creation per request (context switching overhead)
  - Bridges ASGI gap using memory channels
  - At 9,000 VUs: context switching alone consumes significant CPU

FastAPI Depends() is directly in the request handling path:
  - Zero middleware overhead
  - Accepts already-decoded user object — no duplicate JWT decryption
  - Only applied to routes that need it

WHY NO DUPLICATE JWT DECRYPTION:
──────────────────────────────────
Old approach: middleware decoded JWT to extract user_id for rate limiting
              AND auth dependency decoded JWT again for authentication
              = 2x JWT decryption per request at 9,000 VUs = massive CPU waste

New approach: rate limiter accepts current_user from auth dependency
              JWT decoded once, user_id reused for rate limiting
              = 0 extra cryptographic operations

WHY EVAL OVER EVALSHA:
───────────────────────
Originally used SCRIPT LOAD + EVALSHA (send SHA1 hash per request instead of
full script). However, OpenTelemetry Redis instrumentation intercepts exceptions
before redis-py's built-in EVALSHA → EVAL fallback can handle NoScriptError.
This causes OTel to record a false error span on every Redis restart/flush.

Solution: use EVAL directly — sends script on every call, slightly more bytes
per request (~200 bytes) but eliminates the NoScriptError entirely and works
correctly with OTel instrumentation. At 9,000 VUs the overhead is negligible.
"""

import time
import uuid

import structlog
from fastapi import Depends, HTTPException, Request, status

from app.utils.metrics import RATE_LIMIT_HITS

logger = structlog.get_logger()

# ── Rate limit constants ──────────────────────────────────────────────────────
RESERVATION_LIMIT  = 5    # per user per window
RESERVATION_WINDOW = 60   # seconds
AUTH_LOGIN_LIMIT   = 100  # per IP per window
AUTH_LOGIN_WINDOW  = 60

# ── Lua script — sent via EVAL on every call ──────────────────────────────────
# Sliding window rate limiter using Redis sorted set.
# ZREMRANGEBYSCORE removes expired entries, ZCARD counts current,
# ZADD adds current request, PEXPIRE resets TTL.
# Atomic — no race conditions possible.
_lua_script = """
local key        = KEYS[1]
local now        = tonumber(ARGV[1])
local window     = tonumber(ARGV[2])
local limit      = tonumber(ARGV[3])
local request_id = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

local count = redis.call('ZCARD', key)

if count >= limit then
    return {count, 0}
end

redis.call('ZADD', key, now, request_id)
redis.call('PEXPIRE', key, window)

return {count + 1, 1}
"""


async def init_rate_limiter(redis) -> None:
    """
    No-op — kept for API compatibility with main.py lifespan.
    Previously pre-loaded Lua script via SCRIPT LOAD + EVALSHA.
    Now uses EVAL directly — no startup initialization needed.
    """
    logger.info("Rate limiter ready (EVAL mode)")


async def _check_rate_limit(
    redis,
    identifier: str,
    limit: int,
    window_seconds: int,
    path: str,
) -> None:
    """
    Core rate limit check using Lua script via EVAL.
    Raises HTTP 429 if limit exceeded.
    Fails open if Redis is unavailable.
    """
    key       = f"ratelimit:{identifier}:{path}"
    window_ms = window_seconds * 1000
    now_ms    = int(time.time() * 1000)

    try:
        result = await redis.eval(
            _lua_script,
            1,                  # number of keys
            key,                # KEYS[1]
            now_ms,             # ARGV[1]
            window_ms,          # ARGV[2]
            limit,              # ARGV[3]
            str(uuid.uuid4()),  # ARGV[4] — unique request ID for ZADD
        )

        current_count = int(result[0])
        allowed       = int(result[1])

    except Exception:
        return  # Redis unavailable — fail open

    if not allowed:
        RATE_LIMIT_HITS.labels(path=path).inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit: {limit} requests per {window_seconds}s. Try again later.",
            headers={
                "Retry-After":       str(window_seconds),
                "X-RateLimit-Limit": str(limit),
            },
        )


# ── Per-endpoint dependencies ─────────────────────────────────────────────────

async def check_reservation_rate_limit(
    request: Request,
    current_user: dict,
    redis,
) -> None:
    """
    Called directly from create_reservation with current_user already decoded.
    Zero duplicate JWT work.
    5 reservation attempts per user per 60 seconds.
    """
    user_id    = str(current_user["id"])
    identifier = f"user:{user_id}"
    await _check_rate_limit(
        redis, identifier,
        RESERVATION_LIMIT, RESERVATION_WINDOW,
        "/reservations",
    )


async def check_login_rate_limit(
    request: Request,
    redis,
) -> None:
    """
    Rate limit for login endpoint — by IP since user not yet authenticated.
    100 attempts per IP per 60 seconds.
    """
    identifier = f"ip:{request.client.host}"
    await _check_rate_limit(
        redis, identifier,
        AUTH_LOGIN_LIMIT, AUTH_LOGIN_WINDOW,
        "/auth/login",
    )


# ── Keep SlidingWindowRateLimiter for backward compatibility ──────────────────
# No-op stub — actual rate limiting is now in dependencies above
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response


class SlidingWindowRateLimiter(BaseHTTPMiddleware):
    """
    No-op stub — rate limiting moved to FastAPI dependencies.
    Kept for import compatibility only.
    """
    async def dispatch(self, request: StarletteRequest, call_next) -> Response:
        return await call_next(request)
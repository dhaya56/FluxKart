"""
Payment Idempotency.

WHY THIS EXISTS:
─────────────────
Without idempotency, a user who clicks "Pay" twice in quick succession
(double-click, network retry, browser back button) could be charged twice.

This is the #1 cause of customer complaints at payment companies.

HOW IT WORKS:
──────────────
Before processing payment:
  1. Generate idempotency key = hash(user_id + order_id + amount)
  2. Check Redis: has this key been used?
  3. If yes → return cached result (same response, no double charge)
  4. If no  → process payment, cache result with TTL

REDIS KEY:
  pay_idem:{key}  → JSON result, TTL = 24 hours

INTERVIEW TALKING POINT:
─────────────────────────
"Our payment endpoint is idempotent. The key is derived from
user_id + order_id + amount — so even if the user clicks Pay 10 times,
only one charge is processed. Stripe's own API uses the same pattern.
This is critical for distributed systems where retries are common."
"""

import hashlib
import json
from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

IDEMPOTENCY_TTL = 86400  # 24 hours


def generate_payment_key(user_id: str, order_id: str, amount: str) -> str:
    """
    Deterministic idempotency key from payment parameters.
    Same inputs always produce same key.
    """
    raw = f"pay:{user_id}:{order_id}:{amount}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def check_idempotency(
    redis: aioredis.Redis,
    key: str,
) -> dict | None:
    """
    Returns cached payment result if key already used.
    Returns None if this is a fresh payment attempt.
    """
    try:
        cached = await redis.get(f"pay_idem:{key}")
        if cached:
            result = json.loads(cached)
            logger.info(
                "Duplicate payment attempt blocked — returning cached result",
                idempotency_key=key,
                original_at=result.get("processed_at"),
            )
            return result
    except Exception as e:
        logger.warning("Idempotency check failed — proceeding with payment", error=str(e))

    return None


async def store_idempotency_result(
    redis: aioredis.Redis,
    key: str,
    result: dict,
) -> None:
    """
    Caches payment result for 24 hours.
    Any retry within 24h returns this cached result.
    """
    try:
        result["processed_at"] = datetime.now(timezone.utc).isoformat()
        await redis.set(
            f"pay_idem:{key}",
            json.dumps(result),
            ex=IDEMPOTENCY_TTL,
        )
    except Exception as e:
        # Redis down — idempotency unavailable but payment still processed
        # Log for monitoring but don't block the response
        logger.warning(
            "Could not store idempotency result — Redis unavailable",
            error=str(e),
            key=key,
        )
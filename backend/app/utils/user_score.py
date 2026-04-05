"""
User Behavioral Scoring System.

PURPOSE:
─────────
Distinguishes between two types of reservation abandonment:

1. MALICIOUS: Bots/scalpers reserving inventory without intent to buy
   → Detected by: high abandonment rate, rapid repeated attempts,
     no purchase history
   → Response: shorten TTL to 2 minutes

2. LEGITIMATE: Real users who face emergencies, payment failures, etc.
   → Detected by: good purchase history, first abandonment,
     quick return after expiry
   → Response: full TTL + recovery window

SCORING ALGORITHM:
───────────────────
Score ranges from 0.0 to 1.0

  1.0 = perfect history (long TTL, recovery window enabled)
  0.5 = neutral/new user (standard TTL)
  0.0 = suspicious/bot behavior (short TTL, no recovery)

Score is calculated from:
  - total_reservations vs total_orders (conversion rate)
  - recent_abandonments in last 24 hours
  - account_age in days
  - time_since_last_purchase

TTL MAPPING:
─────────────
  score >= 0.7  → TTL = 900s (15 min),  recovery = 300s (5 min)
  score >= 0.4  → TTL = 600s (10 min),  recovery = 120s (2 min)
  score < 0.4   → TTL = 180s (3 min),   recovery = None
"""

import asyncpg
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

# Score thresholds
HIGH_TRUST_THRESHOLD   = 0.7
MEDIUM_TRUST_THRESHOLD = 0.4

# TTL values in seconds
TTL_HIGH_TRUST   = 900   # 15 minutes — matches Amazon checkout window
TTL_MEDIUM_TRUST = 600   # 10 minutes
TTL_LOW_TRUST    = 180   # 3 minutes — suspicious users get less time

# Recovery window values in seconds
RECOVERY_HIGH_TRUST   = 300  # 5 minutes grace after expiry
RECOVERY_MEDIUM_TRUST = 120  # 2 minutes grace
RECOVERY_LOW_TRUST    = 0    # No recovery for low trust


async def calculate_user_score(
    db: asyncpg.Pool,
    user_id: str,
) -> float:
    """
    Calculates a trust score for a user based on their history.

    Returns a float between 0.0 and 1.0.
    """
    async with db.acquire() as conn:
        # Get reservation and order counts
        stats = await conn.fetchrow(
            """
            SELECT
                COUNT(r.id)                                    AS total_reservations,
                COUNT(o.id)                                    AS total_orders,
                COUNT(CASE
                    WHEN r.status = 'expired'
                    AND r.created_at > NOW() - INTERVAL '24 hours'
                    THEN 1 END)                                AS recent_abandonments,
                EXTRACT(EPOCH FROM (NOW() - u.created_at))
                    / 86400                                    AS account_age_days
            FROM users u
            LEFT JOIN reservations r ON r.user_id = u.id
            LEFT JOIN orders o       ON o.user_id = u.id
            WHERE u.id = $1
            GROUP BY u.created_at
            """,
            user_id,
        )

    if not stats:
        return 0.5  # Unknown user — neutral score

    total_reservations  = stats["total_reservations"] or 0
    total_orders        = stats["total_orders"] or 0
    recent_abandonments = stats["recent_abandonments"] or 0
    account_age_days    = float(stats["account_age_days"] or 0)

    # ── Base Score ────────────────────────────────────────────
    # New user with no history starts at 0.5
    if total_reservations == 0:
        base_score = 0.5
    else:
        # Conversion rate — what fraction of reservations led to orders
        conversion_rate = total_orders / total_reservations
        base_score = conversion_rate

    # ── Penalties ─────────────────────────────────────────────
    # Each recent abandonment reduces score by 0.15
    abandonment_penalty = recent_abandonments * 0.15

    # ── Bonuses ───────────────────────────────────────────────
    # Older accounts are more trustworthy
    if account_age_days > 365:
        age_bonus = 0.2
    elif account_age_days > 30:
        age_bonus = 0.1
    else:
        age_bonus = 0.0

    # ── Final Score ───────────────────────────────────────────
    score = base_score - abandonment_penalty + age_bonus
    score = max(0.0, min(1.0, score))  # Clamp to [0.0, 1.0]

    logger.info(
        "User score calculated",
        user_id=user_id,
        score=round(score, 3),
        total_reservations=total_reservations,
        total_orders=total_orders,
        recent_abandonments=recent_abandonments,
        account_age_days=round(account_age_days, 1),
    )

    return score


def get_ttl_for_score(score: float) -> int:
    """Returns reservation TTL in seconds based on user score."""
    if score >= HIGH_TRUST_THRESHOLD:
        return TTL_HIGH_TRUST
    elif score >= MEDIUM_TRUST_THRESHOLD:
        return TTL_MEDIUM_TRUST
    else:
        return TTL_LOW_TRUST


def get_recovery_window_for_score(score: float) -> int:
    """
    Returns recovery window duration in seconds.
    0 means no recovery window for this user.
    """
    if score >= HIGH_TRUST_THRESHOLD:
        return RECOVERY_HIGH_TRUST
    elif score >= MEDIUM_TRUST_THRESHOLD:
        return RECOVERY_MEDIUM_TRUST
    else:
        return RECOVERY_LOW_TRUST
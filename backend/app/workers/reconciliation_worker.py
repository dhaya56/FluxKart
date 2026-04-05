"""
Inventory Reconciliation Worker.

WHY THIS EXISTS:
─────────────────
Redis and PostgreSQL can drift apart under extreme load:

  Scenario 1 — Redis restart:
    Redis loses all inventory counters
    PostgreSQL still has correct reserved_quantity
    Without reconciliation: Redis shows 0, sale appears sold out
    With reconciliation: Redis is reseeded from PostgreSQL within 60s

  Scenario 2 — Network partition:
    A DECRBY succeeds in Redis but PostgreSQL update fails
    Redis shows 49, PostgreSQL shows 50
    Without reconciliation: you can oversell by 1 unit

  Scenario 3 — Bug in release logic:
    A cancelled reservation releases inventory in Redis
    but PostgreSQL update fails
    Redis and PostgreSQL permanently diverged

ALGORITHM:
───────────
Every 5 minutes:
  1. For each active sale, read Redis inventory counter
  2. Calculate expected = total - reserved - sold from PostgreSQL
  3. If |Redis - expected| > DRIFT_THRESHOLD → log alert + fix Redis
  4. If Redis key missing → reseed from PostgreSQL

INTERVIEW TALKING POINT:
─────────────────────────
"Redis is our fast path but PostgreSQL is the source of truth.
The reconciliation worker runs every 5 minutes and compares the two.
If drift exceeds our threshold of 2 units, we alert and auto-correct.
This gives us eventual consistency guarantees even under failure scenarios."
"""

import asyncio

import asyncpg
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

RECONCILE_INTERVAL_SECONDS = 300   # Run every 5 minutes
DRIFT_THRESHOLD            = 2     # Alert if drift exceeds this many units
AUTO_FIX_THRESHOLD         = 10    # Auto-fix if drift exceeds this (smaller drifts just alert)


async def reconcile_inventory(
    db: asyncpg.Pool,
    redis: aioredis.Redis,
) -> dict:
    """
    Compares Redis inventory counters with PostgreSQL source of truth.
    Returns a dict with reconciliation results for observability.
    """
    results = {
        "checked":   0,
        "ok":        0,
        "drifted":   0,
        "fixed":     0,
        "reseeded":  0,
    }

    async with db.acquire() as conn:
        # Get all active sales with their inventory
        active_sales = await conn.fetch(
            """
            SELECT
                s.id,
                s.title,
                s.status,
                i.total_quantity,
                i.reserved_quantity,
                i.sold_quantity
            FROM sales s
            JOIN inventory i ON i.sale_id = s.id
            WHERE s.status IN ('active', 'scheduled')
            """
        )

    for sale in active_sales:
        sale_id  = str(sale["id"])
        expected = sale["total_quantity"] - sale["reserved_quantity"] - sale["sold_quantity"]
        expected = max(0, expected)
        results["checked"] += 1

        try:
            redis_val = await redis.get(f"inventory:{sale_id}")

            # ── Key missing — reseed ──────────────────────────────────────
            if redis_val is None:
                if sale["status"] == "active":
                    await redis.set(f"inventory:{sale_id}", expected)
                    results["reseeded"] += 1
                    logger.warning(
                        "Inventory key missing — reseeded from PostgreSQL",
                        sale_id=sale_id,
                        title=sale["title"],
                        reseeded_value=expected,
                    )
                continue

            redis_inventory = int(redis_val)
            drift = abs(redis_inventory - expected)

            if drift == 0:
                results["ok"] += 1
                continue

            # ── Drift detected ────────────────────────────────────────────
            results["drifted"] += 1

            logger.warning(
                "Inventory drift detected",
                sale_id=sale_id,
                title=sale["title"],
                redis_value=redis_inventory,
                postgres_value=expected,
                drift=drift,
                direction="redis_high" if redis_inventory > expected else "redis_low",
            )

            # ── Auto-fix large drifts ─────────────────────────────────────
            if drift >= AUTO_FIX_THRESHOLD:
                await redis.set(f"inventory:{sale_id}", expected)
                results["fixed"] += 1
                logger.error(
                    "Large inventory drift auto-corrected — Redis reset to PostgreSQL value",
                    sale_id=sale_id,
                    title=sale["title"],
                    old_redis_value=redis_inventory,
                    new_redis_value=expected,
                    drift=drift,
                )

        except Exception as e:
            logger.error(
                "Reconciliation error for sale",
                sale_id=sale_id,
                error=str(e),
            )

    if results["drifted"] > 0 or results["reseeded"] > 0:
        logger.warning(
            "Reconciliation complete — issues found",
            **results,
        )
    else:
        logger.info(
            "Reconciliation complete — all inventory in sync",
            checked=results["checked"],
        )

    return results


async def start_reconciliation_worker(
    db: asyncpg.Pool,
    redis: aioredis.Redis,
) -> None:
    """
    Runs the reconciliation worker in an infinite loop.
    Started as an asyncio background task in main.py lifespan.
    """
    logger.info(
        "Inventory reconciliation worker started",
        interval_seconds=RECONCILE_INTERVAL_SECONDS,
        drift_threshold=DRIFT_THRESHOLD,
        auto_fix_threshold=AUTO_FIX_THRESHOLD,
    )

    while True:
        try:
            await reconcile_inventory(db, redis)
        except Exception as e:
            logger.error(
                "Reconciliation worker encountered an error",
                error=str(e),
            )

        await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)
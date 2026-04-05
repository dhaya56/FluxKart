"""
Graceful Degradation — Redis Fallback to PostgreSQL.

WHY THIS EXISTS:
─────────────────
Redis is our fast path for inventory management.
But Redis can go down — network blip, container restart, OOM kill.

Without fallback:
  Redis goes down → inventory check fails → all reservations fail
  Sale is ruined, revenue lost

With fallback:
  Redis goes down → automatically switch to PostgreSQL locking
  Slower (50ms vs 1ms) but 100% correct
  Sale continues, just at reduced throughput

FALLBACK MECHANISM:
────────────────────
PostgreSQL SELECT FOR UPDATE locks the inventory row.
Only one transaction can hold the lock at a time.
Prevents overselling with the same correctness guarantee as Redis.

Trade-off:
  Redis:      1ms, 10,000 concurrent ops/sec
  PostgreSQL: 50ms, ~200 concurrent ops/sec (limited by lock contention)

This is acceptable degradation — system slows but never fails.
"""

import asyncpg
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


async def try_reserve_with_fallback(
    db: asyncpg.Pool,
    redis: aioredis.Redis,
    sale_id: str,
    reservation_id: str,
    user_id: str,
    quantity: int,
    ttl_seconds: int,
) -> bool:
    """
    Attempts Redis reservation first.
    Falls back to PostgreSQL if Redis is unavailable.

    Returns:
        True  → reservation successful
        False → not enough inventory
    """
    # ── Try Redis first (fast path) ───────────────────────────────────────────
    try:
        from app.services.inventory_service import InventoryService
        inventory_svc = InventoryService(redis)

        # Test Redis is responsive with a quick ping
        await redis.ping()

        result = await inventory_svc.try_reserve_inventory(
            sale_id=sale_id,
            reservation_id=reservation_id,
            user_id=user_id,
            quantity=quantity,
            ttl_seconds=ttl_seconds,
        )

        return result

    except Exception as redis_error:
        # Redis failed — log and fall back to PostgreSQL
        logger.warning(
            "Redis unavailable — falling back to PostgreSQL locking",
            error=str(redis_error),
            sale_id=sale_id,
        )

    # ── PostgreSQL fallback (slow path) ───────────────────────────────────────
    return await _reserve_with_db_lock(db, sale_id, quantity)


async def _reserve_with_db_lock(
    db: asyncpg.Pool,
    sale_id: str,
    quantity: int,
) -> bool:
    """
    Reserves inventory using PostgreSQL pessimistic locking.

    SELECT FOR UPDATE locks the inventory row.
    Only one transaction can modify it at a time.
    Prevents overselling with strong consistency guarantee.

    Slower than Redis but correct under all conditions.
    """
    async with db.acquire() as conn:
        async with conn.transaction():
            # Lock the inventory row for this sale
            row = await conn.fetchrow(
                """
                SELECT
                    id,
                    total_quantity,
                    reserved_quantity,
                    sold_quantity,
                    total_quantity - reserved_quantity - sold_quantity
                        AS available
                FROM inventory
                WHERE sale_id = $1
                FOR UPDATE
                """,
                sale_id,
            )

            if not row:
                logger.error(
                    "Inventory row not found for sale",
                    sale_id=sale_id,
                )
                return False

            available = row["available"]

            if available < quantity:
                logger.info(
                    "Insufficient inventory in DB fallback",
                    sale_id=sale_id,
                    available=available,
                    requested=quantity,
                )
                return False

            # Atomically increment reserved quantity
            await conn.execute(
                """
                UPDATE inventory
                SET
                    reserved_quantity = reserved_quantity + $1,
                    updated_at = NOW()
                WHERE sale_id = $2
                """,
                quantity,
                sale_id,
            )

            logger.info(
                "Inventory reserved via PostgreSQL fallback",
                sale_id=sale_id,
                quantity=quantity,
                remaining=available - quantity,
            )

            return True
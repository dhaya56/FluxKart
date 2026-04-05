"""
Reservation Expiry Worker.

WHY THIS EXISTS:
─────────────────
When a user reserves inventory, we hold it for 10 minutes (RESERVATION_TTL).
If they don't complete payment, the inventory must be released back
so other users can buy it.

FIXES APPLIED:
──────────────
1. Inner loop — processes ALL expired reservations before sleeping.
   Old: process 100 → sleep 60s → process 100 → sleep 60s (50 min for 5000!)
   New: process 100 → process 100 → ... → 0 rows → sleep 60s

2. Bulk queries — 3 queries for 100 rows instead of 400.
   Old: 4 queries per row × 100 rows = 400 round trips per batch
   New: 1 bulk UPDATE reservations + 1 bulk UPDATE orders +
        per-sale inventory updates (grouped by sale_id)
"""

import asyncio
from collections import defaultdict

import asyncpg
import redis.asyncio as aioredis
import structlog

from app.services.inventory_service import InventoryService
from app.utils.metrics import INVENTORY_RELEASES, RESERVATIONS_EXPIRED

logger = structlog.get_logger()

EXPIRY_CHECK_INTERVAL_SECONDS = 60
BATCH_SIZE                    = 100


async def expire_reservations(
    db: asyncpg.Pool,
    redis: aioredis.Redis,
) -> int:
    """
    Finds and expires all overdue pending/confirmed reservations.

    INNER LOOP: keeps processing batches until no rows remain.
    BULK QUERIES: groups updates to minimize DB round trips.
    """
    inventory_svc = InventoryService(redis)
    total_expired = 0

    while True:
        batch_count = await _expire_batch(db, redis, inventory_svc)
        total_expired += batch_count

        if batch_count < BATCH_SIZE:
            # Fewer than batch size returned = no more rows to process
            break

    return total_expired


async def _expire_batch(
    db: asyncpg.Pool,
    redis: aioredis.Redis,
    inventory_svc: InventoryService,
) -> int:
    """
    Processes one batch of up to 100 expired reservations.
    Uses bulk queries — 3-4 DB round trips for entire batch.
    """
    async with db.acquire() as conn:
        async with conn.transaction():

            # ── Step 1: Fetch batch ───────────────────────────────────────
            expired_rows = await conn.fetch(
                """
                SELECT id, sale_id, quantity
                FROM reservations
                WHERE status IN ('pending', 'confirmed')
                AND expires_at < NOW()
                ORDER BY expires_at ASC
                LIMIT $1
                FOR UPDATE SKIP LOCKED
                """,
                BATCH_SIZE,
            )

            if not expired_rows:
                return 0

            # ── Step 2: Collect IDs for bulk operations ───────────────────
            reservation_ids = [row["id"] for row in expired_rows]

            # Group by sale_id for inventory updates
            # sale_id → {quantity_to_release, is_active}
            sale_groups = defaultdict(lambda: {"quantity": 0, "is_active": False})
            for row in expired_rows:
                sale_id = str(row["sale_id"])
                sale_groups[sale_id]["quantity"] += row["quantity"]

            # ── Step 3: Bulk update reservations → expired ────────────────
            await conn.execute(
                """
                UPDATE reservations
                SET status     = 'expired',
                    updated_at = NOW()
                WHERE id = ANY($1)
                """,
                reservation_ids,
            )

            # ── Step 4: Bulk update linked orders → failed ────────────────
            await conn.execute(
                """
                UPDATE orders
                SET status     = 'failed',
                    updated_at = NOW()
                WHERE reservation_id = ANY($1)
                AND status != 'paid'
                """,
                reservation_ids,
            )

            # ── Step 5: Check sale statuses in bulk ───────────────────────
            sale_id_list = list(sale_groups.keys())
            sale_rows    = await conn.fetch(
                """
                SELECT id::text, status
                FROM sales
                WHERE id::text = ANY($1)
                """,
                sale_id_list,
            )
            sale_status_map = {str(row["id"]): row["status"] for row in sale_rows}

            for sale_id in sale_groups:
                sale_groups[sale_id]["is_active"] = (
                    sale_status_map.get(sale_id) == "active"
                )

            # ── Step 6: Bulk update PostgreSQL inventory ──────────────────
            # One UPDATE per sale_id (grouped) — not per reservation
            for sale_id, data in sale_groups.items():
                await conn.execute(
                    """
                    UPDATE inventory
                    SET reserved_quantity = GREATEST(0, reserved_quantity - $1),
                        updated_at        = NOW()
                    WHERE sale_id = $2::uuid
                    """,
                    data["quantity"],
                    sale_id,
                )

        # ── Step 7: Release Redis inventory (outside transaction) ─────────
        # Done after transaction commits to avoid holding locks during Redis I/O
        for row in expired_rows:
            sale_id        = str(row["sale_id"])
            reservation_id = str(row["id"])
            quantity       = row["quantity"]

            if sale_groups[sale_id]["is_active"]:
                try:
                    await inventory_svc.release_inventory(
                        sale_id=sale_id,
                        reservation_id=reservation_id,
                        quantity=quantity,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to release Redis inventory",
                        reservation_id=reservation_id,
                        error=str(e),
                    )

    expired_count = len(expired_rows)

    if expired_count > 0:
        RESERVATIONS_EXPIRED.inc(expired_count)
        INVENTORY_RELEASES.inc(expired_count)
        logger.info(
            "Expiry batch complete",
            expired_count=expired_count,
        )

    return expired_count


async def expire_sales(db: asyncpg.Pool) -> int:
    """
    Auto-completes active sales whose ends_at has passed.
    """
    async with db.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE sales
            SET status     = 'completed',
                updated_at = NOW()
            WHERE status = 'active'
            AND ends_at < NOW()
            """
        )

    count = int(result.split()[-1])
    if count > 0:
        logger.info("Sales auto-completed by expiry worker", count=count)
    return count


async def activate_scheduled_sales(db: asyncpg.Pool, redis: aioredis.Redis) -> int:
    """
    Auto-activates scheduled sales whose starts_at has passed.
    """
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE sales
            SET status     = 'active',
                updated_at = NOW()
            WHERE status = 'scheduled'
            AND starts_at <= NOW()
            RETURNING id
            """
        )

        count = len(rows)
        if count > 0:
            for row in rows:
                sale_id = str(row["id"])
                inv = await conn.fetchrow(
                    """
                    SELECT total_quantity, reserved_quantity, sold_quantity
                    FROM inventory WHERE sale_id = $1
                    """,
                    row["id"],
                )
                if inv:
                    available = inv["total_quantity"] - inv["reserved_quantity"] - inv["sold_quantity"]
                    try:
                        await redis.set(f"inventory:{sale_id}", available)
                    except Exception:
                        pass

            logger.info("Sales auto-activated by expiry worker", count=count)

    return count


async def start_expiry_worker(
    db: asyncpg.Pool,
    redis: aioredis.Redis,
) -> None:
    """
    Runs the expiry worker in an infinite loop.
    Now in dedicated worker process — no event loop competition with HTTP.
    """
    logger.info(
        "Expiry worker started",
        interval_seconds=EXPIRY_CHECK_INTERVAL_SECONDS,
        batch_size=BATCH_SIZE,
    )

    while True:
        try:
            await activate_scheduled_sales(db, redis)
            expired_reservations = await expire_reservations(db, redis)
            expired_sales        = await expire_sales(db)

            if expired_reservations > 0 or expired_sales > 0:
                logger.info(
                    "Expiry worker run complete",
                    expired_reservations=expired_reservations,
                    expired_sales=expired_sales,
                )

        except Exception as e:
            logger.error("Expiry worker error", error=str(e))

        await asyncio.sleep(EXPIRY_CHECK_INTERVAL_SECONDS)
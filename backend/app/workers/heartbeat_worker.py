"""
Queue Heartbeat Worker.

WHY THIS EXISTS:
─────────────────
When a user joins the waiting queue and closes their browser,
they still occupy a queue position. Everyone behind them waits
for a ghost user who will never complete their reservation.

This is the "queue squatting" problem — different from reservation
squatting. A user squats in the queue itself without ever reserving.

HOW IT WORKS:
──────────────
When user enters queue → frontend pings heartbeat every 15 seconds:
  POST /reservations/queue-heartbeat?sale_id=X

This worker runs every 30 seconds:
  1. Find all users in all active queues
  2. Check Redis heartbeat key for each user
  3. If no heartbeat in 30 seconds → remove from queue
  4. Position of everyone behind them improves immediately

HEARTBEAT KEY:
  queue_hb:{sale_id}:{user_id}  → "1", TTL = 30 seconds

INTERVIEW TALKING POINT:
─────────────────────────
"We detect abandoned queue positions using a heartbeat mechanism.
The frontend pings every 15 seconds. If we don't hear from a user
in 30 seconds, we remove them from the queue. This keeps the queue
accurate and prevents users from seeing inflated wait times due to
ghost users. It's the same pattern used by Ticketmaster."
"""

import asyncio

import asyncpg
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

HEARTBEAT_CHECK_INTERVAL = 30   # seconds between checks
HEARTBEAT_TTL            = 30   # seconds — must be > frontend ping interval (15s)


def heartbeat_key(sale_id: str, user_id: str) -> str:
    return f"queue_hb:{sale_id}:{user_id}"


async def refresh_heartbeat(
    redis: aioredis.Redis,
    sale_id: str,
    user_id: str,
) -> None:
    """
    Called by the heartbeat endpoint when frontend pings.
    Refreshes the TTL — user stays in queue.
    """
    await redis.set(heartbeat_key(sale_id, user_id), "1", ex=HEARTBEAT_TTL)


async def remove_ghost_users(
    redis: aioredis.Redis,
) -> int:
    """
    Scans all active queues and removes users with no heartbeat.
    Returns count of ghost users removed.
    """
    removed_count = 0

    try:
        # Find all queue keys
        queue_keys = await redis.keys("queue:*")

        for queue_key in queue_keys:
            # queue_key is like b"queue:sale-uuid"
            if isinstance(queue_key, bytes):
                queue_key = queue_key.decode()

            sale_id = queue_key.replace("queue:", "")

            # Get all users in this queue
            members = await redis.zrange(queue_key, 0, -1)

            for member in members:
                if isinstance(member, bytes):
                    member = member.decode()

                # Check if user has active heartbeat
                hb_key  = heartbeat_key(sale_id, member)
                alive   = await redis.exists(hb_key)

                if not alive:
                    # No heartbeat — ghost user, remove from queue
                    await redis.zrem(queue_key, member)
                    removed_count += 1

                    logger.info(
                        "Ghost user removed from queue — no heartbeat",
                        sale_id=sale_id,
                        user_id=member,
                    )

    except Exception as e:
        logger.error("Error scanning queues for ghost users", error=str(e))

    return removed_count


async def start_heartbeat_worker(
    redis: aioredis.Redis,
) -> None:
    """
    Runs the heartbeat worker in an infinite loop.
    Started as an asyncio background task in main.py lifespan.
    """
    logger.info(
        "Queue heartbeat worker started",
        check_interval_seconds=HEARTBEAT_CHECK_INTERVAL,
        heartbeat_ttl_seconds=HEARTBEAT_TTL,
    )

    while True:
        try:
            removed = await remove_ghost_users(redis)
            if removed > 0:
                logger.info(
                    "Heartbeat worker removed ghost users",
                    removed_count=removed,
                )
        except Exception as e:
            logger.error("Heartbeat worker error", error=str(e))

        await asyncio.sleep(HEARTBEAT_CHECK_INTERVAL)
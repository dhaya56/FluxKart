"""
Staggered Admission Worker.

PURPOSE:
─────────
Solves the thundering herd problem at T=0.

Without this:
  Sale starts at 12:00:00
  50,000 pre-registered users all hit /reserve at 12:00:00.000
  Server receives 50,000 requests in < 1 second
  Connection pools exhaust, latency spikes, some requests fail

With this:
  Sale starts at 12:00:00
  Worker fires at 12:00:00
  Admits 50 users every 100ms → 500 users/second controlled rate
  Each user gets an admission token valid for 60 seconds
  Users poll /sales/{id}/admission-status
  When admitted=true → they call /reserve
  Server receives steady 500 requests/second instead of spike

FAIRNESS:
──────────
Pre-registered users are admitted in FIFO order (earliest registration first).
This is the fairest possible system — first to register = first to buy.

ADMISSION TOKEN:
─────────────────
Stored in Redis: admission:{sale_id}:{user_id} → TTL 60 seconds
User has 60 seconds after admission to complete their reservation.
If they miss the window they go to the back of the regular queue.

WORKER LIFECYCLE:
──────────────────
Started as asyncio task when a sale becomes active.
Runs until all pre-registered users are admitted or sale ends.
One worker per active sale.
"""

import asyncio

import asyncpg
import redis.asyncio as aioredis
import structlog

from app.db.queries.preregistrations import (
    get_preregistrations_for_sale,
    mark_admitted,
)

logger = structlog.get_logger()

# Admission rate control
BATCH_SIZE           = 50    # Users admitted per batch
BATCH_INTERVAL_MS    = 100   # Milliseconds between batches
ADMISSION_TOKEN_TTL  = 60    # Seconds user has to reserve after admission
POLL_INTERVAL_S      = 5     # Seconds between checks for new pre-registrations


def _admission_key(sale_id: str, user_id: str) -> str:
    return f"admission:{sale_id}:{user_id}"


async def admit_batch(
    db: asyncpg.Pool,
    redis: aioredis.Redis,
    sale_id: str,
) -> int:
    """
    Admits the next batch of pre-registered users.

    Steps:
    1. Fetch next BATCH_SIZE waiting users (FIFO order)
    2. Write admission token to Redis for each
    3. Mark as admitted in PostgreSQL
    4. Return count of admitted users

    Returns:
        Number of users admitted in this batch.
    """
    # Get next batch of waiting users
    waiting = await get_preregistrations_for_sale(
        db, sale_id, limit=BATCH_SIZE
    )

    if not waiting:
        return 0

    admitted_count = 0

    for registration in waiting:
        user_id = str(registration["user_id"])

        # Write admission token to Redis
        # User has ADMISSION_TOKEN_TTL seconds to call /reserve
        await redis.set(
            _admission_key(sale_id, user_id),
            "1",
            ex=ADMISSION_TOKEN_TTL,
        )

        # Mark admitted in PostgreSQL
        await mark_admitted(db, user_id, sale_id)

        admitted_count += 1

    logger.info(
        "Admission batch complete",
        sale_id=sale_id,
        admitted_count=admitted_count,
    )

    return admitted_count


async def run_admission_worker(
    db: asyncpg.Pool,
    redis: aioredis.Redis,
    sale_id: str,
    sale_ends_at,
) -> None:
    """
    Runs the staggered admission worker for a specific sale.

    Admits users in batches until:
    - All pre-registered users have been admitted, OR
    - The sale ends

    After all pre-registered users are admitted, the worker
    polls periodically for late pre-registrations and admits
    them immediately.
    """
    from datetime import datetime, timezone

    logger.info(
        "Admission worker started",
        sale_id=sale_id,
        batch_size=BATCH_SIZE,
        batch_interval_ms=BATCH_INTERVAL_MS,
    )

    while True:
        try:
            # Check if sale has ended
            now = datetime.now(timezone.utc)
            ends_at = sale_ends_at if sale_ends_at.tzinfo else sale_ends_at.replace(tzinfo=timezone.utc)
            if ends_at < now:
                logger.info(
                    "Sale ended — admission worker stopping",
                    sale_id=sale_id,
                )
                break

            # Admit next batch
            admitted = await admit_batch(db, redis, sale_id)

            if admitted == BATCH_SIZE:
                # Full batch admitted — there may be more waiting
                # Wait the interval then admit next batch
                await asyncio.sleep(BATCH_INTERVAL_MS / 1000)
            else:
                # Fewer than batch size — caught up with queue
                # Poll less frequently
                await asyncio.sleep(POLL_INTERVAL_S)

        except asyncio.CancelledError:
            logger.info(
                "Admission worker cancelled",
                sale_id=sale_id,
            )
            break

        except Exception as e:
            logger.error(
                "Admission worker error",
                sale_id=sale_id,
                error=str(e),
            )
            await asyncio.sleep(5)  # Brief pause before retry


# ── Worker Registry ───────────────────────────────────────────────────────────
# Tracks running admission workers by sale_id
# Prevents duplicate workers for the same sale

_active_workers: dict[str, asyncio.Task] = {}


async def start_admission_worker(
    db: asyncpg.Pool,
    redis: aioredis.Redis,
    sale_id: str,
    sale_ends_at,
) -> None:
    """
    Starts an admission worker for a sale if not already running.
    Called when a sale transitions to 'active' status.
    """
    if sale_id in _active_workers:
        task = _active_workers[sale_id]
        if not task.done():
            logger.info(
                "Admission worker already running",
                sale_id=sale_id,
            )
            return

    task = asyncio.create_task(
        run_admission_worker(db, redis, sale_id, sale_ends_at),
        name=f"admission_worker_{sale_id}",
    )
    _active_workers[sale_id] = task

    logger.info(
        "Admission worker launched",
        sale_id=sale_id,
    )


async def stop_admission_worker(sale_id: str) -> None:
    """Stops the admission worker for a sale."""
    if sale_id in _active_workers:
        task = _active_workers.pop(sale_id)
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("Admission worker stopped", sale_id=sale_id)
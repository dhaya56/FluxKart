"""
Outbox pattern DB queries.

The outbox worker uses these to poll unpublished events
and mark them published after successful RabbitMQ delivery.
"""

import json
from datetime import datetime, timezone

import asyncpg


async def create_outbox_event(
    conn: asyncpg.Connection,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict,
) -> dict:
    """
    Inserts an outbox event using an EXISTING connection (not a new pool acquire).

    CRITICAL: Must be called with the same connection used for the reservation
    INSERT — this ensures both writes are in the same transaction.

    Usage:
        async with db.acquire() as conn:
            async with conn.transaction():
                reservation = await conn.fetchrow("INSERT INTO reservations ...")
                await create_outbox_event(conn, ...)   ← same conn, same tx
    """
    row = await conn.fetchrow(
        """
        INSERT INTO outbox_events (
            aggregate_type,
            aggregate_id,
            event_type,
            payload
        )
        VALUES ($1, $2, $3, $4::jsonb)
        RETURNING *
        """,
        aggregate_type,
        aggregate_id,
        event_type,
        json.dumps(payload),
    )
    return dict(row)


async def get_pending_outbox_events(
    db: asyncpg.Pool,
    batch_size: int = 50,
) -> list[dict]:
    """
    Fetches unpublished outbox events ordered by created_at.
    Uses partial index idx_outbox_unpublished — only scans unpublished rows.
    Limits to batch_size to avoid memory spike on large backlogs.
    """
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM outbox_events
            WHERE published = FALSE
            ORDER BY created_at ASC
            LIMIT $1
            """,
            batch_size,
        )
    return [dict(row) for row in rows]


async def mark_event_published(
    db: asyncpg.Pool,
    event_id: str,
) -> None:
    """Marks a single outbox event as successfully published."""
    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE outbox_events
            SET published    = TRUE,
                published_at = NOW()
            WHERE id = $1
            """,
            event_id,
        )


async def mark_event_failed(
    db: asyncpg.Pool,
    event_id: str,
    error: str,
) -> None:
    """
    Increments retry count and records last error.
    Event stays unpublished — worker will retry on next poll.
    """
    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE outbox_events
            SET retry_count = retry_count + 1,
                last_error  = $1
            WHERE id = $2
            """,
            error,
            event_id,
        )
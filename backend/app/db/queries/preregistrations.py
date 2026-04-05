"""
Raw SQL queries for the preregistrations table.
"""

import asyncpg


async def create_preregistration(
    db: asyncpg.Pool,
    user_id: str,
    sale_id: str,
) -> dict:
    """
    Registers a user's interest in a sale.
    Raises on duplicate — user can only pre-register once per sale.
    """
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO preregistrations (user_id, sale_id)
            VALUES ($1, $2)
            RETURNING *
            """,
            user_id,
            sale_id,
        )
    return dict(row)


async def get_preregistration(
    db: asyncpg.Pool,
    user_id: str,
    sale_id: str,
) -> dict | None:
    """Fetches a single preregistration."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM preregistrations
            WHERE user_id = $1 AND sale_id = $2
            """,
            user_id,
            sale_id,
        )
    return dict(row) if row else None


async def get_preregistrations_for_sale(
    db: asyncpg.Pool,
    sale_id: str,
    limit: int = 100,
) -> list[dict]:
    """
    Fetches waiting preregistrations ordered by registration time.
    Used by the staggered admission worker to admit users in FIFO order.
    """
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM preregistrations
            WHERE sale_id = $1
            AND status = 'waiting'
            ORDER BY registered_at ASC
            LIMIT $2
            """,
            sale_id,
            limit,
        )
    return [dict(r) for r in rows]


async def mark_admitted(
    db: asyncpg.Pool,
    user_id: str,
    sale_id: str,
) -> None:
    """Marks a preregistration as admitted."""
    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE preregistrations
            SET status = 'admitted', admitted_at = NOW()
            WHERE user_id = $1 AND sale_id = $2
            """,
            user_id,
            sale_id,
        )


async def get_preregistration_count(
    db: asyncpg.Pool,
    sale_id: str,
) -> int:
    """Returns total number of pre-registered users for a sale."""
    async with db.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT COUNT(*) FROM preregistrations
            WHERE sale_id = $1
            """,
            sale_id,
        )
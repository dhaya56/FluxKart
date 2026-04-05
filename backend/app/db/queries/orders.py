"""
Raw SQL queries for reservations and orders tables.
"""

import asyncpg


async def get_reservation_by_idempotency_key(
    db: asyncpg.Pool,
    idempotency_key: str
) -> dict | None:
    """
    Check if a reservation already exists for this idempotency key.
    This is the core of exactly-once reservation logic.
    If the client retries with the same key, we return the existing reservation.
    """
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM reservations WHERE idempotency_key = $1",
            idempotency_key,
        )
    return dict(row) if row else None


async def create_reservation(db: asyncpg.Pool, data: dict) -> dict:
    """Insert a new reservation record."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO reservations (
                user_id, sale_id, quantity,
                idempotency_key, expires_at
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            data["user_id"],
            data["sale_id"],
            data["quantity"],
            data["idempotency_key"],
            data["expires_at"],
        )
    return dict(row)


async def get_reservation_by_id(
    db: asyncpg.Pool,
    reservation_id: str
) -> dict | None:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM reservations WHERE id = $1",
            reservation_id,
        )
    return dict(row) if row else None


async def update_reservation_status(
    db: asyncpg.Pool,
    reservation_id: str,
    status: str
) -> dict | None:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE reservations
            SET status = $1, updated_at = NOW()
            WHERE id = $2
            RETURNING *
            """,
            status,
            reservation_id,
        )
    return dict(row) if row else None


async def create_order(db: asyncpg.Pool, data: dict) -> dict:
    """
    Creates an order from a confirmed reservation.
    Called by the RabbitMQ consumer after successful payment.
    """
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO orders (
                user_id, sale_id, reservation_id,
                quantity, unit_price, total_price
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            data["user_id"],
            data["sale_id"],
            data["reservation_id"],
            data["quantity"],
            data["unit_price"],
            data["total_price"],
        )
    return dict(row)


async def get_orders_by_user(
    db: asyncpg.Pool,
    user_id: str
) -> list[dict]:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM orders
            WHERE user_id = $1
            ORDER BY created_at DESC
            """,
            user_id,
        )
    return [dict(row) for row in rows]


async def update_reservation_quantity(
    db: asyncpg.Pool,
    reservation_id: str,
    new_quantity: int,
    new_expires_at,
) -> dict:
    """
    Updates reservation quantity and resets TTL in PostgreSQL.
    Called after successful Redis quantity modification.
    """
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE reservations
            SET
                quantity   = $1,
                expires_at = $2,
                updated_at = NOW()
            WHERE id = $3
            AND status = 'pending'
            RETURNING *
            """,
            new_quantity,
            new_expires_at,
            reservation_id,
        )
    if not row:
        raise ValueError(
            f"Reservation {reservation_id} not found or not pending"
        )
    return dict(row)


async def get_reservation_by_id_and_user(
    db: asyncpg.Pool,
    reservation_id: str,
    user_id: str,
) -> dict | None:
    """
    Fetches a reservation by ID, verifying it belongs to the user.
    Returns any status — pending, confirmed, expired, cancelled.
    """
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT r.*, s.sale_price, s.total_quantity
            FROM reservations r
            JOIN sales s ON s.id = r.sale_id
            WHERE r.id = $1
            AND r.user_id = $2
            """,
            reservation_id,
            user_id,
        )
    return dict(row) if row else None


async def confirm_reservation(
    db: asyncpg.Pool,
    reservation_id: str,
) -> None:
    """
    Marks a reservation as confirmed after order is successfully created.

    WHY THIS MATTERS:
    A confirmed reservation means payment is being processed.
    The inventory is permanently held — expiry worker will not release it.
    This prevents the edge case where:
      - Order created successfully
      - Expiry worker runs before confirmation
      - Inventory released despite successful order
    """
    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE reservations
            SET status     = 'confirmed',
                updated_at = NOW()
            WHERE id     = $1
            AND status   = 'pending'
            """,
            reservation_id,
        )


async def get_reservation_by_id(
    db: asyncpg.Pool,
    reservation_id: str,
) -> dict | None:
    """Fetches a reservation by ID."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM reservations WHERE id = $1",
            reservation_id,
        )
    return dict(row) if row else None


async def get_pending_reservation_by_id_and_user(
    db: asyncpg.Pool,
    reservation_id: str,
    user_id: str,
) -> dict | None:
    """
    Fetches a reservation only if status is pending.
    Used for quantity modification — cannot modify confirmed reservations.
    """
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT r.*, s.sale_price, s.total_quantity
            FROM reservations r
            JOIN sales s ON s.id = r.sale_id
            WHERE r.id = $1
            AND r.user_id = $2
            AND r.status = 'pending'
            """,
            reservation_id,
            user_id,
        )
    return dict(row) if row else None
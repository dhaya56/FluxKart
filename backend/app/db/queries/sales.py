"""
Raw SQL queries for the sales and inventory tables.
"""

import asyncpg


async def create_sale(db: asyncpg.Pool, data: dict) -> dict:
    """
    Creates a sale and its inventory record atomically.
    """
    async with db.acquire() as conn:
        async with conn.transaction():
            sale = await conn.fetchrow(
                """
                INSERT INTO sales (
                    title, description, product_name,
                    original_price, sale_price,
                    total_quantity, starts_at, ends_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING *
                """,
                data["title"],
                data.get("description"),
                data["product_name"],
                data["original_price"],
                data["sale_price"],
                data["total_quantity"],
                data["starts_at"],
                data["ends_at"],
            )

            await conn.execute(
                """
                INSERT INTO inventory (sale_id, total_quantity, reserved_quantity, sold_quantity)
                VALUES ($1, $2, 0, 0)
                """,
                sale["id"],
                data["total_quantity"],
            )

    return dict(sale)


async def get_sale_by_id(db: asyncpg.Pool, sale_id: str) -> dict | None:
    """Fetch a single sale with its live inventory data."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                s.*,
                i.total_quantity,
                i.reserved_quantity,
                i.sold_quantity,
                i.total_quantity - i.reserved_quantity - i.sold_quantity AS available_quantity
            FROM sales s
            JOIN inventory i ON i.sale_id = s.id
            WHERE s.id = $1
            """,
            sale_id,
        )
    return dict(row) if row else None


async def get_active_sales(db: asyncpg.Pool) -> list[dict]:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                s.*,
                i.total_quantity,
                i.reserved_quantity,
                i.sold_quantity,
                i.total_quantity - i.reserved_quantity - i.sold_quantity
                    AS available_quantity
            FROM sales s
            JOIN inventory i ON i.sale_id = s.id
            WHERE s.status IN ('active', 'scheduled', 'completed', 'paused')
            ORDER BY
                CASE s.status
                    WHEN 'active'    THEN 0
                    WHEN 'scheduled' THEN 1
                    ELSE 2
                END,
                s.starts_at ASC
            """
        )
    return [dict(r) for r in rows]


async def update_sale_status(
    db: asyncpg.Pool,
    sale_id: str,
    new_status: str,
) -> dict:
    """Updates sale status and returns full sale with inventory data."""
    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE sales
            SET status = $1, updated_at = NOW()
            WHERE id = $2
            """,
            new_status,
            sale_id,
        )
    return await get_sale_by_id(db, sale_id)


async def admin_update_sale(db: asyncpg.Pool, sale_id: str, data: dict) -> dict | None:
    """
    Updates sale details — title, prices, dates, quantity.
    Also syncs inventory total_quantity if changed.
    """
    async with db.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE sales SET
                    title          = $1,
                    description    = $2,
                    product_name   = $3,
                    original_price = $4,
                    sale_price     = $5,
                    total_quantity = $6,
                    starts_at      = $7,
                    ends_at        = $8,
                    updated_at     = NOW()
                WHERE id = $9
                """,
                data["title"],
                data.get("description"),
                data["product_name"],
                data["original_price"],
                data["sale_price"],
                data["total_quantity"],
                data["starts_at"],
                data["ends_at"],
                sale_id,
            )

            # Sync inventory total_quantity
            await conn.execute(
                """
                UPDATE inventory
                SET total_quantity = $1,
                    updated_at     = NOW()
                WHERE sale_id = $2
                """,
                data["total_quantity"],
                sale_id,
            )

    return await get_sale_by_id(db, sale_id)


async def admin_delete_sale(db: asyncpg.Pool, sale_id: str) -> bool:
    """
    Deletes a sale and all related data.
    Only allowed if sale is scheduled or completed — not active.
    Returns True if deleted, False if not found.
    """
    async with db.acquire() as conn:
        async with conn.transaction():
            # Delete child records first
            await conn.execute(
                "DELETE FROM orders WHERE sale_id = $1", sale_id
            )
            await conn.execute(
                "DELETE FROM reservations WHERE sale_id = $1", sale_id
            )
            await conn.execute(
                "DELETE FROM preregistrations WHERE sale_id = $1", sale_id
            )
            await conn.execute(
                "DELETE FROM inventory WHERE sale_id = $1", sale_id
            )
            result = await conn.execute(
                "DELETE FROM sales WHERE id = $1", sale_id
            )

    return result == "DELETE 1"


async def admin_get_all_sales(db: asyncpg.Pool) -> list[dict]:
    """All sales for admin — includes paused and all statuses."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                s.*,
                i.total_quantity,
                i.reserved_quantity,
                i.sold_quantity,
                i.total_quantity - i.reserved_quantity - i.sold_quantity
                    AS available_quantity
            FROM sales s
            JOIN inventory i ON i.sale_id = s.id
            ORDER BY s.created_at DESC
            """
        )
    return [dict(r) for r in rows]
"""
Raw SQL queries for the users table.
"""

import asyncpg


async def create_user(db: asyncpg.Pool, data: dict) -> dict:
    """Creates a new user. Raises if email already exists."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, hashed_password, full_name, is_admin)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            data["email"],
            data["hashed_password"],
            data["full_name"],
            data.get("is_admin", False),
        )
    return dict(row)


async def get_user_by_email(db: asyncpg.Pool, email: str) -> dict | None:
    """Fetches a user by email. Used for login."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE email = $1",
            email,
        )
    return dict(row) if row else None


async def get_user_by_id(db: asyncpg.Pool, user_id: str) -> dict | None:
    """Fetches a user by ID. Used for token validation."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1 AND is_active = TRUE",
            user_id,
        )
    return dict(row) if row else None


async def admin_list_users(db: asyncpg.Pool) -> list[dict]:
    """Returns all users for admin panel — newest first."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, email, full_name, is_active, is_admin,
                created_at,
                (SELECT COUNT(*) FROM orders o WHERE o.user_id = users.id) AS order_count,
                (SELECT COUNT(*) FROM reservations r WHERE r.user_id = users.id) AS reservation_count
            FROM users
            ORDER BY created_at DESC
            """
        )
    return [dict(r) for r in rows]


async def admin_deactivate_user(db: asyncpg.Pool, user_id: str) -> dict | None:
    """Deactivates a user account — they can no longer login."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET is_active = FALSE
            WHERE id = $1 AND is_admin = FALSE
            RETURNING id, email, full_name, is_active, is_admin, created_at
            """,
            user_id,
        )
    return dict(row) if row else None


async def admin_activate_user(db: asyncpg.Pool, user_id: str) -> dict | None:
    """Reactivates a deactivated user account."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET is_active = TRUE
            WHERE id = $1
            RETURNING id, email, full_name, is_active, is_admin, created_at
            """,
            user_id,
        )
    return dict(row) if row else None


async def admin_delete_user(db: asyncpg.Pool, user_id: str) -> bool:
    """
    Permanently deletes a non-admin user and all their data.
    Returns True if deleted, False if not found or is admin.
    """
    async with db.acquire() as conn:
        async with conn.transaction():
            # Check not admin
            is_admin = await conn.fetchval(
                "SELECT is_admin FROM users WHERE id = $1", user_id
            )
            if is_admin is None or is_admin:
                return False

            # Delete child records first
            await conn.execute(
                "DELETE FROM orders WHERE user_id = $1", user_id
            )
            await conn.execute(
                "DELETE FROM reservations WHERE user_id = $1", user_id
            )
            await conn.execute(
                "DELETE FROM preregistrations WHERE user_id = $1", user_id
            )
            result = await conn.execute(
                "DELETE FROM users WHERE id = $1", user_id
            )

    return result == "DELETE 1"
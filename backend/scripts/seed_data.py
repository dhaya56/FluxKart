"""
Seed Data Script — FluxKart

Creates test data:
  - 1 admin user (dhaya@fluxkart.com / 123)
  - 5 flash sales with realistic inventory
  - Pre-seeds Redis inventory for active sales

Usage:
  python scripts/seed_data.py

Safe to run multiple times — skips existing data.
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncpg
import redis.asyncio as aioredis

from app.config import settings
from app.utils.security import hash_password


# ── Users ─────────────────────────────────────────────────────────────────────

USERS = [
    {
        "email":     "dhaya@fluxkart.com",
        "full_name": "Dhaya",
        "password":  "123",
        "is_admin":  True,
    },
]

# ── Flash Sales ───────────────────────────────────────────────────────────────

def get_sales():
    now = datetime.now(timezone.utc)
    return [
        {
            "title":          "iPhone 15 Pro Flash Sale",
            "description":    "Limited units at 30% off. Fastest fingers first.",
            "product_name":   "iPhone 15 Pro 256GB",
            "original_price": "1199.99",
            "sale_price":     "839.99",
            "total_quantity": 50,
            "starts_at":      now - timedelta(minutes=2),
            "ends_at":        now + timedelta(minutes=15),
            "status":         "active",
        },
        {
            "title":          "Samsung Galaxy S24 Sale",
            "description":    "Flash sale — only 100 units available.",
            "product_name":   "Samsung Galaxy S24 Ultra",
            "original_price": "1299.99",
            "sale_price":     "899.99",
            "total_quantity": 100,
            "starts_at":      now - timedelta(minutes=1),
            "ends_at":        now + timedelta(minutes=15),
            "status":         "active",
        },
        {
            "title":          "MacBook Air M3 Deal",
            "description":    "Student discount flash sale.",
            "product_name":   "MacBook Air M3 8GB 256GB",
            "original_price": "1099.99",
            "sale_price":     "879.99",
            "total_quantity": 25,
            "starts_at":      now - timedelta(minutes=1),
            "ends_at":        now + timedelta(minutes=15),
            "status":         "active",
        },
        {
            "title":          "PS5 Console Flash Sale",
            "description":    "Very limited stock. One per customer.",
            "product_name":   "PlayStation 5 Disc Edition",
            "original_price": "499.99",
            "sale_price":     "399.99",
            "total_quantity": 10,
            "starts_at":      now + timedelta(minutes=20),
            "ends_at":        now + timedelta(minutes=35),
            "status":         "scheduled",
        },
        {
            "title":          "Sony WH-1000XM5 Headphones",
            "description":    "Premium noise cancelling at flash price.",
            "product_name":   "Sony WH-1000XM5",
            "original_price": "399.99",
            "sale_price":     "249.99",
            "total_quantity": 200,
            "starts_at":      now + timedelta(minutes=30),
            "ends_at":        now + timedelta(minutes=45),
            "status":         "scheduled",
        },
    ]


# ── Seed Functions ────────────────────────────────────────────────────────────

async def seed_users(conn: asyncpg.Connection) -> None:
    print("Seeding users...")
    for user in USERS:
        existing = await conn.fetchval(
            "SELECT id FROM users WHERE email = $1",
            user["email"],
        )
        if existing:
            print(f"  Skipping {user['email']} — already exists")
            continue

        await conn.execute(
            """
            INSERT INTO users (email, full_name, hashed_password, is_active, is_admin)
            VALUES ($1, $2, $3, TRUE, $4)
            """,
            user["email"],
            user["full_name"],
            hash_password(user["password"]),
            user.get("is_admin", False),
        )
        print(f"  Created {user['email']}")


async def seed_sales(
    conn: asyncpg.Connection,
    redis: aioredis.Redis,
) -> list[dict]:
    print("\nSeeding sales...")
    created_sales = []
    sales = get_sales()

    for sale_data in sales:
        existing = await conn.fetchval(
            "SELECT id FROM sales WHERE title = $1",
            sale_data["title"],
        )
        if existing:
            print(f"  Skipping '{sale_data['title']}' — already exists")
            sale = await conn.fetchrow("SELECT * FROM sales WHERE id = $1", existing)
            created_sales.append(dict(sale))
            continue

        # Create sale
        sale = await conn.fetchrow(
            """
            INSERT INTO sales (
                title, description, product_name,
                original_price, sale_price, total_quantity,
                starts_at, ends_at, status
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING *
            """,
            sale_data["title"],
            sale_data["description"],
            sale_data["product_name"],
            sale_data["original_price"],
            sale_data["sale_price"],
            sale_data["total_quantity"],
            sale_data["starts_at"],
            sale_data["ends_at"],
            sale_data["status"],
        )

        sale_id = str(sale["id"])

        # Create inventory record — all counters start at 0
        await conn.execute(
            """
            INSERT INTO inventory (sale_id, total_quantity, reserved_quantity, sold_quantity)
            VALUES ($1, $2, 0, 0)
            """,
            sale["id"],
            sale_data["total_quantity"],
        )

        # Seed Redis for active sales only
        if sale_data["status"] == "active":
            await redis.set(f"inventory:{sale_id}", sale_data["total_quantity"])
            print(f"  Created '{sale_data['title']}' [ACTIVE]    qty={sale_data['total_quantity']}  id={sale_id}")
        else:
            print(f"  Created '{sale_data['title']}' [SCHEDULED] qty={sale_data['total_quantity']}  id={sale_id}")

        created_sales.append(dict(sale))

    return created_sales


async def print_summary(sales: list[dict]) -> None:
    print("\n" + "=" * 60)
    print("SEED COMPLETE")
    print("=" * 60)
    print("\nAdmin account:")
    print("  Email   : dhaya@fluxkart.com")
    print("  Password: 123")
    print("\nSales:")
    for sale in sales:
        print(
            f"  [{sale['status'].upper():10}] "
            f"{sale['title'][:40]:40} "
            f"id={str(sale['id'])[:8]}..."
        )
    print("=" * 60)


async def main():
    print("FluxKart Seed Data Script")
    print("-" * 40)

    db = await asyncpg.create_pool(dsn=settings.postgres_dsn)
    redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

    try:
        async with db.acquire() as conn:
            await seed_users(conn)
            sales = await seed_sales(conn, redis)
            await print_summary(sales)

        print("\nDone.")

    finally:
        await db.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
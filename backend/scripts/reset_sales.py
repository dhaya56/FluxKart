"""
Reset Sales Script — FluxKart

Resets all sale timers and inventory for testing.
Run this whenever sales expire during development.

Usage:
  python scripts/reset_sales.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
import asyncpg
import redis.asyncio as aioredis


ACTIVE_SALES = [
    {"title": "iPhone 15 Pro Flash Sale",  "quantity": 10000},
    {"title": "Samsung Galaxy S24 Sale",   "quantity": 100},
    {"title": "MacBook Air M3 Deal",       "quantity": 25},
]

SCHEDULED_SALES = [
    {"title": "PS5 Console Flash Sale",        "start_in": 20, "end_in": 35,  "quantity": 10},
    {"title": "Sony WH-1000XM5 Headphones",    "start_in": 30, "end_in": 45,  "quantity": 200},
]


async def main():
    print("FluxKart Sales Reset")
    print("-" * 40)

    db = await asyncpg.create_pool(dsn=settings.postgres_dsn)
    redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

    try:
        async with db.acquire() as conn:

            # ── Reset active sale timers ──────────────────────────────────
            active_titles = [s["title"] for s in ACTIVE_SALES]
            await conn.execute(
                """
                UPDATE sales SET
                  status    = 'active',
                  starts_at = NOW() - INTERVAL '1 minute',
                  ends_at   = NOW() + INTERVAL '15 minutes'
                WHERE title = ANY($1)
                """,
                active_titles,
            )

            # ── Reset scheduled sale timers ───────────────────────────────
            for sale in SCHEDULED_SALES:
                await conn.execute(
                    """
                    UPDATE sales SET
                      status    = 'scheduled',
                      starts_at = NOW() + ($1 || ' minutes')::interval,
                      ends_at   = NOW() + ($2 || ' minutes')::interval
                    WHERE title = $3
                    """,
                    str(sale["start_in"]),
                    str(sale["end_in"]),
                    sale["title"],
                )

            # ── Reset PostgreSQL inventory ────────────────────────────────
            all_sales = ACTIVE_SALES + [
                {"title": s["title"], "quantity": s["quantity"]}
                for s in SCHEDULED_SALES
            ]
            for sale in all_sales:
                await conn.execute(
                    """
                    UPDATE inventory SET
                      reserved_quantity = 0,
                      sold_quantity     = 0,
                      total_quantity    = $1,
                      updated_at        = NOW()
                    WHERE sale_id = (
                      SELECT id FROM sales WHERE title = $2
                    )
                    """,
                    sale["quantity"],
                    sale["title"],
                )

            # ── Reset Redis inventory ─────────────────────────────────────
            for sale in ACTIVE_SALES:
                sale_id = await conn.fetchval(
                    "SELECT id FROM sales WHERE title = $1",
                    sale["title"],
                )
                if sale_id:
                    await redis.set(f"inventory:{sale_id}", sale["quantity"])

            # ── Clear Redis queues ────────────────────────────────────────
            for sale in ACTIVE_SALES + SCHEDULED_SALES:
                sale_id = await conn.fetchval(
                    "SELECT id FROM sales WHERE title = $1", sale["title"]
                )
                if sale_id:
                    await redis.delete(f"queue:{sale_id}")

            # ── Clear ALL reservations and orders (testing only) ──────────
            await conn.execute("DELETE FROM orders")
            await conn.execute("DELETE FROM reservations")
            await conn.execute("DELETE FROM preregistrations")

            # ── Print summary ─────────────────────────────────────────────
            print("\nActive sales (15 min remaining):")
            for sale in ACTIVE_SALES:
                sale_id = await conn.fetchval(
                    "SELECT id FROM sales WHERE title = $1", sale["title"]
                )
                print(f"  ✓ {sale['title']:<35} qty={sale['quantity']}  id={str(sale_id)[:8]}...")

            print("\nScheduled sales:")
            for sale in SCHEDULED_SALES:
                sale_id = await conn.fetchval(
                    "SELECT id FROM sales WHERE title = $1", sale["title"]
                )
                print(f"  ✓ {sale['title']:<35} starts in {sale['start_in']} min  id={str(sale_id)[:8]}...")

            print("\nCleared ALL orders, reservations and preregistrations (testing mode).")

        print("\nReset complete. Refresh the frontend.")
        print("-" * 40)

    finally:
        await db.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
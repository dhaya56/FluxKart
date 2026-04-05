"""
Creates 5000 test users for k6 load testing.

Run before load test:
  python scripts/create_test_users.py

Creates users: testuser1@fluxkart.com through testuser5000@fluxkart.com
Password: testpass123
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.utils.security import hash_password
import asyncpg

TOTAL_USERS = 5000
BATCH_SIZE  = 100  # Insert in batches to avoid memory spike


async def main():
    db = await asyncpg.create_pool(dsn=settings.postgres_dsn)

    created = 0
    skipped = 0

    # Pre-hash password once — reuse for all users
    # bcrypt is slow — hashing 5000 times would take ~5 minutes
    print("Pre-hashing password (once)...")
    hashed_pw = hash_password("testpass123")
    print("Done. Creating users...")

    async with db.acquire() as conn:
        for i in range(1, TOTAL_USERS + 1):
            email = f"testuser{i}@fluxkart.com"

            exists = await conn.fetchval(
                "SELECT id FROM users WHERE email = $1", email
            )

            if exists:
                skipped += 1
            else:
                await conn.execute(
                    """
                    INSERT INTO users (email, hashed_password, full_name, is_active, is_admin)
                    VALUES ($1, $2, $3, TRUE, FALSE)
                    """,
                    email,
                    hashed_pw,
                    f"Test User {i}",
                )
                created += 1

            if i % 500 == 0:
                print(f"  Progress: {i}/{TOTAL_USERS}")

    await db.close()

    print(f"\nTest users ready.")
    print(f"  Created : {created}")
    print(f"  Skipped : {skipped}")
    print(f"  Total   : {created + skipped}")
    print(f"\nCredentials: testuser1@fluxkart.com / testpass123")


if __name__ == "__main__":
    asyncio.run(main())
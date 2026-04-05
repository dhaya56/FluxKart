"""
Pre-generates JWT tokens for all 5000 test users.
Saves to scripts/tokens.json — loaded by k6 at startup instead of
doing 5000 live logins (eliminates the 3-minute bcrypt bottleneck).

Run once before load testing:
  python scripts/generate_tokens.py

Re-run if tokens expire (default JWT TTL: 30 minutes).
File is gitignored — never commit tokens.json.

Usage:
  python scripts/generate_tokens.py            # default: http://localhost
  python scripts/generate_tokens.py --url http://localhost
"""

import argparse
import asyncio
import json
import os
import sys
import time

import aiohttp

BASE_URL    = "http://localhost"
TOTAL_USERS = 5000
CONCURRENCY = 50          # simultaneous login requests
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "tokens.json")


async def login(
    session:   aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    i:         int,
) -> tuple[str, str | None]:
    email = f"testuser{i}@fluxkart.com"
    async with semaphore:
        try:
            async with session.post(
                f"{BASE_URL}/auth/login",
                data={
                    "username": email,
                    "password": "testpass123",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    return email, body.get("access_token")
                else:
                    return email, None
        except Exception:
            return email, None


async def main(base_url: str) -> None:
    global BASE_URL
    BASE_URL = base_url

    print(f"Generating tokens for {TOTAL_USERS} users against {BASE_URL}")
    print(f"Concurrency: {CONCURRENCY} simultaneous logins")
    print("This will take ~30-60 seconds...\n")

    semaphore = asyncio.Semaphore(CONCURRENCY)
    tokens    = {}
    failed    = []

    start = time.time()

    async with aiohttp.ClientSession() as session:
        tasks = [login(session, semaphore, i) for i in range(1, TOTAL_USERS + 1)]

        completed = 0
        for coro in asyncio.as_completed(tasks):
            email, token = await coro
            completed += 1

            if token:
                tokens[email] = token
            else:
                failed.append(email)

            if completed % 500 == 0:
                elapsed = time.time() - start
                print(f"  Progress: {completed}/{TOTAL_USERS} ({elapsed:.1f}s)")

    elapsed = time.time() - start

    # Save to file
    with open(OUTPUT_FILE, "w") as f:
        json.dump(tokens, f)

    print(f"\n✓ Done in {elapsed:.1f}s")
    print(f"  Succeeded : {len(tokens)}")
    print(f"  Failed    : {len(failed)}")
    print(f"  Saved to  : {OUTPUT_FILE}")

    if failed:
        print(f"\n  First 5 failures: {failed[:5]}")
        print("  Run create_test_users.py first if users don't exist.")

    if len(tokens) < TOTAL_USERS * 0.95:
        print(f"\n  WARNING: Less than 95% of tokens generated.")
        print(f"  Check that the API is running and test users exist.")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost", help="API base URL")
    args = parser.parse_args()
    asyncio.run(main(args.url))
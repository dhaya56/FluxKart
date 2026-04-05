"""
Inventory Service — Redis-based atomic inventory management.

WHY REDIS AND NOT POSTGRES FOR INVENTORY:
─────────────────────────────────────────
In a flash sale, thousands of requests hit /reserve simultaneously.
If we check and decrement inventory in PostgreSQL:
    1. Read inventory (SELECT)
    2. Check if available
    3. Decrement (UPDATE)

Between steps 1 and 3, another request could read the same value.
This is a classic race condition → overselling.

Solutions:
  Option A: PostgreSQL row lock (SELECT FOR UPDATE) — correct but slow under load
  Option B: Redis DECR — atomic by design, single-threaded Redis guarantees
             no two DECR operations interleave. Much faster.

We use Option B (Redis) for the hot path.
PostgreSQL inventory table is updated asynchronously as the source of truth.

REDIS KEY STRUCTURE:
────────────────────
  inventory:{sale_id}          → integer counter (available units)
  reservation:{reservation_id} → hash (user_id, sale_id, quantity, expires_at)
"""

import json
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings


class InventoryService:

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    # ── Key Helpers ───────────────────────────────────────────────────────────

    def _inventory_key(self, sale_id: str) -> str:
        return f"inventory:{sale_id}"

    def _reservation_key(self, reservation_id: str) -> str:
        return f"reservation:{reservation_id}"

    # ── Inventory Initialization ──────────────────────────────────────────────

    async def initialize_inventory(
        self,
        sale_id: str,
        quantity: int,
        already_reserved: int = 0,
    ) -> None:
        """
        Seeds Redis inventory counter when sale is created or activated.

        Uses actual available quantity = total - already_reserved - sold
        This ensures Redis stays in sync with PostgreSQL on restart.

        NX flag removed — we always want accurate value on activation.
        """
        available = max(0, quantity - already_reserved)
        await self.redis.set(
            self._inventory_key(sale_id),
            available,
        )

    async def get_available_inventory(self, sale_id: str) -> int:
        """Returns current available inventory from Redis."""
        key = self._inventory_key(sale_id)
        value = await self.redis.get(key)
        if value is None:
            return 0
        return int(value)

    # ── Core Atomic Operation ─────────────────────────────────────────────────

    async def try_reserve_inventory(
        self,
        sale_id: str,
        reservation_id: str,
        user_id: str,
        quantity: int,
        ttl_seconds: int = 600,  # Now accepts dynamic TTL
    ) -> bool:
        """
        Attempts to atomically reserve inventory using a Lua script.
        TTL is now dynamic based on user behavioral score.
        """
        lua_script = """
        local inventory_key = KEYS[1]
        local reservation_key = KEYS[2]
        local quantity = tonumber(ARGV[1])
        local reservation_data = ARGV[2]
        local ttl = tonumber(ARGV[3])

        local current = tonumber(redis.call('GET', inventory_key))

        if current == nil or current < quantity then
            return 0
        end

        redis.call('DECRBY', inventory_key, quantity)
        redis.call('SET', reservation_key, reservation_data, 'EX', ttl)

        return 1
        """

        reservation_data = json.dumps({
            "user_id":    user_id,
            "sale_id":    sale_id,
            "quantity":   quantity,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        result = await self.redis.eval(
            lua_script,
            2,
            self._inventory_key(sale_id),
            self._reservation_key(reservation_id),
            quantity,
            reservation_data,
            ttl_seconds,  # Dynamic TTL
        )

        return bool(result)

    # ── Inventory Release ─────────────────────────────────────────────────────

    async def release_inventory(
        self,
        sale_id: str,
        reservation_id: str,
        quantity: int,
    ) -> None:
        """
        Returns inventory back to the pool when a reservation expires or
        is cancelled. Called by the background expiry worker.
        """
        lua_script = """
        local inventory_key = KEYS[1]
        local reservation_key = KEYS[2]
        local quantity = tonumber(ARGV[1])

        -- Only release if reservation still exists in Redis
        -- (prevents double-release if called twice)
        local exists = redis.call('EXISTS', reservation_key)
        if exists == 1 then
            redis.call('INCRBY', inventory_key, quantity)
            redis.call('DEL', reservation_key)
        end

        return exists
        """

        await self.redis.eval(
            lua_script,
            2,
            self._inventory_key(sale_id),
            self._reservation_key(reservation_id),
            quantity,
        )

    async def confirm_reservation(
        self,
        reservation_id: str,
    ) -> None:
        """
        Called when payment is confirmed.
        Removes the reservation from Redis — inventory stays decremented.
        """
        key = self._reservation_key(reservation_id)
        await self.redis.delete(key)

    async def try_increase_reservation(
        self,
        sale_id: str,
        reservation_id: str,
        extra_quantity: int,
    ) -> bool:
        """
        Atomically acquires additional inventory for an existing reservation.
        Uses Lua script — check and decrement are atomic.

        Returns True if successful, False if not enough inventory.
        """
        lua_script = """
        local inventory_key  = KEYS[1]
        local reservation_key = KEYS[2]
        local extra = tonumber(ARGV[1])

        local current = tonumber(redis.call('GET', inventory_key))

        if current == nil or current < extra then
            return 0
        end

        redis.call('DECRBY', inventory_key, extra)

        -- Update quantity in reservation metadata
        local data = redis.call('GET', reservation_key)
        if data then
            local decoded = cjson.decode(data)
            decoded['quantity'] = decoded['quantity'] + extra
            local ttl = redis.call('TTL', reservation_key)
            redis.call('SET', reservation_key, cjson.encode(decoded), 'EX', ttl)
        end

        return 1
        """

        result = await self.redis.eval(
            lua_script,
            2,
            self._inventory_key(sale_id),
            self._reservation_key(reservation_id),
            extra_quantity,
        )

        return bool(result)

    async def release_partial_inventory(
        self,
        sale_id: str,
        reservation_id: str,
        released_quantity: int,
    ) -> None:
        """
        Returns partial inventory when user decreases quantity.
        Updates reservation metadata in Redis.
        """
        lua_script = """
        local inventory_key   = KEYS[1]
        local reservation_key = KEYS[2]
        local released = tonumber(ARGV[1])

        -- Return inventory
        redis.call('INCRBY', inventory_key, released)

        -- Update reservation metadata
        local data = redis.call('GET', reservation_key)
        if data then
            local decoded = cjson.decode(data)
            decoded['quantity'] = decoded['quantity'] - released
            local ttl = redis.call('TTL', reservation_key)
            redis.call('SET', reservation_key, cjson.encode(decoded), 'EX', ttl)
        end

        return 1
        """

        await self.redis.eval(
            lua_script,
            2,
            self._inventory_key(sale_id),
            self._reservation_key(reservation_id),
            released_quantity,
        )
"""
Virtual Waiting Queue Service.

DESIGN:
────────
Redis Sorted Set per sale:
  Key:   queue:{sale_id}
  Score: arrival timestamp (ms) — guarantees FIFO order
  Value: user_id

Under normal load (queue depth < threshold):
  → Skip queue, process reservation directly
  → Fast path for low traffic

Under high load (queue depth >= threshold):
  → All users enter queue
  → Processor admits in batches of 10 every 100ms
  → Fair — first come first served
  → Backpressure communicated to client via position

QUEUE THRESHOLD:
─────────────────
If fewer than 10 users are waiting, skip queue entirely.
This prevents unnecessary latency during normal traffic.
Only activate queue under genuine load.
"""

import time

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

QUEUE_THRESHOLD = 10  # Activate queue only above this depth


class QueueService:

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    def _queue_key(self, sale_id: str) -> str:
        return f"queue:{sale_id}"

    def _admitted_key(self, sale_id: str, user_id: str) -> str:
        """Key that marks a user as admitted from the queue."""
        return f"admitted:{sale_id}:{user_id}"

    async def get_queue_depth(self, sale_id: str) -> int:
        """Returns total users currently waiting."""
        try:
            return await self.redis.zcard(self._queue_key(sale_id))
        except Exception:
            return 0  # Redis down — report empty queue

    async def is_queue_active(self, sale_id: str) -> bool:
        """
        Returns True if queue should be enforced.
        Fails safely — if Redis is down, skip queue entirely.
        """
        try:
            depth = await self.get_queue_depth(sale_id)
            return depth >= QUEUE_THRESHOLD
        except Exception:
            return False  # Redis down — skip queue, use fallback path

    async def enqueue(self, sale_id: str, user_id: str) -> int:
        """
        Adds user to waiting queue.
        Returns their 1-based position.
        NX flag prevents re-queuing if already waiting.
        """
        key   = self._queue_key(sale_id)
        score = int(time.time() * 1000)

        await self.redis.zadd(key, {user_id: score}, nx=True)

        rank = await self.redis.zrank(key, user_id)
        return (rank or 0) + 1

    async def get_position(self, sale_id: str, user_id: str) -> int | None:
        """Returns current queue position. None if not in queue."""
        rank = await self.redis.zrank(self._queue_key(sale_id), user_id)
        if rank is None:
            return None
        return rank + 1

    async def is_admitted(self, sale_id: str, user_id: str) -> bool:
        """
        Checks if user has been admitted from the queue.
        Fails open — if Redis is down, admit everyone.
        """
        try:
            key = self._admitted_key(sale_id, user_id)
            return await self.redis.exists(key) == 1
        except Exception:
            return True  # Redis down — admit everyone, fallback handles inventory

    async def admit_user(self, sale_id: str, user_id: str) -> None:
        key = self._admitted_key(sale_id, user_id)
        await self.redis.set(key, "1", ex=30)
        # Remove from waiting set — position of everyone behind updates immediately
        await self.redis.zrem(self._queue_key(sale_id), user_id)

    async def consume_admission(self, sale_id: str, user_id: str) -> None:
        """Removes admission token after user reserves."""
        await self.redis.delete(self._admitted_key(sale_id, user_id))

    async def dequeue_batch(
        self,
        sale_id: str,
        batch_size: int = 10,
    ) -> list[str]:
        """
        Atomically removes and returns next batch of users.
        Uses ZPOPMIN — lowest score = earliest arrival = first served.
        """
        key   = self._queue_key(sale_id)
        items = await self.redis.zpopmin(key, batch_size)
        return [item[0] for item in items]

    async def remove_from_queue(self, sale_id: str, user_id: str) -> None:
        """Removes user from queue (cancelled or timed out)."""
        await self.redis.zrem(self._queue_key(sale_id), user_id)

    async def get_queue_status(self, sale_id: str, user_id: str) -> dict:
        """Full queue status for a user — used by polling endpoint."""
        position = await self.get_position(sale_id, user_id)
        depth    = await self.get_queue_depth(sale_id)
        admitted = await self.is_admitted(sale_id, user_id)

        return {
            "sale_id":        sale_id,
            "user_id":        user_id,
            "position":       position,
            "total_in_queue": depth,
            "in_queue":       position is not None,
            "admitted":       admitted,
        }
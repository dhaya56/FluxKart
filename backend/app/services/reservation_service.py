"""
Reservation Service — orchestrates the full reservation flow.

PERFORMANCE OPTIMIZATIONS:
────────────────────────────
1. Sale data cached in Redis (30s TTL) — eliminates DB query on hot path
2. User trust score cached in Redis (5min TTL) — eliminates complex DB query
3. PostgreSQL inventory UPDATE removed from API path — handled by consumer
4. RabbitMQ channel pool — no per-request channel open/close

RELIABILITY:
─────────────
Outbox pattern — reservation INSERT and outbox_event INSERT happen in ONE
atomic transaction. The outbox worker publishes to RabbitMQ separately.
This guarantees zero message loss if RabbitMQ is temporarily unavailable.
"""

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import aio_pika
import asyncpg
import redis.asyncio as aioredis
import structlog

from app.consumers.order_consumer import EXCHANGE_NAME, ROUTING_KEY
from app.db.queries import orders as order_queries
from app.db.queries import sales as sale_queries
from app.db.queries.outbox import create_outbox_event
from app.services.inventory_service import InventoryService
from app.utils.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.utils.degradation import try_reserve_with_fallback
from app.utils.metrics import (
    INVENTORY_REMAINING,
    RESERVATION_ATTEMPTS,
    RESERVATION_LATENCY,
)
from app.utils.user_score import (
    calculate_user_score,
    get_recovery_window_for_score,
    get_ttl_for_score,
)
from app.services.queue_service import QueueService

logger = structlog.get_logger()

# ── Cache TTLs ────────────────────────────────────────────────────────────────
SALE_CACHE_TTL       = 30    # seconds — sale state (active/status/prices)
USER_SCORE_CACHE_TTL = 300   # seconds — user trust score (5 minutes)


class QueuePositionError(Exception):
    """Raised when user is placed in queue instead of reserved."""
    def __init__(self, position: int, queue_depth: int, message: str):
        self.position    = position
        self.queue_depth = queue_depth
        self.message     = message
        super().__init__(message)


class ReservationService:

    def __init__(
        self,
        db: asyncpg.Pool,
        redis: aioredis.Redis,
    ):
        self.db        = db
        self.redis     = redis
        self.inventory = InventoryService(redis)

    # ── Redis Cache Helpers ───────────────────────────────────────────────────

    async def _get_sale_cached(self, sale_id_str: str) -> dict | None:
        """
        Returns sale data from Redis cache or DB.
        Caches for 30 seconds — eliminates get_sale_by_id DB query on hot path.
        """
        cache_key = f"sale_cache:{sale_id_str}"
        try:
            cached = await self.redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                for field in ("starts_at", "ends_at", "created_at", "updated_at"):
                    if data.get(field):
                        data[field] = datetime.fromisoformat(data[field])
                return data
        except Exception:
            pass

        sale = await sale_queries.get_sale_by_id(self.db, sale_id_str)
        if sale:
            try:
                cacheable = {
                    k: v.isoformat() if isinstance(v, datetime) else
                       str(v) if isinstance(v, Decimal) else v
                    for k, v in sale.items()
                    if not isinstance(v, (bytes, memoryview))
                }
                await self.redis.set(cache_key, json.dumps(cacheable), ex=SALE_CACHE_TTL)
            except Exception:
                pass

        return sale

    async def _get_user_score_cached(self, user_id_str: str) -> tuple[float, int, int]:
        """
        Returns (score, ttl_seconds, recovery_window) from Redis cache or DB.
        Caches for 5 minutes.
        """
        cache_key = f"user_score:{user_id_str}"
        try:
            cached = await self.redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                return data["score"], data["ttl"], data["recovery"]
        except Exception:
            pass

        score           = await calculate_user_score(self.db, user_id_str)
        ttl_seconds     = get_ttl_for_score(score)
        recovery_window = get_recovery_window_for_score(score)

        try:
            await self.redis.set(
                cache_key,
                json.dumps({"score": score, "ttl": ttl_seconds, "recovery": recovery_window}),
                ex=USER_SCORE_CACHE_TTL,
            )
        except Exception:
            pass

        return score, ttl_seconds, recovery_window

    # ── Main Reservation Flow ─────────────────────────────────────────────────

    async def create_reservation(
        self,
        user_id: UUID,
        sale_id: UUID,
        quantity: int,
        idempotency_key: str,
    ) -> dict:
        sale_id_str = str(sale_id)
        user_id_str = str(user_id)
        start_time  = time.time()

        # ── Step 1: Idempotency Check ─────────────────────────────────────────
        existing = await order_queries.get_reservation_by_idempotency_key(
            self.db, idempotency_key
        )
        if existing:
            RESERVATION_ATTEMPTS.labels(status="duplicate").inc()
            return {"reservation": existing, "was_duplicate": True}

        # ── Step 2: One Order Per User Per Sale ───────────────────────────────
        async with self.db.acquire() as conn:
            existing_order = await conn.fetchrow(
                """
                SELECT id FROM orders
                WHERE user_id = $1 AND sale_id = $2
                AND status = 'paid'
                """,
                user_id_str, sale_id_str,
            )
            if existing_order:
                RESERVATION_ATTEMPTS.labels(status="failed_already_purchased").inc()
                raise ValueError(
                    "You have already purchased this item. "
                    "Flash sales allow one purchase per user per sale."
                )

            existing_reservation = await conn.fetchrow(
                """
                SELECT id FROM reservations
                WHERE user_id = $1
                AND sale_id   = $2
                AND status    IN ('pending', 'confirmed')
                """,
                user_id_str, sale_id_str,
            )
            if existing_reservation:
                RESERVATION_ATTEMPTS.labels(status="failed_duplicate").inc()
                raise ValueError(
                    "You already have an active reservation for this sale. "
                    "Complete or wait for it to expire before reserving again."
                )

        # ── Step 3: Validate Sale (Redis cache first) ─────────────────────────
        sale = await self._get_sale_cached(sale_id_str)

        if not sale:
            RESERVATION_ATTEMPTS.labels(status="failed_invalid_sale").inc()
            raise ValueError("Sale not found")

        if sale["status"] != "active":
            RESERVATION_ATTEMPTS.labels(status="failed_invalid_sale").inc()
            raise ValueError(f"Sale is not active. Current status: {sale['status']}")

        now = datetime.now(timezone.utc)
        ends_at = sale["ends_at"]
        if isinstance(ends_at, str):
            ends_at = datetime.fromisoformat(ends_at)
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)

        if now > ends_at:
            RESERVATION_ATTEMPTS.labels(status="failed_invalid_sale").inc()
            raise ValueError("Sale has already ended")

        # ── Step 4: Admission Token Check ─────────────────────────────────────
        admission_key = f"admission:{sale_id_str}:{user_id_str}"

        try:
            has_admission_token = await self.redis.exists(admission_key) == 1
        except Exception:
            has_admission_token = False

        if has_admission_token:
            await self.redis.delete(admission_key)
        else:
            queue_svc = QueueService(self.redis)

            if await queue_svc.is_queue_active(sale_id_str):
                admitted = await queue_svc.is_admitted(sale_id_str, user_id_str)

                if not admitted:
                    position = await queue_svc.enqueue(sale_id_str, user_id_str)
                    depth    = await queue_svc.get_queue_depth(sale_id_str)

                    raise QueuePositionError(
                        position=position,
                        queue_depth=depth,
                        message=(
                            f"You are in queue. Position: {position} of {depth}."
                        ),
                    )

                await queue_svc.consume_admission(sale_id_str, user_id_str)

        # ── Step 5: User Trust Score (Redis cache first) ──────────────────────
        user_score, ttl_seconds, recovery_window = await self._get_user_score_cached(
            user_id_str
        )

        # ── Step 6: Atomic Inventory Reservation ─────────────────────────────
        reservation_id = str(uuid.uuid4())

        success = await try_reserve_with_fallback(
            db=self.db,
            redis=self.redis,
            sale_id=sale_id_str,
            reservation_id=reservation_id,
            user_id=user_id_str,
            quantity=quantity,
            ttl_seconds=ttl_seconds,
        )

        if not success:
            RESERVATION_ATTEMPTS.labels(status="failed_no_inventory").inc()
            raise ValueError("Not enough inventory available")

        try:
            remaining = await self.inventory.get_available_inventory(sale_id_str)
            INVENTORY_REMAINING.labels(sale_id=sale_id_str).set(remaining)
        except Exception:
            pass

        # ── Step 7: Persist Reservation + Outbox Event (single transaction) ───
        # OUTBOX PATTERN:
        # Both writes happen atomically — if either fails, both roll back.
        # This guarantees: if reservation exists in DB, outbox event also exists.
        # The outbox worker publishes to RabbitMQ separately — zero message loss
        # even if RabbitMQ is down at this moment.
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        sale_price = sale.get("sale_price", 0)

        try:
            async with self.db.acquire() as conn:
                async with conn.transaction():
                    # Insert reservation
                    reservation = await conn.fetchrow(
                        """
                        INSERT INTO reservations (
                            user_id, sale_id, quantity,
                            idempotency_key, expires_at
                        )
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING *
                        """,
                        user_id_str,
                        sale_id_str,
                        quantity,
                        idempotency_key,
                        expires_at,
                    )
                    reservation = dict(reservation)

                    # Insert outbox event — same connection, same transaction
                    await create_outbox_event(
                        conn=conn,
                        aggregate_type="reservation",
                        aggregate_id=str(reservation["id"]),
                        event_type="reservation.created",
                        payload={
                            "event_type":     "reservation.created",
                            "reservation_id": str(reservation["id"]),
                            "user_id":        user_id_str,
                            "sale_id":        sale_id_str,
                            "quantity":       quantity,
                            "unit_price":     str(sale_price),
                            "timestamp":      datetime.now(timezone.utc).isoformat(),
                        },
                    )

        except Exception as e:
            # Roll back Redis inventory reservation on DB failure
            await self.inventory.release_inventory(
                sale_id=sale_id_str,
                reservation_id=reservation_id,
                quantity=quantity,
            )
            RESERVATION_ATTEMPTS.labels(status="failed_db_error").inc()
            if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                raise ValueError("You already have an active reservation for this sale.")
            raise RuntimeError(f"Failed to persist reservation: {str(e)}")

        # ── Step 8: Store Recovery Window ─────────────────────────────────────
        if recovery_window > 0:
            try:
                recovery_key  = f"recovery:{user_id_str}:{sale_id_str}"
                recovery_data = json.dumps({
                    "reservation_id": str(reservation["id"]),
                    "user_id":        user_id_str,
                    "sale_id":        sale_id_str,
                    "quantity":       quantity,
                    "unit_price":     str(sale_price),
                    "score":          round(user_score, 3),
                })
                await self.redis.set(recovery_key, recovery_data, ex=ttl_seconds + recovery_window)
            except Exception:
                pass

        # ── Step 9: Record Metrics ────────────────────────────────────────────
        duration = time.time() - start_time
        RESERVATION_LATENCY.observe(duration)
        RESERVATION_ATTEMPTS.labels(status="success").inc()

        # ── Step 10: Best-effort direct RabbitMQ publish ──────────────────────
        # Try to publish immediately for low latency (consumer gets it in ~1ms).
        # If this fails, the outbox worker will publish within 1-2 seconds.
        # This is a best-effort fast path — NOT the reliability guarantee.
        # Reliability comes from the outbox event written in Step 7.
        circuit_breaker = CircuitBreaker(
            redis=self.redis,
            name="rabbitmq_publish",
            failure_threshold=5,
            cooldown_seconds=30,
        )

        try:
            await circuit_breaker.call(
                self._publish_reservation_event,
                reservation_id=str(reservation["id"]),
                user_id=user_id_str,
                sale_id=sale_id_str,
                quantity=quantity,
                unit_price=sale_price,
            )
        except (CircuitOpenError, Exception) as e:
            logger.warning(
                "Direct RabbitMQ publish failed — outbox worker will retry",
                reservation_id=str(reservation["id"]),
                reason=str(e),
            )
            # No raise — outbox worker handles delivery

        return {"reservation": reservation, "was_duplicate": False}

    async def _publish_reservation_event(
        self,
        reservation_id: str,
        user_id: str,
        sale_id: str,
        quantity: int,
        unit_price: Decimal,
    ) -> None:
        from app.dependencies import get_channel_pool
        from opentelemetry import trace
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        message_body = json.dumps({
            "event_type":     "reservation.created",
            "reservation_id": reservation_id,
            "user_id":        user_id,
            "sale_id":        sale_id,
            "quantity":       quantity,
            "unit_price":     str(unit_price),
            "timestamp":      datetime.now(timezone.utc).isoformat(),
        }).encode()

        # Inject W3C trace context — links consumer span to this API span in Jaeger
        carrier = {}
        TraceContextTextMapPropagator().inject(carrier)

        channel_pool = await get_channel_pool()
        async with channel_pool.acquire() as channel:
            exchange = await channel.get_exchange(EXCHANGE_NAME)
            await exchange.publish(
                aio_pika.Message(
                    body=message_body,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type="application/json",
                    headers=carrier,
                ),
                routing_key=ROUTING_KEY,
            )
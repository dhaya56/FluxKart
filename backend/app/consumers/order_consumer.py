"""
Order Consumer — processes reservation events from RabbitMQ.
Now confirms reservation after order creation.
"""

import asyncio
import json
import traceback
from datetime import datetime, timezone

import aio_pika
import asyncpg
import structlog
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.config import settings
from app.db.queries.orders import (
    confirm_reservation,
    create_order,
    get_reservation_by_id,
)
from app.utils.metrics import ORDERS_CREATED, ORDERS_FAILED

logger = structlog.get_logger()

EXCHANGE_NAME   = "fluxkart.direct"
QUEUE_NAME      = "fluxkart.orders"
DLQ_NAME        = "fluxkart.orders.dead"
ROUTING_KEY     = "order.created"
MAX_RETRY_COUNT = 3

_propagator = TraceContextTextMapPropagator()


async def setup_queues(channel: aio_pika.Channel) -> aio_pika.Queue:
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME,
        aio_pika.ExchangeType.DIRECT,
        durable=True,
    )

    dlx = await channel.declare_exchange(
        f"{EXCHANGE_NAME}.dead",
        aio_pika.ExchangeType.DIRECT,
        durable=True,
    )

    dlq = await channel.declare_queue(DLQ_NAME, durable=True)
    await dlq.bind(dlx, routing_key=ROUTING_KEY)

    queue = await channel.declare_queue(
        QUEUE_NAME,
        durable=True,
        arguments={
            "x-dead-letter-exchange":    f"{EXCHANGE_NAME}.dead",
            "x-dead-letter-routing-key": ROUTING_KEY,
            "x-message-ttl":             86400000,
        },
    )
    await queue.bind(exchange, routing_key=ROUTING_KEY)

    return queue


async def process_order_message(
    message: aio_pika.IncomingMessage,
    db: asyncpg.Pool,
) -> None:
    """
    Processes a single order message.

    Full flow:
    1. Parse message + extract trace context (propagated from API)
    2. Fetch reservation
    3. Check idempotency — skip if already processed
    4. Create order record
    5. Confirm reservation — status pending → confirmed
    6. Update inventory reserved_quantity
    7. Acknowledge message

    Trace context is extracted from message headers — this links the
    consumer span to the original POST /reservations trace in Jaeger.
    Each order shows the full distributed trace: API → RabbitMQ → Consumer.
    """
    # ── Extract trace context from message headers ────────────────────────────
    # The API published the W3C traceparent header in the message
    # This links this consumer span to the original API request trace
    carrier = {}
    if message.headers:
        carrier = {
            k: v for k, v in message.headers.items()
            if isinstance(v, str)
        }
    ctx = _propagator.extract(carrier)

    tracer = trace.get_tracer("fluxkart-consumer")

    with tracer.start_as_current_span(
        "rabbitmq.consume order.created",
        context=ctx,
        kind=trace.SpanKind.CONSUMER,
    ) as span:
        span.set_attribute("messaging.system",           "rabbitmq")
        span.set_attribute("messaging.destination",      QUEUE_NAME)
        span.set_attribute("messaging.operation",        "process")

        async with message.process(requeue=False):
            try:
                body           = json.loads(message.body.decode())
                reservation_id = body["reservation_id"]

                span.set_attribute("reservation.id",   reservation_id)
                span.set_attribute("order.unit_price", body.get("unit_price", 0))

                logger.info(
                    "Processing order message",
                    reservation_id=reservation_id,
                    event_type=body.get("event_type"),
                )

                # Fetch reservation
                reservation = await get_reservation_by_id(db, reservation_id)

                if not reservation:
                    span.set_attribute("skip.reason", "reservation_not_found")
                    logger.error(
                        "Reservation not found — skipping",
                        reservation_id=reservation_id,
                    )
                    ORDERS_FAILED.inc()
                    return

                # Idempotency check — skip if already confirmed
                if reservation["status"] == "confirmed":
                    span.set_attribute("skip.reason", "already_confirmed")
                    logger.info(
                        "Reservation already confirmed — skipping",
                        reservation_id=reservation_id,
                    )
                    return

                if reservation["status"] != "pending":
                    span.set_attribute("skip.reason", f"status_{reservation['status']}")
                    logger.info(
                        "Reservation not pending — skipping",
                        reservation_id=reservation_id,
                        status=reservation["status"],
                    )
                    return

                # Create order
                unit_price  = float(body["unit_price"])
                quantity    = reservation["quantity"]
                total_price = unit_price * quantity

                span.set_attribute("order.quantity",    quantity)
                span.set_attribute("order.total_price", total_price)

                order = await create_order(db, {
                    "user_id":        str(reservation["user_id"]),
                    "sale_id":        str(reservation["sale_id"]),
                    "reservation_id": reservation_id,
                    "quantity":       quantity,
                    "unit_price":     unit_price,
                    "total_price":    total_price,
                })

                # Confirm reservation
                await confirm_reservation(db, reservation_id)

                # Sync inventory reserved_quantity
                async with db.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE inventory
                        SET reserved_quantity = reserved_quantity + $1,
                            updated_at        = NOW()
                        WHERE sale_id = $2
                        """,
                        quantity,
                        str(reservation["sale_id"]),
                    )

                span.set_attribute("order.id", str(order["id"]))
                ORDERS_CREATED.inc()

                logger.info(
                    "Order created and reservation confirmed",
                    order_id=str(order["id"]),
                    reservation_id=reservation_id,
                    total_price=total_price,
                )

            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                ORDERS_FAILED.inc()
                logger.error(
                    "Failed to process order message",
                    error=str(e),
                    traceback=traceback.format_exc(),
                )
                raise


async def start_consumer(db: asyncpg.Pool) -> None:
    logger.info("Starting order consumer")

    connection = await aio_pika.connect_robust(settings.rabbitmq_url)

    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)
        queue   = await setup_queues(channel)

        logger.info("Order consumer ready", queue=QUEUE_NAME)

        async for message in queue:
            await process_order_message(message, db)
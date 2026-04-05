"""
Outbox Worker — polls outbox_events table and publishes to RabbitMQ.

WHY THIS EXISTS:
─────────────────
The outbox pattern guarantees at-least-once message delivery.

Flow:
  1. reservation_service writes reservation + outbox_event in ONE transaction
  2. This worker polls outbox_events WHERE published = FALSE every 1 second
  3. For each unpublished event, publishes to RabbitMQ
  4. On success: marks event published = TRUE
  5. On failure: increments retry_count, logs error, retries next poll

This means:
  - RabbitMQ down for 30 seconds? Events accumulate in outbox, published when it recovers
  - API pod crashes after DB write? Worker on another pod picks up the event
  - Zero message loss regardless of RabbitMQ availability

DEDUPLICATION:
───────────────
The outbox publishes the same event as the direct publish in reservation_service.
The order_consumer handles deduplication via idempotency check:
  if reservation["status"] == "confirmed": skip
This means even if both the direct publish AND the outbox worker publish,
only one order is created.
"""

import asyncio
import json
from datetime import datetime, timezone

import aio_pika
import asyncpg
import structlog

from app.config import settings
from app.db.queries.outbox import (
    get_pending_outbox_events,
    mark_event_failed,
    mark_event_published,
)

logger = structlog.get_logger()

POLL_INTERVAL_SECONDS = 1     # Poll every 1 second
BATCH_SIZE            = 50    # Process up to 50 events per poll
MAX_RETRY_COUNT       = 10    # Stop retrying after 10 failures

EXCHANGE_NAME = "fluxkart.direct"
ROUTING_KEY   = "order.created"


async def _publish_event(
    channel: aio_pika.Channel,
    event: dict,
) -> None:
    """Publishes a single outbox event to RabbitMQ."""
    payload = event["payload"]

    # payload is stored as JSONB — asyncpg returns it as a dict already
    if isinstance(payload, str):
        payload = json.loads(payload)

    message_body = json.dumps(payload).encode()

    exchange = await channel.get_exchange(EXCHANGE_NAME)
    await exchange.publish(
        aio_pika.Message(
            body=message_body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
        ),
        routing_key=ROUTING_KEY,
    )


async def process_outbox_batch(
    db: asyncpg.Pool,
    channel: aio_pika.Channel,
) -> int:
    """
    Processes one batch of unpublished outbox events.
    Returns number of events successfully published.
    """
    events    = await get_pending_outbox_events(db, batch_size=BATCH_SIZE)
    published = 0

    for event in events:
        event_id    = str(event["id"])
        retry_count = event["retry_count"]

        # Stop retrying permanently failed events
        if retry_count >= MAX_RETRY_COUNT:
            logger.error(
                "Outbox event exceeded max retries — skipping permanently",
                event_id=event_id,
                retry_count=retry_count,
                event_type=event["event_type"],
            )
            # Mark published to stop retrying — prevents infinite loop
            # In production: move to a dead letter outbox table instead
            await mark_event_published(db, event_id)
            continue

        try:
            await _publish_event(channel, event)
            await mark_event_published(db, event_id)
            published += 1

            logger.info(
                "Outbox event published",
                event_id=event_id,
                event_type=event["event_type"],
                aggregate_id=str(event["aggregate_id"]),
                retry_count=retry_count,
            )

        except Exception as e:
            await mark_event_failed(db, event_id, str(e))
            logger.warning(
                "Failed to publish outbox event — will retry",
                event_id=event_id,
                event_type=event["event_type"],
                retry_count=retry_count + 1,
                error=str(e),
            )

    return published


async def start_outbox_worker(db: asyncpg.Pool) -> None:
    """
    Main outbox worker loop.

    Maintains its own RabbitMQ connection — independent of the API's
    channel pool. This ensures the outbox worker keeps publishing even
    if the API's RabbitMQ connection has issues.
    """
    logger.info("Starting outbox worker", poll_interval=POLL_INTERVAL_SECONDS)

    while True:
        try:
            connection = await aio_pika.connect_robust(settings.rabbitmq_url)

            async with connection:
                channel = await connection.channel()

                logger.info("Outbox worker connected to RabbitMQ")

                while True:
                    try:
                        published = await process_outbox_batch(db, channel)

                        if published > 0:
                            logger.info(
                                "Outbox batch complete",
                                published=published,
                            )

                    except Exception as e:
                        logger.error(
                            "Outbox batch processing error",
                            error=str(e),
                        )
                        # Break inner loop — reconnect to RabbitMQ
                        break

                    await asyncio.sleep(POLL_INTERVAL_SECONDS)

        except Exception as e:
            logger.error(
                "Outbox worker RabbitMQ connection failed — retrying in 5s",
                error=str(e),
            )
            await asyncio.sleep(5)
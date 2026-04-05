"""
Dead Letter Queue Monitor.

WHY THIS EXISTS:
─────────────────
RabbitMQ moves failed messages to the DLQ automatically.
But nobody is watching the DLQ.

Without a monitor:
  Messages pile up silently in DLQ
  Orders are never created for those reservations
  Users reserved inventory but never got orders
  Revenue lost, users angry, nobody knows why

With a monitor:
  Worker checks DLQ depth every 60 seconds
  If depth > threshold → logs critical alert
  In production this would trigger PagerDuty/Slack alert
  Team can inspect and replay messages immediately

WHAT TO DO WHEN DLQ HAS MESSAGES:
────────────────────────────────────
1. Check logs for consumer errors around the time messages arrived
2. Fix the bug
3. Move messages back to main queue for reprocessing:
   - Use RabbitMQ management UI (localhost:15672)
   - Click queues → fluxkart.orders.dead → Move messages
   - Or use shovel plugin for automated replay
"""

import asyncio

import aio_pika
import structlog

from app.config import settings
from app.utils.metrics import ORDERS_FAILED

logger = structlog.get_logger()

DLQ_NAME               = "fluxkart.orders.dead"
DLQ_CHECK_INTERVAL_S   = 60
DLQ_ALERT_THRESHOLD    = 5   # Alert if more than 5 messages in DLQ


async def check_dlq_depth(channel: aio_pika.Channel) -> int:
    """
    Returns the current number of messages in the DLQ.
    Uses passive declare — does not modify the queue.
    """
    queue = await channel.declare_queue(
        DLQ_NAME,
        durable=True,
        passive=True,   # Just inspect, do not create or modify
    )
    return queue.declaration_result.message_count


async def start_dlq_monitor() -> None:
    """
    Runs the DLQ monitor in an infinite loop.
    Started as a background task in main.py lifespan.
    """
    logger.info(
        "DLQ monitor started",
        queue=DLQ_NAME,
        check_interval_seconds=DLQ_CHECK_INTERVAL_S,
        alert_threshold=DLQ_ALERT_THRESHOLD,
    )

    while True:
        try:
            connection = await aio_pika.connect_robust(settings.rabbitmq_url)

            async with connection:
                channel = await connection.channel()
                depth   = await check_dlq_depth(channel)

                if depth == 0:
                    # All good — no failed messages
                    pass

                elif depth <= DLQ_ALERT_THRESHOLD:
                    # Small number — warn but not critical
                    logger.warning(
                        "DLQ has failed messages",
                        queue=DLQ_NAME,
                        message_count=depth,
                        threshold=DLQ_ALERT_THRESHOLD,
                        action="Inspect RabbitMQ UI at localhost:15672",
                    )

                else:
                    # Above threshold — critical alert
                    logger.error(
                        "DLQ CRITICAL — too many failed messages",
                        queue=DLQ_NAME,
                        message_count=depth,
                        threshold=DLQ_ALERT_THRESHOLD,
                        action=(
                            "IMMEDIATE ACTION REQUIRED. "
                            "Check consumer logs and fix before replaying. "
                            "RabbitMQ UI: localhost:15672"
                        ),
                    )
                    # Increment failed orders metric for Prometheus/Grafana
                    ORDERS_FAILED.inc(depth)

        except asyncio.CancelledError:
            logger.info("DLQ monitor stopped")
            break

        except Exception as e:
            logger.error(
                "DLQ monitor error",
                error=str(e),
            )

        await asyncio.sleep(DLQ_CHECK_INTERVAL_S)
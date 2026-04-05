"""
FluxKart Worker Process — runs consumer + all background workers.

WHY SEPARATION FROM API:
─────────────────────────
Before: api1 + api2 each ran 4 background workers
  - 8 worker instances polling same Redis/RabbitMQ queues
  - Workers competed with HTTP handlers for the event loop
  - RabbitMQ CPU spiked to 500% from duplicate polling

After: Single dedicated worker process
  - API event loops 100% free for HTTP requests
  - One set of workers — no duplicate polling
  - RabbitMQ idle CPU drops to < 5%

Usage:
  python consumers/run_consumer.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import structlog
import structlog.contextvars

from app.dependencies import (
    init_db_pool, init_redis, init_rabbitmq,
    get_db, get_redis,
)
from app.consumers.order_consumer import start_consumer
from app.workers.expiry_worker import start_expiry_worker
from app.workers.outbox_worker import start_outbox_worker
from app.workers.reconciliation_worker import start_reconciliation_worker
from app.workers.heartbeat_worker import start_heartbeat_worker
from app.utils.dlq_monitor import start_dlq_monitor

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


async def main():
    logger.info("Starting FluxKart Worker Process")

    await init_db_pool()
    logger.info("PostgreSQL connection pool initialized")

    await init_redis()
    logger.info("Redis connection initialized")

    await init_rabbitmq()
    logger.info("RabbitMQ connection initialized")

    # ── Tracing — no app instance, consumer has no HTTP ──────────────────────
    from app.telemetry import setup_tracing
    setup_tracing(app=None, service_name="fluxkart-consumer")
    logger.info("OpenTelemetry tracing initialized")

    db    = await get_db()
    redis = await get_redis()

    logger.info("Starting all background workers")

    await asyncio.gather(
        start_consumer(db),
        start_expiry_worker(db, redis),
        start_reconciliation_worker(db, redis),
        start_heartbeat_worker(redis),
        start_dlq_monitor(),
        start_outbox_worker(db),    # ← publishes pending outbox events to RabbitMQ
        return_exceptions=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
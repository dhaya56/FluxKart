import asyncio
from contextlib import asynccontextmanager

import aio_pika
import structlog
import structlog.contextvars
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from app.config import settings
from app.dependencies import (
    close_db_pool,
    close_rabbitmq,
    close_redis,
    get_db,
    get_rabbitmq,
    init_db_pool,
    init_rabbitmq,
    init_redis,
    get_redis,
)
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.routers import admin, auth, health, orders, reservations, sales

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


async def initialize_rabbitmq_infrastructure(rabbitmq) -> None:
    """
    Creates RabbitMQ exchanges and queues at startup.
    Idempotent — safe to call multiple times.
    """
    channel = await rabbitmq.channel()

    await channel.declare_exchange(
        "fluxkart.direct",
        aio_pika.ExchangeType.DIRECT,
        durable=True,
    )

    await channel.declare_exchange(
        "fluxkart.direct.dead",
        aio_pika.ExchangeType.DIRECT,
        durable=True,
    )

    dlq = await channel.declare_queue(
        "fluxkart.orders.dead",
        durable=True,
    )
    dlx = await channel.get_exchange("fluxkart.direct.dead")
    await dlq.bind(dlx, routing_key="order.created")

    exchange = await channel.get_exchange("fluxkart.direct")
    queue = await channel.declare_queue(
        "fluxkart.orders",
        durable=True,
        arguments={
            "x-dead-letter-exchange":    "fluxkart.direct.dead",
            "x-dead-letter-routing-key": "order.created",
            "x-message-ttl":             86400000,
        },
    )
    await queue.bind(exchange, routing_key="order.created")
    await channel.close()

    logger.info("RabbitMQ infrastructure initialized")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting FluxKart API", env=settings.app_env)

    await init_db_pool()
    logger.info("PostgreSQL connection pool initialized")

    await init_redis()
    logger.info("Redis connection initialized")

    from app.middleware.rate_limiter import init_rate_limiter
    redis = await get_redis()
    await init_rate_limiter(redis)
    logger.info("Rate limiter initialized")

    await init_rabbitmq()
    logger.info("RabbitMQ connection initialized")

    rabbitmq = await get_rabbitmq()
    await initialize_rabbitmq_infrastructure(rabbitmq)

    app.state.redis = await get_redis()

    logger.info("FluxKart API is ready to accept requests")

    yield

    logger.info("Shutting down FluxKart API")

    await close_db_pool()
    await close_redis()
    await close_rabbitmq()
    logger.info("All connections closed. Goodbye.")


# ── Swagger UI disabled in production ────────────────────────────────────────
# Prevents exposing API schema to public in production
# Still available in development via /docs and /redoc
_is_production = settings.app_env == "production"

app = FastAPI(
    title="FluxKart",
    description=(
        "Distributed Flash Sale & Inventory Reservation Engine. "
        "Handles thundering-herd traffic with atomic inventory management, "
        "virtual waiting queues, and async order processing."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

# ── Tracing ───────────────────────────────────────────────────────────────────
from app.telemetry import setup_tracing
setup_tracing(app=app, service_name="fluxkart-api")

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(CorrelationIdMiddleware)

Instrumentator().instrument(app).expose(app)

app.include_router(health.router,        tags=["Health"])
app.include_router(admin.router,         prefix="/admin",        tags=["Admin"])
app.include_router(auth.router,          prefix="/auth",         tags=["Authentication"])
app.include_router(sales.router,         prefix="/sales",        tags=["Sales"])
app.include_router(reservations.router,  prefix="/reservations", tags=["Reservations"])
app.include_router(orders.router,        prefix="/orders",       tags=["Orders"])
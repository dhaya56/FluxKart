"""
Health check endpoint.
Now includes circuit breaker status.
"""

import aio_pika
import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.dependencies import get_db, get_redis
from app.utils.circuit_breaker import CircuitBreaker

router = APIRouter()


@router.get("/health", summary="Health Check")
async def health_check(
    db: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    results = {
        "status":   "healthy",
        "version":  "0.1.0",
        "services": {
            "postgresql": "unknown",
            "redis":      "unknown",
            "rabbitmq":   "unknown",
        },
        "circuit_breakers": {},
    }
    all_healthy = True

    # ── Check PostgreSQL ──────────────────────────────────────
    try:
        async with db.acquire() as conn:
            await conn.fetchval("SELECT 1")
        results["services"]["postgresql"] = "healthy"
    except Exception as e:
        results["services"]["postgresql"] = f"unhealthy: {str(e)}"
        all_healthy = False

    # ── Check Redis ───────────────────────────────────────────
    try:
        await redis.ping()
        results["services"]["redis"] = "healthy"
    except Exception as e:
        results["services"]["redis"] = f"unhealthy: {str(e)}"
        all_healthy = False

    # ── Check RabbitMQ ────────────────────────────────────────
    try:
        connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        await connection.close()
        results["services"]["rabbitmq"] = "healthy"
    except Exception as e:
        results["services"]["rabbitmq"] = f"unhealthy: {str(e)}"
        all_healthy = False

    # ── Check Circuit Breakers ────────────────────────────────
    try:
        cb = CircuitBreaker(redis=redis, name="rabbitmq_publish")
        results["circuit_breakers"]["rabbitmq_publish"] = \
            await cb.get_status()
    except Exception:
        pass

    if not all_healthy:
        results["status"] = "unhealthy"
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=results,
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=results,
    )
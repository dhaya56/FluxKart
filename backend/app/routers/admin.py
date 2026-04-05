"""
Admin API — internal operations endpoints.

Endpoints:
  GET    /admin/sales                      → List all sales with stats
  POST   /admin/sales                      → Create a new sale
  GET    /admin/sales/{id}/stats           → Detailed stats for one sale
  PUT    /admin/sales/{id}                 → Edit sale details
  DELETE /admin/sales/{id}                 → Delete a sale
  POST   /admin/sales/{id}/pause           → Pause an active sale
  POST   /admin/sales/{id}/resume          → Resume a paused sale
  POST   /admin/sales/{id}/complete        → Complete a sale
  POST   /admin/sales/{id}/activate        → Activate a scheduled sale
  POST   /admin/sales/{id}/adjust-inventory → Adjust inventory manually
  GET    /admin/queue/{sale_id}            → View queue depth and details
  GET    /admin/dlq                        → View DLQ status
  GET    /admin/circuit-breakers           → View all circuit breaker states
  GET    /admin/users                      → List all users
  POST   /admin/users/{id}/deactivate      → Deactivate a user
  POST   /admin/users/{id}/activate        → Activate a user
  DELETE /admin/users/{id}                 → Delete a user
"""

import aio_pika
import asyncpg
import structlog
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings
from app.db.queries import sales as sale_queries
from app.db.queries import users as user_queries
from app.dependencies import get_db, get_rabbitmq, get_redis
from app.routers.auth import get_current_user
from app.services.inventory_service import InventoryService
from app.services.queue_service import QueueService
from app.utils.circuit_breaker import CircuitBreaker
from app.workers.admission_worker import (
    start_admission_worker,
    stop_admission_worker,
)

router = APIRouter()
logger = structlog.get_logger()


# ── Admin Auth ────────────────────────────────────────────────────────────────

async def verify_admin(
    current_user=Depends(get_current_user),
    db: asyncpg.Pool = Depends(get_db),
):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ── Request Models ────────────────────────────────────────────────────────────

class InventoryAdjustRequest(BaseModel):
    adjustment: int = Field(description="Positive to add, negative to remove")
    reason: str     = Field(min_length=5, description="Reason for adjustment")


class SaleCreateRequest(BaseModel):
    title:          str     = Field(min_length=3, max_length=255)
    description:    str | None = None
    product_name:   str     = Field(min_length=2, max_length=255)
    original_price: Decimal = Field(gt=0)
    sale_price:     Decimal = Field(gt=0)
    total_quantity: int     = Field(gt=0)
    starts_at:      datetime
    ends_at:        datetime


class SaleEditRequest(BaseModel):
    title:          str     = Field(min_length=3, max_length=255)
    description:    str | None = None
    product_name:   str     = Field(min_length=2, max_length=255)
    original_price: Decimal = Field(gt=0)
    sale_price:     Decimal = Field(gt=0)
    total_quantity: int     = Field(gt=0)
    starts_at:      datetime
    ends_at:        datetime


# ── Sale Management ───────────────────────────────────────────────────────────

@router.get(
    "/sales",
    summary="List all sales with stats",
    dependencies=[Depends(verify_admin)],
)
async def list_all_sales(
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
):
    sales = await sale_queries.admin_get_all_sales(db)
    queue_svc = QueueService(redis)

    for sale in sales:
        sale_id = str(sale["id"])
        try:
            sale["queue_depth"] = await queue_svc.get_queue_depth(sale_id)
        except Exception:
            sale["queue_depth"] = 0

        try:
            redis_inventory = await redis.get(f"inventory:{sale_id}")
            sale["redis_inventory"] = int(redis_inventory) if redis_inventory else None
        except Exception:
            sale["redis_inventory"] = None

    return sales


@router.post(
    "/sales",
    summary="Create a new sale",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_admin)],
)
async def create_sale(
    payload: SaleCreateRequest,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
):
    if payload.sale_price >= payload.original_price:
        raise HTTPException(
            status_code=400,
            detail="Sale price must be less than original price",
        )
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(
            status_code=400,
            detail="ends_at must be after starts_at",
        )

    now = datetime.now(timezone.utc)
    starts_at = payload.starts_at
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)

    # Determine initial status
    initial_status = "active" if starts_at <= now else "scheduled"

    sale = await sale_queries.create_sale(db, {
        "title":          payload.title,
        "description":    payload.description,
        "product_name":   payload.product_name,
        "original_price": payload.original_price,
        "sale_price":     payload.sale_price,
        "total_quantity": payload.total_quantity,
        "starts_at":      payload.starts_at,
        "ends_at":        payload.ends_at,
    })

    # Set status
    await sale_queries.update_sale_status(db, str(sale["id"]), initial_status)

    # Seed Redis for active sales
    if initial_status == "active":
        try:
            await redis.set(f"inventory:{sale['id']}", payload.total_quantity)
        except Exception:
            pass

    logger.info(
        "Sale created by admin",
        sale_id=str(sale["id"]),
        title=payload.title,
        status=initial_status,
    )

    return {**sale, "status": initial_status}


@router.put(
    "/sales/{sale_id}",
    summary="Edit sale details",
    dependencies=[Depends(verify_admin)],
)
async def edit_sale(
    sale_id: str,
    payload: SaleEditRequest,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
):
    sale = await sale_queries.get_sale_by_id(db, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if sale["status"] == "completed":
        raise HTTPException(
            status_code=400,
            detail="Cannot edit a completed sale",
        )

    if payload.sale_price >= payload.original_price:
        raise HTTPException(
            status_code=400,
            detail="Sale price must be less than original price",
        )

    updated = await sale_queries.admin_update_sale(db, sale_id, {
        "title":          payload.title,
        "description":    payload.description,
        "product_name":   payload.product_name,
        "original_price": payload.original_price,
        "sale_price":     payload.sale_price,
        "total_quantity": payload.total_quantity,
        "starts_at":      payload.starts_at,
        "ends_at":        payload.ends_at,
    })

    # Sync Redis total if quantity changed
    if payload.total_quantity != sale["total_quantity"]:
        diff = payload.total_quantity - sale["total_quantity"]
        try:
            if diff > 0:
                await redis.incrby(f"inventory:{sale_id}", diff)
            else:
                await redis.decrby(f"inventory:{sale_id}", abs(diff))
        except Exception:
            pass

    logger.info("Sale edited by admin", sale_id=sale_id, title=payload.title)
    return updated


@router.delete(
    "/sales/{sale_id}",
    summary="Delete a sale",
    dependencies=[Depends(verify_admin)],
)
async def delete_sale(
    sale_id: str,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
):
    sale = await sale_queries.get_sale_by_id(db, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if sale["status"] == "active":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an active sale. Pause or complete it first.",
        )

    deleted = await sale_queries.admin_delete_sale(db, sale_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sale not found")

    # Clean up Redis
    try:
        await redis.delete(f"inventory:{sale_id}")
        await redis.delete(f"queue:{sale_id}")
    except Exception:
        pass

    logger.info("Sale deleted by admin", sale_id=sale_id)
    return {"message": "Sale deleted", "sale_id": sale_id}


@router.get(
    "/sales/{sale_id}/stats",
    summary="Get detailed stats for a sale",
    dependencies=[Depends(verify_admin)],
)
async def get_sale_stats(
    sale_id: str,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
):
    async with db.acquire() as conn:
        stats = await conn.fetchrow(
            """
            SELECT
                s.id, s.title, s.status, s.starts_at, s.ends_at,
                i.total_quantity, i.reserved_quantity, i.sold_quantity,
                i.total_quantity - i.reserved_quantity - i.sold_quantity
                    AS available_quantity,
                COUNT(DISTINCT r.id) FILTER (WHERE r.status = 'pending')   AS pending_reservations,
                COUNT(DISTINCT r.id) FILTER (WHERE r.status = 'confirmed') AS confirmed_reservations,
                COUNT(DISTINCT r.id) FILTER (WHERE r.status = 'expired')   AS expired_reservations,
                COUNT(DISTINCT o.id)                                        AS total_orders,
                COALESCE(SUM(o.total_price), 0)                             AS total_revenue
            FROM sales s
            JOIN inventory i ON i.sale_id = s.id
            LEFT JOIN reservations r ON r.sale_id = s.id
            LEFT JOIN orders o ON o.sale_id = s.id
            WHERE s.id = $1
            GROUP BY s.id, s.title, s.status, s.starts_at, s.ends_at,
                     i.total_quantity, i.reserved_quantity, i.sold_quantity
            """,
            sale_id,
        )

    if not stats:
        raise HTTPException(status_code=404, detail="Sale not found")

    result = dict(stats)
    try:
        redis_inventory = await redis.get(f"inventory:{sale_id}")
        result["redis_inventory"] = int(redis_inventory) if redis_inventory else None
        queue_svc = QueueService(redis)
        result["queue_depth"] = await queue_svc.get_queue_depth(sale_id)
    except Exception:
        result["redis_inventory"] = None
        result["queue_depth"]     = 0

    return result


@router.post(
    "/sales/{sale_id}/activate",
    summary="Manually activate a scheduled sale",
    dependencies=[Depends(verify_admin)],
)
async def activate_sale(
    sale_id: str,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
):
    sale = await sale_queries.get_sale_by_id(db, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if sale["status"] != "scheduled":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot activate sale with status: {sale['status']}",
        )

    # Block activation if end time already passed
    now     = datetime.now(timezone.utc)
    ends_at = sale["ends_at"]
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)

    if ends_at < now:
        raise HTTPException(
            status_code=400,
            detail="Sale end time has already passed. Edit the sale dates before activating.",
        )

    updated = await sale_queries.update_sale_status(db, sale_id, "active")

    # Seed Redis inventory
    try:
        available = sale["total_quantity"] - sale["reserved_quantity"] - sale["sold_quantity"]
        await redis.set(f"inventory:{sale_id}", available)
    except Exception:
        pass

    # Start admission worker
    await start_admission_worker(
        db=db,
        redis=redis,
        sale_id=sale_id,
        sale_ends_at=updated["ends_at"],
    )

    logger.info("Sale manually activated by admin", sale_id=sale_id)
    return {"message": f"Sale {sale_id} activated", "status": "active"}


@router.post(
    "/sales/{sale_id}/pause",
    summary="Pause an active sale",
    dependencies=[Depends(verify_admin)],
)
async def pause_sale(
    sale_id: str,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
):
    sale = await sale_queries.get_sale_by_id(db, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if sale["status"] != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pause sale with status: {sale['status']}",
        )

    await sale_queries.update_sale_status(db, sale_id, "paused")
    await stop_admission_worker(sale_id)
    return {"message": f"Sale {sale_id} paused", "status": "paused"}


@router.post(
    "/sales/{sale_id}/resume",
    summary="Resume a paused sale",
    dependencies=[Depends(verify_admin)],
)
async def resume_sale(
    sale_id: str,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
):
    sale = await sale_queries.get_sale_by_id(db, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if sale["status"] != "paused":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resume sale with status: {sale['status']}",
        )

    updated = await sale_queries.update_sale_status(db, sale_id, "active")
    await start_admission_worker(
        db=db, redis=redis,
        sale_id=sale_id,
        sale_ends_at=updated["ends_at"],
    )
    return {"message": f"Sale {sale_id} resumed", "status": "active"}


@router.post(
    "/sales/{sale_id}/complete",
    summary="Mark a sale as completed",
    dependencies=[Depends(verify_admin)],
)
async def complete_sale(
    sale_id: str,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
):
    sale = await sale_queries.get_sale_by_id(db, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    await sale_queries.update_sale_status(db, sale_id, "completed")
    await stop_admission_worker(sale_id)

    try:
        await redis.delete(f"inventory:{sale_id}")
        await redis.delete(f"queue:{sale_id}")
    except Exception:
        pass

    return {"message": f"Sale {sale_id} completed", "status": "completed"}


@router.post(
    "/sales/{sale_id}/adjust-inventory",
    summary="Manually adjust inventory",
    dependencies=[Depends(verify_admin)],
)
async def adjust_inventory(
    sale_id: str,
    payload: InventoryAdjustRequest,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
):
    sale = await sale_queries.get_sale_by_id(db, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    async with db.acquire() as conn:
        current = await conn.fetchrow(
            "SELECT * FROM inventory WHERE sale_id = $1", sale_id
        )
        if not current:
            raise HTTPException(status_code=404, detail="Inventory not found")

        new_total = current["total_quantity"] + payload.adjustment
        if new_total < 0:
            raise HTTPException(
                status_code=400,
                detail=f"Adjustment would result in negative inventory. Current: {current['total_quantity']}",
            )

        await conn.execute(
            """
            UPDATE inventory
            SET total_quantity = total_quantity + $1, updated_at = NOW()
            WHERE sale_id = $2
            """,
            payload.adjustment, sale_id,
        )

    try:
        if payload.adjustment > 0:
            await redis.incrby(f"inventory:{sale_id}", payload.adjustment)
        else:
            await redis.decrby(f"inventory:{sale_id}", abs(payload.adjustment))
    except Exception:
        pass

    logger.info(
        "Inventory adjusted by admin",
        sale_id=sale_id,
        adjustment=payload.adjustment,
        reason=payload.reason,
    )

    return {
        "message":    "Inventory adjusted",
        "sale_id":    sale_id,
        "adjustment": payload.adjustment,
        "new_total":  new_total,
        "reason":     payload.reason,
    }


# ── User Management ───────────────────────────────────────────────────────────

@router.get(
    "/users",
    summary="List all users",
    dependencies=[Depends(verify_admin)],
)
async def list_users(db: asyncpg.Pool = Depends(get_db)):
    return await user_queries.admin_list_users(db)


@router.post(
    "/users/{user_id}/deactivate",
    summary="Deactivate a user account",
    dependencies=[Depends(verify_admin)],
)
async def deactivate_user(
    user_id: str,
    db: asyncpg.Pool = Depends(get_db),
):
    result = await user_queries.admin_deactivate_user(db, user_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="User not found or is an admin — cannot deactivate",
        )
    logger.info("User deactivated by admin", user_id=user_id)
    return {"message": "User deactivated", "user": result}


@router.post(
    "/users/{user_id}/activate",
    summary="Reactivate a user account",
    dependencies=[Depends(verify_admin)],
)
async def activate_user(
    user_id: str,
    db: asyncpg.Pool = Depends(get_db),
):
    result = await user_queries.admin_activate_user(db, user_id)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    logger.info("User activated by admin", user_id=user_id)
    return {"message": "User activated", "user": result}


@router.delete(
    "/users/{user_id}",
    summary="Permanently delete a user",
    dependencies=[Depends(verify_admin)],
)
async def delete_user(
    user_id: str,
    db: asyncpg.Pool = Depends(get_db),
):
    deleted = await user_queries.admin_delete_user(db, user_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="User not found or is an admin — cannot delete",
        )
    logger.info("User deleted by admin", user_id=user_id)
    return {"message": "User deleted", "user_id": user_id}


# ── Queue Management ──────────────────────────────────────────────────────────

@router.get(
    "/queue/{sale_id}",
    summary="View queue depth and top waiting users",
    dependencies=[Depends(verify_admin)],
)
async def get_queue_info(
    sale_id: str,
    redis=Depends(get_redis),
):
    queue_svc = QueueService(redis)
    depth     = await queue_svc.get_queue_depth(sale_id)

    try:
        items = await redis.zrange(f"queue:{sale_id}", 0, 9, withscores=True)
        waiting = [{"user_id": item[0], "queued_at_ms": item[1]} for item in items]
    except Exception:
        waiting = []

    return {"sale_id": sale_id, "queue_depth": depth, "top_waiting": waiting}


# ── System Health ─────────────────────────────────────────────────────────────

@router.get(
    "/dlq",
    summary="View DLQ status",
    dependencies=[Depends(verify_admin)],
)
async def get_dlq_status(rabbitmq=Depends(get_rabbitmq)):
    try:
        channel = await rabbitmq.channel()
        queue   = await channel.declare_queue(
            "fluxkart.orders.dead", durable=True, passive=True
        )
        count = queue.declaration_result.message_count
        await channel.close()

        return {
            "queue":         "fluxkart.orders.dead",
            "message_count": count,
            "status":        "critical" if count > 5 else "warning" if count > 0 else "healthy",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not check DLQ: {str(e)}")


@router.get(
    "/circuit-breakers",
    summary="View all circuit breaker states",
    dependencies=[Depends(verify_admin)],
)
async def get_circuit_breakers(redis=Depends(get_redis)):
    cb = CircuitBreaker(redis=redis, name="rabbitmq_publish")
    return {"circuit_breakers": [await cb.get_status()]}
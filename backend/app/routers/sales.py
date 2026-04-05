"""
Sales API endpoints.

POST /sales                    → Create a new flash sale
GET  /sales                    → List active sales
GET  /sales/{id}               → Get sale with inventory
PATCH /sales/{id}/status       → Update sale status
POST /sales/{id}/preregister   → Pre-register for a sale
GET  /sales/{id}/admission-status → Check if admitted
"""

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

from app.db.queries import sales as sale_queries
from app.db.queries.preregistrations import (
    create_preregistration,
    get_preregistration,
    get_preregistration_count,
)
from app.dependencies import get_db, get_redis
from app.models.schemas import SaleCreate, SaleResponse, SaleWithInventory
from app.routers.auth import get_current_user
from app.services.inventory_service import InventoryService
from app.workers.admission_worker import (
    start_admission_worker,
    stop_admission_worker,
)

router = APIRouter()


@router.post(
    "",
    response_model=SaleWithInventory,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new flash sale",
)
async def create_sale(
    payload: SaleCreate,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
    current_user: dict = Depends(get_current_user),
):
    sale = await sale_queries.create_sale(db, payload.model_dump())

    # Seed Redis inventory — new sale has no reservations yet
    inventory_svc = InventoryService(redis)
    await inventory_svc.initialize_inventory(
        sale_id=str(sale["id"]),
        quantity=sale["total_quantity"],
        already_reserved=0,
    )

    return sale


@router.get(
    "",
    response_model=list[SaleWithInventory],
    summary="List all active sales",
)
async def list_sales(
    db: asyncpg.Pool = Depends(get_db),
):
    return await sale_queries.get_active_sales(db)


@router.get(
    "/{sale_id}",
    response_model=SaleWithInventory,
    summary="Get a specific sale with inventory",
)
async def get_sale(
    sale_id: str,
    db: asyncpg.Pool = Depends(get_db),
):
    sale = await sale_queries.get_sale_by_id(db, sale_id)
    if not sale:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sale {sale_id} not found",
        )
    return sale


@router.patch(
    "/{sale_id}/status",
    response_model=SaleWithInventory,
    summary="Update sale status",
)
async def update_sale_status(
    sale_id: str,
    new_status: str,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
    current_user: dict = Depends(get_current_user),
):
    sale = await sale_queries.get_sale_by_id(db, sale_id)
    if not sale:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sale {sale_id} not found",
        )

    updated = await sale_queries.update_sale_status(db, sale_id, new_status)

    # When sale becomes active — seed Redis and start admission worker
    if new_status == "active":
        # Get current reservation count from DB to sync Redis correctly
        async with db.acquire() as conn:
            reserved = await conn.fetchval(
                """
                SELECT COALESCE(reserved_quantity, 0) + COALESCE(sold_quantity, 0)
                FROM inventory
                WHERE sale_id = $1
                """,
                sale_id,
            ) or 0

        inventory_svc = InventoryService(redis)
        await inventory_svc.initialize_inventory(
            sale_id=sale_id,
            quantity=updated["total_quantity"],
            already_reserved=reserved,
        )
        await start_admission_worker(
            db=db,
            redis=redis,
            sale_id=sale_id,
            sale_ends_at=updated["ends_at"],
        )

    # When sale is paused or completed — stop admission worker
    elif new_status in ("paused", "completed"):
        await stop_admission_worker(sale_id)

    return updated


@router.post(
    "/{sale_id}/preregister",
    status_code=status.HTTP_201_CREATED,
    summary="Pre-register interest in a flash sale",
)
async def preregister_for_sale(
    sale_id: str,
    db: asyncpg.Pool = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Registers user's interest before the sale starts.
    Pre-registered users are admitted in FIFO order at T=0
    instead of competing in a thundering herd.
    """
    sale = await sale_queries.get_sale_by_id(db, sale_id)
    if not sale:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sale not found",
        )

    if sale["status"] == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sale has already completed",
        )

    user_id = str(current_user["id"])

    # Check if already pre-registered
    existing = await get_preregistration(db, user_id, sale_id)
    if existing:
        total = await get_preregistration_count(db, sale_id)
        return {
            "message":      "Already pre-registered",
            "sale_id":      sale_id,
            "registered_at": str(existing["registered_at"]),
            "total_registered": total,
        }

    preregistration = await create_preregistration(db, user_id, sale_id)
    total           = await get_preregistration_count(db, sale_id)

    return {
        "message":          "Pre-registration successful",
        "sale_id":          sale_id,
        "registered_at":    str(preregistration["registered_at"]),
        "total_registered": total,
    }


@router.get(
    "/{sale_id}/admission-status",
    summary="Check if pre-registered user has been admitted",
)
async def get_admission_status(
    sale_id: str,
    redis=Depends(get_redis),
    current_user: dict = Depends(get_current_user),
):
    """
    Poll this endpoint after pre-registering.
    When admitted=true, immediately call POST /reservations.
    Admission token expires in 60 seconds — act fast.
    """
    user_id       = str(current_user["id"])
    admission_key = f"admission:{sale_id}:{user_id}"

    admitted = await redis.exists(admission_key) == 1
    ttl      = await redis.ttl(admission_key) if admitted else 0

    return {
        "sale_id":  sale_id,
        "admitted": admitted,
        "seconds_remaining": ttl if ttl > 0 else 0,
        "message": (
            "You are admitted! Call POST /reservations within "
            f"{ttl} seconds."
            if admitted else
            "Not yet admitted. Keep polling."
        ),
    }
"""
Reservation endpoints.
"""

import json
from uuid import UUID
import asyncio
from fastapi.responses import StreamingResponse
from app.utils.security import decode_token
from app.db.queries.users import get_user_by_id
import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.dependencies import get_db, get_redis
from app.models.schemas import QuantityModifyRequest, ReservationRequest, ReservationResponse
from app.routers.auth import get_current_user
from app.services.queue_service import QueueService
from app.services.reservation_service import QueuePositionError, ReservationService
from app.workers.heartbeat_worker import refresh_heartbeat

logger = structlog.get_logger()

router = APIRouter()


@router.post(
    "",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reserve inventory in a flash sale",
)

async def create_reservation(
    request: Request,
    payload: ReservationRequest,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
    current_user: dict = Depends(get_current_user),
):
    # Per-user rate limit — uses already-decoded user, zero duplicate JWT work
    from app.middleware.rate_limiter import check_reservation_rate_limit
    await check_reservation_rate_limit(request, current_user, redis)

    service = ReservationService(db=db, redis=redis)

    try:
        result = await service.create_reservation(
            user_id=UUID(str(current_user["id"])),
            sale_id=payload.sale_id,
            quantity=payload.quantity,
            idempotency_key=payload.idempotency_key,
        )
    except QueuePositionError as e:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status":       "queued",
                "message":      e.message,
                "position":     e.position,
                "queue_depth":  e.queue_depth,
            },
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    return result["reservation"]


@router.get(
    "/queue-status",
    summary="Check queue position for a sale",
)
async def get_queue_status(
    sale_id: str,
    redis=Depends(get_redis),
    current_user: dict = Depends(get_current_user),
):
    """
    Poll this endpoint to check your position in the waiting queue.
    When admitted=true, immediately call POST /reservations to reserve.
    """
    queue_svc = QueueService(redis)
    return await queue_svc.get_queue_status(
        sale_id=sale_id,
        user_id=str(current_user["id"]),
    )


@router.post(
    "/queue-heartbeat",
    summary="Heartbeat ping to maintain queue position",
)
async def queue_heartbeat(
    sale_id: str,
    redis=Depends(get_redis),
    current_user: dict = Depends(get_current_user),
):
    await refresh_heartbeat(redis, sale_id, str(current_user["id"]))
    return {"status": "alive"}


@router.post(
    "/recover",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Recover an expired reservation within grace period",
)
async def recover_reservation(
    sale_id: str,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
    current_user: dict = Depends(get_current_user),
):
    user_id_str   = str(current_user["id"])
    recovery_key  = f"recovery:{user_id_str}:{sale_id}"
    recovery_data = await redis.get(recovery_key)

    if not recovery_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recovery window found. Either it expired or you are not eligible.",
        )

    data    = json.loads(recovery_data)
    service = ReservationService(db=db, redis=redis)

    try:
        result = await service.create_reservation(
            user_id=UUID(user_id_str),
            sale_id=UUID(sale_id),
            quantity=data["quantity"],
            idempotency_key=f"recovery-{data['reservation_id']}",
        )
    except QueuePositionError as e:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status":      "queued",
                "message":     e.message,
                "position":    e.position,
                "queue_depth": e.queue_depth,
            },
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    await redis.delete(recovery_key)

    logger.info(
        "Reservation recovered successfully",
        user_id=user_id_str,
        sale_id=sale_id,
    )

    return result["reservation"]


@router.patch(
    "/{reservation_id}/quantity",
    response_model=ReservationResponse,
    summary="Modify reservation quantity",
)
async def modify_reservation_quantity(
    reservation_id: str,
    payload: QuantityModifyRequest,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
    current_user: dict = Depends(get_current_user),
):
    """
    Atomically modifies reservation quantity.

    Increasing quantity:
      Checks if extra inventory is available → atomically acquires it
      Reservation TTL resets — fresh window to complete payment

    Decreasing quantity:
      Releases excess inventory back to pool
      Other waiting users can now acquire it
      Reservation TTL resets

    User never loses their spot regardless of direction of change.
    """
    from datetime import datetime, timedelta, timezone
    from app.db.queries.orders import (
        get_pending_reservation_by_id_and_user,
        update_reservation_quantity,
    )
    from app.services.inventory_service import InventoryService
    from app.utils.user_score import calculate_user_score, get_ttl_for_score

    user_id_str = str(current_user["id"])

    # Fetch existing reservation — verify ownership
    reservation = await get_pending_reservation_by_id_and_user(
        db, reservation_id, user_id_str
    )

    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found or already expired",
        )

    current_quantity = reservation["quantity"]
    new_quantity     = payload.new_quantity
    sale_id_str      = str(reservation["sale_id"])

    if new_quantity == current_quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New quantity is the same as current quantity",
        )

    inventory_svc = InventoryService(redis)

    # ── Increasing quantity ───────────────────────────────────────────────────
    if new_quantity > current_quantity:
        extra = new_quantity - current_quantity

        success = await inventory_svc.try_increase_reservation(
            sale_id=sale_id_str,
            reservation_id=reservation_id,
            extra_quantity=extra,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Not enough inventory to increase by {extra} units"
                ),
            )

        logger.info(
            "Reservation quantity increased",
            reservation_id=reservation_id,
            old_quantity=current_quantity,
            new_quantity=new_quantity,
            extra=extra,
        )

    # ── Decreasing quantity ───────────────────────────────────────────────────
    else:
        released = current_quantity - new_quantity

        await inventory_svc.release_partial_inventory(
            sale_id=sale_id_str,
            reservation_id=reservation_id,
            released_quantity=released,
        )

        logger.info(
            "Reservation quantity decreased — inventory released",
            reservation_id=reservation_id,
            old_quantity=current_quantity,
            new_quantity=new_quantity,
            released=released,
        )

    # ── Reset TTL — fresh window after modification ───────────────────────────
    user_score  = await calculate_user_score(db, user_id_str)
    ttl_seconds = get_ttl_for_score(user_score)
    new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    updated = await update_reservation_quantity(
        db,
        reservation_id,
        new_quantity,
        new_expires_at,
    )

    logger.info(
        "Reservation TTL reset after quantity modification",
        reservation_id=reservation_id,
        new_quantity=new_quantity,
        ttl_seconds=ttl_seconds,
    )

    return updated


# ── ADD THIS ENDPOINT ───────────────────────────────────────────────────────
@router.get(
    "/queue-stream",
    summary="SSE stream — live queue position updates",
)
async def queue_stream(
    sale_id: str,
    token: str,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Server-Sent Events stream for live queue position updates.
 
    WHY SSE OVER WEBSOCKET:
    - One-way push from server to client (we never need client → server messages here)
    - Works over HTTP/1.1 — no upgrade handshake
    - Automatic reconnection built into the browser EventSource API
    - Simpler than WebSocket for this use case
 
    WHY SSE OVER POLLING:
    - Single persistent connection vs a new connection every 2 seconds
    - Lower latency — server pushes immediately on change
    - Lower server overhead at 10,000 concurrent users
 
    Client connects via:
      const es = new EventSource(`/api/reservations/queue-stream?sale_id=X&token=Y`)
 
    Token is passed as query param because EventSource does not support
    custom headers in the browser.
    """
    from fastapi.responses import StreamingResponse
    from app.utils.security import decode_token
    from app.db.queries.users import get_user_by_id
 
    # Validate token manually since EventSource can't send Authorization header
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        async def denied():
            yield "data: {\"error\": \"unauthorized\"}\n\n"
        return StreamingResponse(denied(), media_type="text/event-stream")
 
    user_id = payload.get("sub")
    user    = await get_user_by_id(db, user_id)
    if not user:
        async def denied():
            yield "data: {\"error\": \"unauthorized\"}\n\n"
        return StreamingResponse(denied(), media_type="text/event-stream")
 
    user_id_str = str(user["id"])
    queue_svc   = QueueService(redis)
 
    async def event_generator():
        import json
        import asyncio
 
        HEARTBEAT_INTERVAL = 2  # seconds between updates
 
        try:
            while True:
                # Get current status
                position  = await queue_svc.get_position(sale_id, user_id_str)
                depth     = await queue_svc.get_queue_depth(sale_id)
                admitted  = await queue_svc.is_admitted(sale_id, user_id_str)
 
                # Get inventory from Redis
                try:
                    inv_raw   = await redis.get(f"inventory:{sale_id}")
                    inventory = int(inv_raw) if inv_raw is not None else None
                except Exception:
                    inventory = None
 
                sold_out = inventory is not None and inventory <= 0
 
                payload = {
                    "position":       position,
                    "total_in_queue": depth,
                    "admitted":       admitted,
                    "inventory":      inventory,
                    "sold_out":       sold_out,
                }
 
                yield f"data: {json.dumps(payload)}\n\n"
 
                # Stop streaming if admitted or sold out
                if admitted or sold_out:
                    break
 
                # Heartbeat comment to keep connection alive
                yield ": heartbeat\n\n"
 
                await asyncio.sleep(HEARTBEAT_INTERVAL)
 
        except asyncio.CancelledError:
            # Client disconnected — clean up silently
            pass
 
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",   # disables Nginx buffering
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get(
    "/{reservation_id}",
    response_model=ReservationResponse,
    summary="Get reservation by ID",
)
async def get_reservation(
    reservation_id: str,
    db: asyncpg.Pool = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Returns reservation details including current status."""
    from app.db.queries.orders import get_reservation_by_id_and_user

    reservation = await get_reservation_by_id_and_user(
        db,
        reservation_id,
        str(current_user["id"]),
    )

    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    return reservation
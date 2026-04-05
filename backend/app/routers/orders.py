"""
Orders API — protected by JWT authentication.

Endpoints:
  GET  /orders          → All orders (paid/confirmed history)
  GET  /orders/cart     → Active reservations pending payment (cart)
  POST /orders/{id}/pay → Process payment for an order
  POST /orders/{id}/cancel → Cancel a reservation
  GET  /orders/{id}     → Single order detail
"""

import asyncpg
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import structlog

from app.db.queries.orders import get_orders_by_user
from app.dependencies import get_db, get_redis
from app.models.schemas import OrderResponse
from app.routers.auth import get_current_user
from app.services.inventory_service import InventoryService
from app.utils.idempotency import (
    generate_payment_key,
    check_idempotency,
    store_idempotency_result,
)

router = APIRouter()
logger = structlog.get_logger()


# ── Request Models ─────────────────────────────────────────────────────────────

class PaymentRequest(BaseModel):
    card_number:  str  # Last 4 digits only stored — never full number
    expiry:       str  # MM/YY
    cvv:          str  # Never stored
    name_on_card: str


# ── Cart ──────────────────────────────────────────────────────────────────────

@router.get(
    "/cart",
    summary="Get active reservations pending payment",
)
async def get_cart(
    db: asyncpg.Pool = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns all active reservations with sale info and order details.
    This is the user's cart — items reserved but not yet paid.

    A cart item expires when reservation.expires_at passes.
    The frontend shows a live countdown per item.
    """
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                r.id              AS reservation_id,
                r.expires_at,
                r.quantity,
                r.status          AS reservation_status,
                s.id              AS sale_id,
                s.title,
                s.product_name,
                s.sale_price,
                s.original_price,
                s.ends_at         AS sale_ends_at,
                s.status          AS sale_status,
                o.id              AS order_id,
                o.total_price,
                o.status          AS order_status
            FROM reservations r
            JOIN sales s  ON s.id = r.sale_id
            LEFT JOIN orders o ON o.reservation_id = r.id
            WHERE r.user_id = $1
            AND r.status IN ('pending', 'confirmed')
            AND r.expires_at > NOW()
            AND (o.status IS NULL OR o.status != 'paid')
            ORDER BY r.expires_at ASC
            """,
            str(current_user["id"]),
        )

    return [dict(r) for r in rows]


# ── Payment ───────────────────────────────────────────────────────────────────

@router.post(
    "/{order_id}/pay",
    summary="Process payment for an order",
)
async def pay_order(
    order_id: str,
    payload: PaymentRequest,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
    current_user: dict = Depends(get_current_user),
):
    user_id_str = str(current_user["id"])

    # ── Idempotency check — prevent double charge ──────────────────────────
    idem_key = generate_payment_key(user_id_str, order_id, payload.card_number[-4:])
    cached   = await check_idempotency(redis, idem_key)
    if cached:
        return cached

    async with db.acquire() as conn:
        order = await conn.fetchrow(
            """
            SELECT
                o.id, o.status, o.total_price, o.unit_price, o.quantity,
                o.sale_id, o.reservation_id, o.user_id,
                r.expires_at, r.status AS reservation_status,
                s.title, s.product_name, s.ends_at
            FROM orders o
            JOIN reservations r ON r.id = o.reservation_id
            JOIN sales s        ON s.id = o.sale_id
            WHERE o.id      = $1
            AND   o.user_id = $2
            """,
            order_id,
            user_id_str,
        )

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )

        if order["status"] == "paid":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order has already been paid",
            )

        now        = datetime.now(timezone.utc)
        expires_at = order["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < now:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Reservation has expired. Your cart item has been released.",
            )

        card_digits = payload.card_number.replace(" ", "").replace("-", "")
        if not card_digits.isdigit() or len(card_digits) not in (15, 16):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid card number",
            )

        if not payload.cvv.isdigit() or len(payload.cvv) not in (3, 4):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid CVV",
            )

        try:
            month, year = payload.expiry.split("/")
            exp_year    = 2000 + int(year) if len(year) == 2 else int(year)
            exp_month   = int(month)
            exp_date    = datetime(exp_year, exp_month, 1, tzinfo=timezone.utc)
            if exp_date < now:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Card has expired",
                )
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid expiry format. Use MM/YY",
            )

        async with conn.transaction():
            await conn.execute(
                """
                UPDATE orders
                SET status     = 'paid',
                    updated_at = NOW()
                WHERE id = $1
                """,
                order_id,
            )

            await conn.execute(
                """
                UPDATE reservations
                SET status     = 'confirmed',
                    updated_at = NOW()
                WHERE id = $1
                """,
                order["reservation_id"],
            )

            await conn.execute(
                """
                UPDATE inventory SET
                    sold_quantity     = sold_quantity     + $1,
                    reserved_quantity = GREATEST(0, reserved_quantity - $1),
                    updated_at        = NOW()
                WHERE sale_id = $2
                """,
                order["quantity"],
                str(order["sale_id"]),
            )

    logger.info(
        "Payment processed",
        order_id=order_id,
        user_id=user_id_str,
        total_price=str(order["total_price"]),
        product=order["product_name"],
        card_last4=card_digits[-4:],
    )

    # ── Store idempotency result — 24hr cache ──────────────────────────────
    payment_result = {
        "message":    "Payment successful",
        "order_id":   order_id,
        "product":    order["product_name"],
        "quantity":   order["quantity"],
        "total_paid": str(order["total_price"]),
        "status":     "paid",
        "card_last4": card_digits[-4:],
    }
    await store_idempotency_result(redis, idem_key, payment_result)
    return payment_result


# ── Cancel ────────────────────────────────────────────────────────────────────

@router.post(
    "/{order_id}/cancel",
    summary="Cancel a pending order and release inventory",
)
async def cancel_order(
    order_id: str,
    db: asyncpg.Pool = Depends(get_db),
    redis=Depends(get_redis),
    current_user: dict = Depends(get_current_user),
):
    """
    Cancels a pending order and releases inventory back to pool.
    Only allowed for unpaid orders with active reservations.
    """
    user_id_str = str(current_user["id"])
    inventory_svc = InventoryService(redis)

    async with db.acquire() as conn:
        order = await conn.fetchrow(
            """
            SELECT o.*, r.expires_at, r.status AS reservation_status
            FROM orders o
            JOIN reservations r ON r.id = o.reservation_id
            WHERE o.id = $1 AND o.user_id = $2
            """,
            order_id, user_id_str,
        )

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order["status"] == "paid":
            raise HTTPException(
                status_code=400,
                detail="Cannot cancel a paid order",
            )

        async with conn.transaction():
            # Cancel order
            await conn.execute(
                "UPDATE orders SET status = 'failed', updated_at = NOW() WHERE id = $1",
                order_id,
            )

            # Cancel reservation
            await conn.execute(
                "UPDATE reservations SET status = 'cancelled', updated_at = NOW() WHERE id = $1",
                order["reservation_id"],
            )

            # Release inventory in PostgreSQL
            await conn.execute(
                """
                UPDATE inventory
                SET reserved_quantity = GREATEST(0, reserved_quantity - $1),
                    updated_at        = NOW()
                WHERE sale_id = $2
                """,
                order["quantity"],
                str(order["sale_id"]),
            )

    # Release inventory in Redis
    try:
        await inventory_svc.release_inventory(
            sale_id=str(order["sale_id"]),
            reservation_id=str(order["reservation_id"]),
            quantity=order["quantity"],
        )
    except Exception:
        pass

    logger.info("Order cancelled", order_id=order_id, user_id=user_id_str)
    return {"message": "Order cancelled and inventory released", "order_id": order_id}


# ── Order History ─────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[OrderResponse],
    summary="Get all orders for the current user",
)
async def get_my_orders(
    db: asyncpg.Pool = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await get_orders_by_user(db, str(current_user["id"]))


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Get a specific order",
)
async def get_order(
    order_id: str,
    db: asyncpg.Pool = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    async with db.acquire() as conn:
        order = await conn.fetchrow(
            "SELECT * FROM orders WHERE id = $1 AND user_id = $2",
            order_id, str(current_user["id"]),
        )
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return dict(order)
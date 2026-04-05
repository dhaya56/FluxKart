"""
Pydantic v2 schemas for all request and response models.

Why Pydantic:
- Automatic validation — if a field is wrong type, FastAPI returns 422 automatically
- Auto-generates OpenAPI docs (what you see in /docs)
- Strict mode prevents silent type coercion bugs
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class SaleStatus(str, Enum):
    scheduled = "scheduled"
    active    = "active"
    paused    = "paused"
    completed = "completed"


class ReservationStatus(str, Enum):
    pending   = "pending"
    confirmed = "confirmed"
    expired   = "expired"
    cancelled = "cancelled"


class OrderStatus(str, Enum):
    pending  = "pending"
    paid     = "paid"
    failed   = "failed"
    refunded = "refunded"


# ── User Schemas ───────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email:     EmailStr
    password:  str = Field(min_length=8)
    full_name: str = Field(min_length=2, max_length=255)


class UserResponse(BaseModel):
    id:         UUID
    email:      str
    full_name:  str
    is_active:  bool
    is_admin:   bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Sale Schemas ───────────────────────────────────────────────────────────────

class SaleCreate(BaseModel):
    title:          str = Field(min_length=3, max_length=255)
    description:    str | None = None
    product_name:   str = Field(min_length=2, max_length=255)
    original_price: Decimal = Field(gt=0, decimal_places=2)
    sale_price:     Decimal = Field(gt=0, decimal_places=2)
    total_quantity: int = Field(gt=0)
    starts_at:      datetime
    ends_at:        datetime

    @field_validator("ends_at")
    @classmethod
    def ends_after_starts(cls, ends_at, info):
        if "starts_at" in info.data and ends_at <= info.data["starts_at"]:
            raise ValueError("ends_at must be after starts_at")
        return ends_at

    @field_validator("sale_price")
    @classmethod
    def sale_below_original(cls, sale_price, info):
        if "original_price" in info.data and sale_price >= info.data["original_price"]:
            raise ValueError("sale_price must be less than original_price")
        return sale_price


class SaleResponse(BaseModel):
    id:             UUID
    title:          str
    description:    str | None
    product_name:   str
    original_price: Decimal
    sale_price:     Decimal
    total_quantity: int
    starts_at:      datetime
    ends_at:        datetime
    status:         SaleStatus
    created_at:     datetime

    model_config = {"from_attributes": True}


class SaleWithInventory(SaleResponse):
    """Extended response that includes live inventory data."""
    available_quantity: int
    reserved_quantity:  int
    sold_quantity:      int


# ── Reservation Schemas ────────────────────────────────────────────────────────

class ReservationRequest(BaseModel):
    sale_id:         UUID
    quantity:        int = Field(default=1, ge=1, le=10)
    idempotency_key: str = Field(
        min_length=16,
        max_length=255,
        description=(
            "Unique key per reservation attempt. "
            "If you retry with the same key, you get the same result. "
            "Generate with: import uuid; str(uuid.uuid4())"
        )
    )


class ReservationResponse(BaseModel):
    id:              UUID
    user_id:         UUID
    sale_id:         UUID
    quantity:        int
    status:          ReservationStatus
    idempotency_key: str
    expires_at:      datetime
    created_at:      datetime

    model_config = {"from_attributes": True}


# ── Order Schemas ──────────────────────────────────────────────────────────────

class OrderResponse(BaseModel):
    id:             UUID
    user_id:        UUID
    sale_id:        UUID
    reservation_id: UUID
    quantity:       int
    unit_price:     Decimal
    total_price:    Decimal
    status:         OrderStatus
    created_at:     datetime

    model_config = {"from_attributes": True}


# ── Auth Schemas ───────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


# ── Generic Response Schemas ───────────────────────────────────────────────────

class MessageResponse(BaseModel):
    """Simple message response for success/info messages."""
    message: str


class ErrorResponse(BaseModel):
    """Standard error response shape."""
    error:   str
    detail:  str | None = None


class QuantityModifyRequest(BaseModel):
    new_quantity: int = Field(gt=0, le=10, description="New quantity (1-10)")
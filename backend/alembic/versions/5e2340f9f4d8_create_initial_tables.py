"""create_initial_tables

Revision ID: 5e2340f9f4d8
Revises: 
Create Date: 2026-03-04 16:22:13.204594

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e2340f9f4d8'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enable UUID generation ────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # ── USERS ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE users (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email           VARCHAR(255) NOT NULL UNIQUE,
            hashed_password VARCHAR(255) NOT NULL,
            full_name       VARCHAR(255) NOT NULL,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_users_email ON users(email)")

    # ── SALES ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE sales (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title               VARCHAR(255) NOT NULL,
            description         TEXT,
            product_name        VARCHAR(255) NOT NULL,
            original_price      NUMERIC(10, 2) NOT NULL,
            sale_price          NUMERIC(10, 2) NOT NULL,
            total_quantity      INTEGER NOT NULL,
            starts_at           TIMESTAMPTZ NOT NULL,
            ends_at             TIMESTAMPTZ NOT NULL,
            status              VARCHAR(20) NOT NULL DEFAULT 'scheduled'
                                CHECK (status IN ('scheduled', 'active', 'paused', 'completed')),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    # Index for finding active sales quickly
    op.execute("CREATE INDEX idx_sales_status ON sales(status)")
    op.execute("CREATE INDEX idx_sales_starts_at ON sales(starts_at)")

    # ── INVENTORY ─────────────────────────────────────────────
    op.execute("""
        CREATE TABLE inventory (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sale_id             UUID NOT NULL UNIQUE REFERENCES sales(id) ON DELETE CASCADE,
            total_quantity      INTEGER NOT NULL,
            reserved_quantity   INTEGER NOT NULL DEFAULT 0,
            sold_quantity       INTEGER NOT NULL DEFAULT 0,
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_reserved_non_negative CHECK (reserved_quantity >= 0),
            CONSTRAINT chk_sold_non_negative CHECK (sold_quantity >= 0),
            CONSTRAINT chk_quantities_valid CHECK (
                reserved_quantity + sold_quantity <= total_quantity
            )
        )
    """)
    op.execute("CREATE INDEX idx_inventory_sale_id ON inventory(sale_id)")

    # ── RESERVATIONS ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE reservations (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id             UUID NOT NULL REFERENCES users(id),
            sale_id             UUID NOT NULL REFERENCES sales(id),
            quantity            INTEGER NOT NULL DEFAULT 1,
            status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'confirmed', 'expired', 'cancelled')),
            idempotency_key     VARCHAR(255) NOT NULL UNIQUE,
            expires_at          TIMESTAMPTZ NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_active_reservation UNIQUE (user_id, sale_id)
        )
    """)
    op.execute("CREATE INDEX idx_reservations_expires_at ON reservations(expires_at)")
    op.execute("CREATE INDEX idx_reservations_status ON reservations(status)")
    op.execute("CREATE INDEX idx_reservations_user_sale ON reservations(user_id, sale_id)")

    # ── ORDERS ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE orders (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id             UUID NOT NULL REFERENCES users(id),
            sale_id             UUID NOT NULL REFERENCES sales(id),
            reservation_id      UUID NOT NULL UNIQUE REFERENCES reservations(id),
            quantity            INTEGER NOT NULL DEFAULT 1,
            unit_price          NUMERIC(10, 2) NOT NULL,
            total_price         NUMERIC(10, 2) NOT NULL,
            status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'paid', 'failed', 'refunded')),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_orders_user_id ON orders(user_id)")
    op.execute("CREATE INDEX idx_orders_status ON orders(status)")
    op.execute("CREATE INDEX idx_orders_reservation_id ON orders(reservation_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS orders")
    op.execute("DROP TABLE IF EXISTS reservations")
    op.execute("DROP TABLE IF EXISTS inventory")
    op.execute("DROP TABLE IF EXISTS sales")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute('DROP EXTENSION IF EXISTS "pgcrypto"')
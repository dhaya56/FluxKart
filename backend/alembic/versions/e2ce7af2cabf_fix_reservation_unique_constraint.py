"""fix_reservation_unique_constraint

Revision ID: e2ce7af2cabf
Revises: 5e2340f9f4d8
Create Date: 2026-03-05 22:08:50.325262

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2ce7af2cabf'
down_revision: Union[str, None] = '5e2340f9f4d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old constraint that blocks all duplicate user+sale combinations
    op.execute("""
        ALTER TABLE reservations 
        DROP CONSTRAINT uq_active_reservation
    """)

    # Add a partial unique index instead — only blocks ACTIVE reservations
    # Expired and cancelled reservations don't count
    op.execute("""
        CREATE UNIQUE INDEX uq_one_active_reservation_per_user_sale
        ON reservations (user_id, sale_id)
        WHERE status IN ('pending', 'confirmed')
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_one_active_reservation_per_user_sale")
    op.execute("""
        ALTER TABLE reservations
        ADD CONSTRAINT uq_active_reservation UNIQUE (user_id, sale_id)
    """)

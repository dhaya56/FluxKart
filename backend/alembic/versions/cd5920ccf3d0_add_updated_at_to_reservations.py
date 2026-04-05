"""add_updated_at_to_reservations

Revision ID: cd5920ccf3d0
Revises: 39a696bebe1d
Create Date: 2026-03-06 23:27:23.217534

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cd5920ccf3d0'
down_revision: Union[str, None] = '39a696bebe1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE reservations
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ
        DEFAULT NOW()
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE reservations
        DROP COLUMN IF EXISTS updated_at
    """)

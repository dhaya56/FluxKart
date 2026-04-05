"""add_preregistrations_table

Revision ID: 39a696bebe1d
Revises: e2ce7af2cabf
Create Date: 2026-03-06 22:27:10.730527

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39a696bebe1d'
down_revision: Union[str, None] = 'e2ce7af2cabf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE preregistrations (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id),
            sale_id     UUID NOT NULL REFERENCES sales(id),
            registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            admitted_at   TIMESTAMPTZ,
            status      VARCHAR(20) NOT NULL DEFAULT 'waiting',
            CONSTRAINT uq_preregistration UNIQUE (user_id, sale_id)
        )
    """)

    op.execute("""
        CREATE INDEX idx_preregistrations_sale_status
        ON preregistrations (sale_id, status)
    """)

    op.execute("""
        CREATE INDEX idx_preregistrations_registered_at
        ON preregistrations (sale_id, registered_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS preregistrations")

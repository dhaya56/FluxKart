"""add_is_admin_to_users

Revision ID: 7655698889d7
Revises: cd5920ccf3d0
Create Date: 2026-03-14 16:55:50.577286

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7655698889d7'
down_revision: Union[str, None] = 'cd5920ccf3d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
    """)
    op.execute("""
        UPDATE users SET is_admin = TRUE WHERE email = 'dhaya@fluxkart.com';
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_admin;")

"""add_outbox_events_table

Revision ID: 6689b0865305
Revises: 7655698889d7
Create Date: 2026-04-02 19:05:27.936668

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6689b0865305'
down_revision: Union[str, None] = '7655698889d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS outbox_events (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            aggregate_type  TEXT        NOT NULL,
            aggregate_id    UUID        NOT NULL,
            event_type      TEXT        NOT NULL,
            payload         JSONB       NOT NULL,
            published       BOOLEAN     NOT NULL DEFAULT FALSE,
            retry_count     INTEGER     NOT NULL DEFAULT 0,
            last_error      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at    TIMESTAMPTZ
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_outbox_unpublished
        ON outbox_events (created_at)
        WHERE published = FALSE;
    """)

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_outbox_unpublished;")
    op.execute("DROP TABLE IF EXISTS outbox_events;")

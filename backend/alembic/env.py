import os
import sys
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from alembic import context

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Raw SQL migrations — no ORM models needed
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=settings.postgres_dsn_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        settings.postgres_dsn_sync,
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
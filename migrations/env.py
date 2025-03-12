import asyncio
import logging
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

# Add the src directory to the path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import models to ensure they are registered
from src.mcp.models.base import Base
import src.mcp.models.models  # This will import all models that inherit from Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Get database URL from environment or use a default
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/mcp"
)
ASYNC_SQLALCHEMY_DATABASE_URL = os.getenv(
    "ASYNC_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/mcp"
)

# Set the database URL in the config
config.set_main_option("sqlalchemy.url", SQLALCHEMY_DATABASE_URL)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)


async def run_async_migrations() -> None:
    """Run migrations in an async context."""
    config_section = config.get_section(config.config_ini_section)
    if config_section is None:
        config_section = {}
    config_section["sqlalchemy.url"] = ASYNC_SQLALCHEMY_DATABASE_URL
    
    connectable = AsyncEngine(
        engine_from_config(
            config_section,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
            future=True,
        )
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations() -> None:
    """Run migrations based on whether we should use async mode or not."""
    use_async = os.getenv("USE_ASYNC_MIGRATION", "false").lower() == "true"
    
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        if use_async:
            asyncio.run(run_async_migrations())
        else:
            run_migrations_online()


# Run migrations when the script is executed
if __name__ == "__main__":
    run_migrations()
else:
    # When called from alembic command
    run_migrations()


"""Durable checkpointing on Postgres. A pod restart mid-run resumes instead of
re-cloning the repo or re-opening a duplicate PR. InMemorySaver is for tests only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from vulnagent.config import get_settings


@asynccontextmanager
async def postgres_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()
        yield saver

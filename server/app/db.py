from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional

import asyncpg

from server.app.config import get_settings


class Database:
    def __init__(self) -> None:
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self.pool is None:
            self.pool = await asyncpg.create_pool(get_settings().database_url, min_size=1, max_size=10)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        if self.pool is None:
            raise RuntimeError("Database pool is not initialized")
        async with self.pool.acquire() as connection:
            yield connection


db = Database()

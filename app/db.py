from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Base


logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(max_attempts: int = 30, retry_delay_seconds: float = 1.0) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(
                    text(
                        "ALTER TABLE projects "
                        "ADD COLUMN IF NOT EXISTS deleted BOOLEAN NOT NULL DEFAULT false"
                    )
                )
            return
        except (ConnectionRefusedError, OSError, OperationalError) as exc:
            if attempt == max_attempts:
                raise
            logger.warning(
                "Database connection failed during startup; retrying in %.1fs "
                "(attempt %s/%s): %s",
                retry_delay_seconds,
                attempt,
                max_attempts,
                exc,
            )
            await asyncio.sleep(retry_delay_seconds)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session

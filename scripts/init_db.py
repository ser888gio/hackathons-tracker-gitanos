from __future__ import annotations

import asyncio

from app.db import init_db


async def main() -> None:
    await init_db()


if __name__ == "__main__":
    asyncio.run(main())

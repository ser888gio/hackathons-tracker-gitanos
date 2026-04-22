from __future__ import annotations

import asyncio
import json

from app.pipeline import run_pipeline


async def main() -> None:
    result = await run_pipeline()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

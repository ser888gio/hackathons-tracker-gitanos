from __future__ import annotations

import asyncio
import json

from app.scraper import scrape_devpost_projects


async def main() -> None:
    projects = await scrape_devpost_projects()
    print(json.dumps(projects, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

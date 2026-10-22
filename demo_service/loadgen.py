"""Steady synthetic traffic against the demo service."""

import asyncio
import os

import httpx

URL = os.getenv("TARGET_URL", "http://localhost:8001")
RPS = float(os.getenv("RPS", "10"))


async def main() -> None:
    async with httpx.AsyncClient(base_url=URL, timeout=30) as c:

        async def hit() -> None:
            try:
                await c.get("/checkout")
            except httpx.HTTPError:
                pass

        while True:
            asyncio.create_task(hit())
            await asyncio.sleep(1 / RPS)


if __name__ == "__main__":
    asyncio.run(main())

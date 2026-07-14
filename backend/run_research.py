#!/usr/bin/env python3
"""CLI entrypoint for running the research pipeline."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import init_db
from pipeline.run import run_pipeline


async def main() -> None:
    await init_db()
    briefing = await run_pipeline()
    print(f"Briefing generated: {briefing.summary[:120]}...")


if __name__ == "__main__":
    asyncio.run(main())

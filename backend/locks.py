from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta

from database import connect_db
from time_utils import parse_datetime, utc_now, utc_now_iso

logger = logging.getLogger(__name__)

LOCK_BRIEFING = "briefing"
LOCK_CATALYST_SCAN = "catalyst_scan"
DEFAULT_TTL_SECONDS = 3600


def _holder_id(process_name: str) -> str:
    return f"{process_name}:{os.getpid()}"


async def try_acquire_lock(
    lock_name: str,
    holder: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> bool:
    now = utc_now()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            "SELECT holder, expires_at FROM job_locks WHERE name = ?",
            (lock_name,),
        )
        row = await cursor.fetchone()
        if row:
            existing_holder, existing_expires = row[0], row[1]
            expires = parse_datetime(existing_expires)
            if expires > now and existing_holder != holder:
                await db.execute("ROLLBACK")
                return False

        await db.execute(
            """
            INSERT INTO job_locks (name, holder, acquired_at, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                holder = excluded.holder,
                acquired_at = excluded.acquired_at,
                expires_at = excluded.expires_at
            """,
            (lock_name, holder, utc_now_iso(), expires_at),
        )
        cursor = await db.execute("SELECT holder FROM job_locks WHERE name = ?", (lock_name,))
        acquired = await cursor.fetchone()
        if acquired and acquired[0] == holder:
            await db.commit()
            return True
        await db.execute("ROLLBACK")
        return False


async def release_lock(lock_name: str, holder: str) -> None:
    async with connect_db() as db:
        await db.execute(
            "DELETE FROM job_locks WHERE name = ? AND holder = ?",
            (lock_name, holder),
        )
        await db.commit()


@asynccontextmanager
async def job_lock(lock_name: str, process_name: str, ttl_seconds: int = DEFAULT_TTL_SECONDS):
    holder = _holder_id(process_name)
    acquired = await try_acquire_lock(lock_name, holder, ttl_seconds=ttl_seconds)
    if not acquired:
        logger.info("Skipping %s — lock held by another process", lock_name)
        yield False
        return
    try:
        yield True
    finally:
        await release_lock(lock_name, holder)

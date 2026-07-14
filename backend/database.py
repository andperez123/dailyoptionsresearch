from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import aiosqlite

from config import settings
from models import (
    BriefingContent,
    BriefingRecord,
    BriefingSummary,
    CalendarEvent,
    DeepDiveResponse,
    MarketSnapshot,
    ScoredCatalyst,
)
from time_utils import parse_datetime, utc_now, utc_now_iso


def _ensure_data_dir() -> None:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def connect_db() -> AsyncIterator[aiosqlite.Connection]:
    _ensure_data_dir()
    db = await aiosqlite.connect(settings.database_path)
    try:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=30000")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA foreign_keys=ON")
        yield db
    finally:
        await db.close()


def _parse_dt(value: str | None) -> datetime:
    return parse_datetime(value)


async def init_db() -> None:
    _ensure_data_dir()
    async with connect_db() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                briefing_date TEXT NOT NULL UNIQUE,
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS ticker_mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mention_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                mention_count INTEGER NOT NULL,
                UNIQUE(mention_date, ticker)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_headlines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                external_id TEXT NOT NULL,
                headline TEXT NOT NULL,
                summary TEXT,
                url TEXT,
                published_at TEXT NOT NULL,
                content_hash TEXT NOT NULL UNIQUE,
                raw_payload TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(provider, external_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS catalyst_clusters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_key TEXT NOT NULL UNIQUE,
                canonical_title TEXT NOT NULL,
                primary_ticker TEXT,
                first_detected TEXT NOT NULL,
                last_updated TEXT NOT NULL,
                supporting_source_count INTEGER DEFAULT 1,
                status TEXT DEFAULT 'active'
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS scored_catalysts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id INTEGER,
                headline TEXT NOT NULL,
                summary TEXT,
                source_name TEXT,
                source_url TEXT,
                published_at TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                primary_ticker TEXT,
                related_tickers_json TEXT,
                sectors_json TEXT,
                direction TEXT,
                catalyst_type TEXT,
                impact_score INTEGER DEFAULT 0,
                confidence_score INTEGER DEFAULT 0,
                novelty_score INTEGER DEFAULT 0,
                current_market_reaction TEXT,
                thesis TEXT,
                confirmation_signals_json TEXT,
                invalidation_signals_json TEXT,
                key_risks_json TEXT,
                strategy_classification TEXT,
                half_life TEXT,
                supporting_source_count INTEGER DEFAULT 1,
                market_reaction_snapshot_json TEXT,
                model_version TEXT,
                scoring_version TEXT,
                scored INTEGER DEFAULT 1,
                FOREIGN KEY(cluster_id) REFERENCES catalyst_clusters(id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                price REAL,
                pct_change REAL,
                volume INTEGER,
                relative_volume REAL,
                implied_volatility REAL,
                snapshot_at TEXT NOT NULL,
                provider TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sports_odds_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL,
                sport TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                commence_time TEXT NOT NULL,
                market TEXT NOT NULL,
                bookmaker TEXT NOT NULL,
                line_json TEXT NOT NULL,
                snapshot_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS catalyst_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalyst_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(catalyst_id) REFERENCES scored_catalysts(id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                event_date TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(ticker, event_type, title, event_date)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS deep_dive_cache (
                ticker TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                cached_until TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS job_locks (
                name TEXT PRIMARY KEY,
                holder TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_scored_catalysts_detected ON scored_catalysts(detected_at DESC)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_scored_catalysts_ticker ON scored_catalysts(primary_ticker)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol ON market_snapshots(symbol, snapshot_at DESC)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_scored_catalysts_cluster ON scored_catalysts(cluster_id)"
        )
        await db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_scored_catalysts_cluster_unique
            ON scored_catalysts(cluster_id) WHERE cluster_id IS NOT NULL
            """
        )
        await db.commit()


# --- V1 briefing helpers (unchanged) ---

async def save_briefing(briefing_date: date, content: BriefingContent) -> int:
    _ensure_data_dir()
    payload = content.model_dump(mode="json")
    created_at = utc_now_iso()
    async with connect_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO briefings (briefing_date, content_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(briefing_date) DO UPDATE SET
                content_json = excluded.content_json,
                created_at = excluded.created_at
            """,
            (briefing_date.isoformat(), json.dumps(payload), created_at),
        )
        await db.commit()
        return cursor.lastrowid or 0


async def get_briefing_by_date(briefing_date: date) -> BriefingRecord | None:
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, briefing_date, content_json, created_at FROM briefings WHERE briefing_date = ?",
            (briefing_date.isoformat(),),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        content = BriefingContent.model_validate(json.loads(row["content_json"]))
        return BriefingRecord(
            id=row["id"],
            briefing_date=date.fromisoformat(row["briefing_date"]),
            content=content,
            created_at=_parse_dt(row["created_at"]),
        )


async def get_latest_briefing() -> BriefingRecord | None:
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, briefing_date, content_json, created_at
            FROM briefings ORDER BY briefing_date DESC LIMIT 1
            """
        )
        row = await cursor.fetchone()
        if not row:
            return None
        content = BriefingContent.model_validate(json.loads(row["content_json"]))
        return BriefingRecord(
            id=row["id"],
            briefing_date=date.fromisoformat(row["briefing_date"]),
            content=content,
            created_at=_parse_dt(row["created_at"]),
        )


async def list_briefings(limit: int = 30) -> list[BriefingSummary]:
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, briefing_date, content_json, created_at
            FROM briefings ORDER BY briefing_date DESC LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        summaries: list[BriefingSummary] = []
        for row in rows:
            content = json.loads(row["content_json"])
            summaries.append(
                BriefingSummary(
                    id=row["id"],
                    briefing_date=date.fromisoformat(row["briefing_date"]),
                    summary=content.get("summary", ""),
                    narrative_count=len(content.get("narratives", [])),
                    created_at=_parse_dt(row["created_at"]),
                )
            )
        return summaries


async def save_ticker_mentions(mention_date: date, counts: dict[str, int]) -> None:
    async with connect_db() as db:
        for ticker, count in counts.items():
            await db.execute(
                """
                INSERT INTO ticker_mentions (mention_date, ticker, mention_count)
                VALUES (?, ?, ?)
                ON CONFLICT(mention_date, ticker) DO UPDATE SET mention_count = excluded.mention_count
                """,
                (mention_date.isoformat(), ticker.upper(), count),
            )
        await db.commit()


async def get_ticker_mentions(mention_date: date) -> dict[str, int]:
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT ticker, mention_count FROM ticker_mentions WHERE mention_date = ?",
            (mention_date.isoformat(),),
        )
        rows = await cursor.fetchall()
        return {row["ticker"]: row["mention_count"] for row in rows}


async def set_pipeline_state(key: str, value: str) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO pipeline_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        await db.commit()


async def get_pipeline_state(key: str) -> str | None:
    async with connect_db() as db:
        cursor = await db.execute("SELECT value FROM pipeline_state WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None


# --- V2 catalyst helpers ---

def _row_to_catalyst(row: aiosqlite.Row) -> ScoredCatalyst:
    return ScoredCatalyst(
        id=row["id"],
        cluster_id=row["cluster_id"],
        headline=row["headline"],
        summary=row["summary"] or "",
        source_name=row["source_name"] or "",
        source_url=row["source_url"] or "",
        published_at=_parse_dt(row["published_at"]),
        detected_at=_parse_dt(row["detected_at"]),
        primary_ticker=row["primary_ticker"],
        related_tickers=json.loads(row["related_tickers_json"] or "[]"),
        sectors=json.loads(row["sectors_json"] or "[]"),
        direction=row["direction"] or "neutral",
        catalyst_type=row["catalyst_type"] or "other",
        impact_score=row["impact_score"] or 0,
        confidence_score=row["confidence_score"] or 0,
        novelty_score=row["novelty_score"] or 0,
        current_market_reaction=row["current_market_reaction"],
        thesis=row["thesis"] or "",
        confirmation_signals=json.loads(row["confirmation_signals_json"] or "[]"),
        invalidation_signals=json.loads(row["invalidation_signals_json"] or "[]"),
        key_risks=json.loads(row["key_risks_json"] or "[]"),
        strategy_classification=row["strategy_classification"] or "event_watchlist",
        half_life=row["half_life"] or "intraday",
        supporting_source_count=row["supporting_source_count"] or 1,
        market_reaction_snapshot=json.loads(row["market_reaction_snapshot_json"] or "{}"),
        model_version=row["model_version"] or settings.catalyst_model_version,
        scoring_version=row["scoring_version"] or settings.catalyst_scoring_version,
        scored=bool(row["scored"]),
    )


async def insert_raw_headline(
    provider: str,
    external_id: str,
    headline: str,
    summary: str,
    url: str,
    published_at: datetime,
    content_hash: str,
    raw_payload: dict[str, Any],
) -> Optional[int]:
    created_at = utc_now_iso()
    async with connect_db() as db:
        try:
            cursor = await db.execute(
                """
                INSERT INTO raw_headlines
                (provider, external_id, headline, summary, url, published_at, content_hash, raw_payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider,
                    external_id,
                    headline,
                    summary,
                    url,
                    published_at.isoformat(),
                    content_hash,
                    json.dumps(raw_payload),
                    created_at,
                ),
            )
            await db.commit()
            return cursor.lastrowid
        except aiosqlite.IntegrityError:
            return None


async def headline_exists(content_hash: str) -> bool:
    async with connect_db() as db:
        cursor = await db.execute(
            "SELECT 1 FROM raw_headlines WHERE content_hash = ? LIMIT 1",
            (content_hash,),
        )
        return await cursor.fetchone() is not None


async def upsert_cluster(
    cluster_key: str,
    canonical_title: str,
    primary_ticker: Optional[str],
) -> tuple[int, int]:
    now = utc_now_iso()
    async with connect_db() as db:
        cursor = await db.execute(
            "SELECT id, supporting_source_count FROM catalyst_clusters WHERE cluster_key = ?",
            (cluster_key,),
        )
        row = await cursor.fetchone()
        if row:
            cluster_id, count = row[0], row[1]
            new_count = count + 1
            await db.execute(
                """
                UPDATE catalyst_clusters
                SET last_updated = ?, supporting_source_count = ?, canonical_title = ?
                WHERE id = ?
                """,
                (now, new_count, canonical_title, cluster_id),
            )
            await db.commit()
            return cluster_id, new_count

        cursor = await db.execute(
            """
            INSERT INTO catalyst_clusters
            (cluster_key, canonical_title, primary_ticker, first_detected, last_updated, supporting_source_count)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (cluster_key, canonical_title, primary_ticker, now, now),
        )
        await db.commit()
        return cursor.lastrowid or 0, 1


async def upsert_scored_catalyst(catalyst: dict[str, Any]) -> int:
    async with connect_db() as db:
        cluster_id = catalyst.get("cluster_id")
        params = (
            catalyst.get("cluster_id"),
            catalyst["headline"],
            catalyst.get("summary", ""),
            catalyst.get("source_name", ""),
            catalyst.get("source_url", ""),
            catalyst["published_at"],
            catalyst["detected_at"],
            catalyst.get("primary_ticker"),
            json.dumps(catalyst.get("related_tickers", [])),
            json.dumps(catalyst.get("sectors", [])),
            catalyst.get("direction", "neutral"),
            catalyst.get("catalyst_type", "other"),
            catalyst.get("impact_score", 0),
            catalyst.get("confidence_score", 0),
            catalyst.get("novelty_score", 0),
            catalyst.get("current_market_reaction"),
            catalyst.get("thesis", ""),
            json.dumps(catalyst.get("confirmation_signals", [])),
            json.dumps(catalyst.get("invalidation_signals", [])),
            json.dumps(catalyst.get("key_risks", [])),
            catalyst.get("strategy_classification", "event_watchlist"),
            catalyst.get("half_life", "intraday"),
            catalyst.get("supporting_source_count", 1),
            json.dumps(catalyst.get("market_reaction_snapshot", {})),
            catalyst.get("model_version", settings.catalyst_model_version),
            catalyst.get("scoring_version", settings.catalyst_scoring_version),
            1 if catalyst.get("scored", True) else 0,
        )
        if cluster_id:
            cursor = await db.execute(
                """
                INSERT INTO scored_catalysts (
                    cluster_id, headline, summary, source_name, source_url, published_at, detected_at,
                    primary_ticker, related_tickers_json, sectors_json, direction, catalyst_type,
                    impact_score, confidence_score, novelty_score, current_market_reaction, thesis,
                    confirmation_signals_json, invalidation_signals_json, key_risks_json,
                    strategy_classification, half_life, supporting_source_count,
                    market_reaction_snapshot_json, model_version, scoring_version, scored
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    headline = excluded.headline,
                    summary = excluded.summary,
                    source_name = excluded.source_name,
                    source_url = excluded.source_url,
                    published_at = excluded.published_at,
                    detected_at = excluded.detected_at,
                    primary_ticker = excluded.primary_ticker,
                    related_tickers_json = excluded.related_tickers_json,
                    sectors_json = excluded.sectors_json,
                    direction = excluded.direction,
                    catalyst_type = excluded.catalyst_type,
                    impact_score = excluded.impact_score,
                    confidence_score = excluded.confidence_score,
                    novelty_score = excluded.novelty_score,
                    current_market_reaction = excluded.current_market_reaction,
                    thesis = excluded.thesis,
                    confirmation_signals_json = excluded.confirmation_signals_json,
                    invalidation_signals_json = excluded.invalidation_signals_json,
                    key_risks_json = excluded.key_risks_json,
                    strategy_classification = excluded.strategy_classification,
                    half_life = excluded.half_life,
                    supporting_source_count = excluded.supporting_source_count,
                    market_reaction_snapshot_json = excluded.market_reaction_snapshot_json,
                    model_version = excluded.model_version,
                    scoring_version = excluded.scoring_version,
                    scored = excluded.scored
                """,
                params,
            )
        else:
            cursor = await db.execute(
                """
                INSERT INTO scored_catalysts (
                    cluster_id, headline, summary, source_name, source_url, published_at, detected_at,
                    primary_ticker, related_tickers_json, sectors_json, direction, catalyst_type,
                    impact_score, confidence_score, novelty_score, current_market_reaction, thesis,
                    confirmation_signals_json, invalidation_signals_json, key_risks_json,
                    strategy_classification, half_life, supporting_source_count,
                    market_reaction_snapshot_json, model_version, scoring_version, scored
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
        await db.commit()
        if cursor.lastrowid:
            return cursor.lastrowid
        if cluster_id:
            lookup = await db.execute(
                "SELECT id FROM scored_catalysts WHERE cluster_id = ?",
                (cluster_id,),
            )
            row = await lookup.fetchone()
            return row[0] if row else 0
        return 0


async def insert_scored_catalyst(catalyst: dict[str, Any]) -> int:
    return await upsert_scored_catalyst(catalyst)


async def list_wire_catalysts(
    page: int = 1,
    page_size: int = 30,
    min_impact: int = 0,
    min_confidence: int = 0,
    ticker: Optional[str] = None,
    direction: Optional[str] = None,
    catalyst_type: Optional[str] = None,
    half_life: Optional[str] = None,
    scored_only: bool = True,
) -> tuple[list[ScoredCatalyst], int]:
    clauses = ["impact_score >= ?", "confidence_score >= ?"]
    params: list[Any] = [min_impact, min_confidence]
    if scored_only:
        clauses.append("scored = 1")
    if ticker:
        ticker_upper = ticker.upper()
        clauses.append(
            "(primary_ticker = ? OR EXISTS ("
            "SELECT 1 FROM json_each(related_tickers_json) WHERE value = ?"
            "))"
        )
        params.extend([ticker_upper, ticker_upper])
    if direction:
        clauses.append("direction = ?")
        params.append(direction)
    if catalyst_type:
        clauses.append("catalyst_type = ?")
        params.append(catalyst_type)
    if half_life:
        clauses.append("half_life = ?")
        params.append(half_life)

    where = " AND ".join(clauses)
    offset = (page - 1) * page_size
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        count_cursor = await db.execute(
            f"SELECT COUNT(*) FROM scored_catalysts WHERE {where}",
            params,
        )
        total = (await count_cursor.fetchone())[0]
        cursor = await db.execute(
            f"""
            SELECT * FROM scored_catalysts WHERE {where}
            ORDER BY impact_score DESC, confidence_score DESC, detected_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        )
        rows = await cursor.fetchall()
        return [_row_to_catalyst(row) for row in rows], total


async def get_catalyst_by_id(catalyst_id: int) -> Optional[ScoredCatalyst]:
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM scored_catalysts WHERE id = ?", (catalyst_id,))
        row = await cursor.fetchone()
        return _row_to_catalyst(row) if row else None


async def get_recent_catalysts_for_ticker(ticker: str, limit: int = 10) -> list[ScoredCatalyst]:
    ticker_upper = ticker.upper()
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM scored_catalysts
            WHERE primary_ticker = ? OR EXISTS (
                SELECT 1 FROM json_each(related_tickers_json) WHERE value = ?
            )
            ORDER BY detected_at DESC LIMIT ?
            """,
            (ticker_upper, ticker_upper, limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_catalyst(row) for row in rows]


async def get_top_catalysts_since(since: datetime, limit: int = 20) -> list[ScoredCatalyst]:
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM scored_catalysts
            WHERE detected_at >= ? AND scored = 1
            ORDER BY impact_score DESC, confidence_score DESC
            LIMIT ?
            """,
            (since.isoformat(), limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_catalyst(row) for row in rows]


async def save_market_snapshot(snapshot: MarketSnapshot) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO market_snapshots
            (symbol, price, pct_change, volume, relative_volume, implied_volatility, snapshot_at, provider)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.symbol,
                snapshot.price,
                snapshot.pct_change,
                snapshot.volume,
                snapshot.relative_volume,
                snapshot.implied_volatility,
                snapshot.snapshot_at.isoformat(),
                snapshot.provider,
            ),
        )
        await db.commit()


async def get_latest_market_snapshots(symbols: list[str]) -> list[MarketSnapshot]:
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        results: list[MarketSnapshot] = []
        for symbol in symbols:
            cursor = await db.execute(
                """
                SELECT * FROM market_snapshots
                WHERE symbol = ? ORDER BY snapshot_at DESC LIMIT 1
                """,
                (symbol,),
            )
            row = await cursor.fetchone()
            if row:
                results.append(
                    MarketSnapshot(
                        symbol=row["symbol"],
                        price=row["price"],
                        pct_change=row["pct_change"],
                        volume=row["volume"],
                        relative_volume=row["relative_volume"],
                        implied_volatility=row["implied_volatility"],
                        snapshot_at=_parse_dt(row["snapshot_at"]),
                        provider=row["provider"],
                    )
                )
        return results


async def save_sports_odds_snapshot(
    event_key: str,
    sport: str,
    home_team: str,
    away_team: str,
    commence_time: str,
    market: str,
    bookmaker: str,
    line: dict[str, Any],
) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO sports_odds_snapshots
            (event_key, sport, home_team, away_team, commence_time, market, bookmaker, line_json, snapshot_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_key,
                sport,
                home_team,
                away_team,
                commence_time,
                market,
                bookmaker,
                json.dumps(line),
                utc_now_iso(),
            ),
        )
        await db.commit()


async def get_sports_odds_history(event_key: str, market: str, limit: int = 20) -> list[dict[str, Any]]:
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM sports_odds_snapshots
            WHERE event_key = ? AND market = ?
            ORDER BY snapshot_at ASC LIMIT ?
            """,
            (event_key, market, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "bookmaker": row["bookmaker"],
                "line": json.loads(row["line_json"]),
                "snapshot_at": row["snapshot_at"],
            }
            for row in rows
        ]


async def save_calendar_events(events: list[CalendarEvent]) -> None:
    now = utc_now_iso()
    async with connect_db() as db:
        for event in events:
            metadata = {
                "iv_level": event.iv_level,
                "recent_catalyst_score": event.recent_catalyst_score,
                "recent_price_change": event.recent_price_change,
                "vol_context": event.vol_context,
            }
            await db.execute(
                """
                INSERT INTO calendar_events (ticker, event_type, title, event_date, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, event_type, title, event_date) DO NOTHING
                """,
                (
                    event.ticker,
                    event.event_type,
                    event.title,
                    event.event_date.isoformat(),
                    json.dumps(metadata),
                    now,
                ),
            )
        await db.commit()


async def list_calendar_events(
    days: int = 7,
    tickers: Optional[list[str]] = None,
) -> list[CalendarEvent]:
    start = date.today()
    end = start + timedelta(days=days)
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        if tickers:
            placeholders = ",".join("?" for _ in tickers)
            cursor = await db.execute(
                f"""
                SELECT * FROM calendar_events
                WHERE event_date >= ? AND event_date <= ?
                AND ticker IN ({placeholders})
                ORDER BY event_date ASC
                """,
                [start.isoformat(), end.isoformat(), *[t.upper() for t in tickers]],
            )
        else:
            cursor = await db.execute(
                """
                SELECT * FROM calendar_events
                WHERE event_date >= ? AND event_date <= ?
                ORDER BY event_date ASC
                """,
                (start.isoformat(), end.isoformat()),
            )
        rows = await cursor.fetchall()
        events: list[CalendarEvent] = []
        for row in rows:
            meta = json.loads(row["metadata_json"] or "{}")
            events.append(
                CalendarEvent(
                    ticker=row["ticker"],
                    event_type=row["event_type"],
                    title=row["title"],
                    event_date=date.fromisoformat(row["event_date"]),
                    iv_level=meta.get("iv_level"),
                    recent_catalyst_score=meta.get("recent_catalyst_score"),
                    recent_price_change=meta.get("recent_price_change"),
                    vol_context=meta.get("vol_context"),
                )
            )
        return events


async def save_catalyst_feedback(catalyst_id: int, label: str, notes: str = "") -> int:
    created_at = utc_now_iso()
    async with connect_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO catalyst_feedback (catalyst_id, label, notes, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (catalyst_id, label, notes, created_at),
        )
        await db.commit()
        return cursor.lastrowid or 0


async def get_deep_dive_cache(ticker: str) -> Optional[DeepDiveResponse]:
    async with connect_db() as db:
        cursor = await db.execute(
            "SELECT payload_json, cached_until FROM deep_dive_cache WHERE ticker = ?",
            (ticker.upper(),),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        cached_until = _parse_dt(row[1])
        if cached_until < utc_now():
            return None
        return DeepDiveResponse.model_validate(json.loads(row[0]))


async def set_deep_dive_cache(ticker: str, payload: DeepDiveResponse) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO deep_dive_cache (ticker, payload_json, cached_until)
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                payload_json = excluded.payload_json,
                cached_until = excluded.cached_until
            """,
            (ticker.upper(), payload.model_dump_json(), payload.cached_until.isoformat()),
        )
        await db.commit()


async def cleanup_old_data(days: int = 30) -> None:
    cutoff = (utc_now() - timedelta(days=days)).isoformat()
    async with connect_db() as db:
        await db.execute("DELETE FROM market_snapshots WHERE snapshot_at < ?", (cutoff,))
        await db.execute("DELETE FROM sports_odds_snapshots WHERE snapshot_at < ?", (cutoff,))
        await db.execute("DELETE FROM raw_headlines WHERE created_at < ?", (cutoff,))
        await db.execute(
            """
            DELETE FROM scored_catalysts
            WHERE detected_at < ? AND impact_score < ?
            """,
            (cutoff, settings.minimum_wire_impact_score),
        )
        await db.commit()

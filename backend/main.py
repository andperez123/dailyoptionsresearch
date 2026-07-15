from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from database import (
    get_briefing_by_date,
    get_deep_dive_cache,
    get_latest_briefing,
    get_latest_market_snapshots,
    get_pipeline_state,
    get_catalyst_by_id,
    init_db,
    list_briefings,
    list_calendar_events,
    list_wire_catalysts,
    save_catalyst_feedback,
)
from models import (
    BriefingRecord,
    BriefingSummary,
    CalendarEvent,
    CatalystFeedbackRecord,
    CatalystFeedbackRequest,
    DeepDiveResponse,
    PulseResponse,
    ResearchStatus,
    SportsBoardResponse,
    WireResponse,
)
from pipeline.catalyst import build_deep_dive, run_catalyst_scan
from pipeline.market_data import market_status_now
from pipeline.run import run_pipeline
from pipeline.sports import build_sports_board
from time_utils import utc_now

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

_pipeline_lock = asyncio.Lock()


def _cors_origins() -> list[str]:
    origins = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if railway_domain:
        origins.append(f"https://{railway_domain}")
    extra = os.environ.get("ALLOWED_ORIGINS", "")
    origins.extend(origin.strip() for origin in extra.split(",") if origin.strip())
    return origins


async def require_api_secret(x_api_secret: Optional[str] = Header(default=None)) -> None:
    if settings.api_secret and x_api_secret != settings.api_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing API secret")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Degen Catalyst Intelligence", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _run_pipeline_job() -> None:
    async with _pipeline_lock:
        try:
            await run_pipeline()
        except RuntimeError:
            pass


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "v2"}


@app.get("/api/briefing/latest", response_model=Optional[BriefingRecord])
async def latest_briefing():
    return await get_latest_briefing()


@app.get("/api/briefing/{briefing_date}", response_model=BriefingRecord)
async def briefing_by_date(briefing_date: date):
    record = await get_briefing_by_date(briefing_date)
    if not record:
        raise HTTPException(status_code=404, detail="Briefing not found for date")
    return record


@app.get("/api/briefings", response_model=list[BriefingSummary])
async def briefings(limit: int = Query(30, ge=1, le=100)):
    return await list_briefings(limit=limit)


@app.get("/api/status", response_model=ResearchStatus)
async def research_status():
    running = (await get_pipeline_state("running")) == "true"
    last_run_raw = await get_pipeline_state("last_run")
    last_error = await get_pipeline_state("last_error") or await get_pipeline_state("last_catalyst_error")
    message = await get_pipeline_state("message") or await get_pipeline_state("last_catalyst_result") or ""
    last_run = None
    if last_run_raw:
        last_run = datetime.fromisoformat(last_run_raw)
    elif scan := await get_pipeline_state("last_catalyst_scan"):
        last_run = datetime.fromisoformat(scan)
    return ResearchStatus(
        running=running,
        last_run=last_run,
        last_error=last_error or None,
        message=message,
    )


@app.post("/api/research/run", response_model=ResearchStatus, dependencies=[Depends(require_api_secret)])
async def trigger_research(background_tasks: BackgroundTasks):
    if (await get_pipeline_state("running")) == "true":
        return ResearchStatus(running=True, message="Research already in progress")
    background_tasks.add_task(_run_pipeline_job)
    return ResearchStatus(running=True, message="Research started")


@app.get("/api/wire", response_model=WireResponse)
async def get_wire(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    min_impact: int = Query(settings.minimum_wire_impact_score, ge=0, le=10),
    min_confidence: int = Query(settings.minimum_wire_confidence_score, ge=0, le=10),
    ticker: Optional[str] = None,
    direction: Optional[str] = None,
    catalyst_type: Optional[str] = None,
    half_life: Optional[str] = None,
):
    items, total = await list_wire_catalysts(
        page=page,
        page_size=page_size,
        min_impact=min_impact,
        min_confidence=min_confidence,
        ticker=ticker,
        direction=direction,
        catalyst_type=catalyst_type,
        half_life=half_life,
    )
    return WireResponse(items=items, total=total, page=page, page_size=page_size)


@app.post("/api/catalyst/scan", dependencies=[Depends(require_api_secret)])
async def trigger_catalyst_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_catalyst_scan)
    return {"status": "started"}


@app.get("/api/pulse", response_model=PulseResponse)
async def get_pulse():
    symbols = settings.pulse_symbols
    sector_symbols = settings.sector_etfs
    indices = await get_latest_market_snapshots(symbols)
    sectors = await get_latest_market_snapshots(sector_symbols)
    warnings: list[str] = []
    if not indices:
        warnings.append("No market snapshots yet — start worker with make worker")
    freshness = utc_now()
    if indices:
        freshness = max(s.snapshot_at for s in indices)
    return PulseResponse(
        indices=indices,
        sectors=sectors,
        market_status=market_status_now(),
        data_freshness=freshness,
        provider_warnings=warnings,
    )


@app.get("/api/calendar", response_model=list[CalendarEvent])
async def get_calendar(days: int = Query(7, ge=1, le=30), wire_only: bool = False):
    tickers = None
    if wire_only:
        items, _ = await list_wire_catalysts(page=1, page_size=50, min_impact=0, min_confidence=0)
        tickers = list({c.primary_ticker for c in items if c.primary_ticker})
    return await list_calendar_events(days=days, tickers=tickers)


@app.get("/api/deepdive/{ticker}", response_model=DeepDiveResponse, dependencies=[Depends(require_api_secret)])
async def get_deep_dive(ticker: str):
    cached = await get_deep_dive_cache(ticker)
    if cached:
        return cached
    return await build_deep_dive(ticker)


@app.get("/api/sports", response_model=SportsBoardResponse)
async def get_sports():
    return await build_sports_board()


@app.post("/api/catalysts/{catalyst_id}/feedback", response_model=CatalystFeedbackRecord)
async def post_catalyst_feedback(catalyst_id: int, body: CatalystFeedbackRequest):
    catalyst = await get_catalyst_by_id(catalyst_id)
    if not catalyst:
        raise HTTPException(status_code=404, detail="Catalyst not found")
    feedback_id = await save_catalyst_feedback(catalyst_id, body.label, body.notes)
    return CatalystFeedbackRecord(
        id=feedback_id,
        catalyst_id=catalyst_id,
        label=body.label,
        notes=body.notes,
        created_at=utc_now(),
    )


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Frontend not built")

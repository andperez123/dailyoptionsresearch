# Degen Catalyst Intelligence Terminal

Personal, local-first market intelligence terminal. V2 converts breaking news, market data, options activity, social momentum, and sports odds into **ranked catalyst signals** throughout the trading day — with observations separated from trade ideas.

**Not financial advice. Entertainment and research only.**

## V2 Architecture

- **Catalyst Engine** — ingest → dedupe → cluster → enrich with market reaction → score (impact + confidence separately)
- **Daily Briefing** — morning anchor synthesis using overnight catalyst clusters
- **Dedicated Worker** — reliable background jobs (not in-process FastAPI scheduler)
- **Signal-first UI** — Live Catalyst Wire, Market Pulse, Calendar, Deep Dive drawer, Sports Board

## Quick start

```bash
cd "Daily Options Research"
make setup

# Add keys to .env:
# OPENAI_API_KEY=sk-...
# FINNHUB_API_KEY=...   (free at finnhub.io)
# ODDS_API_KEY=...      (optional — sports board)

# Demo data (no keys needed)
make seed
make seed-catalysts

# Terminal 1: API + dashboard
make dev

# Terminal 2: background intelligence worker
make worker
```

Open http://127.0.0.1:8000

## Commands

| Command | Description |
|---------|-------------|
| `make setup` | Install Python + npm deps, copy `.env.example` |
| `make dev` | Build frontend + serve on :8000 |
| `make worker` | Start background catalyst worker (news, market, calendar, sports, briefing) |
| `make research` | Run daily briefing pipeline once |
| `make catalyst` | Run one catalyst scan manually |
| `make seed` | Demo daily briefing |
| `make seed-catalysts` | Demo catalyst wire signals |

## API (V2)

| Endpoint | Description |
|----------|-------------|
| `GET /api/wire` | Paginated catalyst signals (filter by impact, confidence, ticker, direction) |
| `GET /api/pulse` | SPY/QQQ/VIX + sectors, market status, data freshness |
| `GET /api/calendar` | Upcoming earnings/events |
| `GET /api/deepdive/{ticker}` | Ticker analysis (15min cache) |
| `GET /api/sports` | Sports board with odds + line movement |
| `POST /api/catalysts/{id}/feedback` | Label signal quality (useful/noise/etc) |
| `GET /api/briefing/latest` | Daily narrative briefing |
| `POST /api/research/run` | Trigger briefing |
| `POST /api/catalyst/scan` | Trigger one catalyst scan |

## Design principles

- **Signal-first** — headlines enriched with price/volume/IV before scoring
- **Observations ≠ trade ideas** — strategy classification, not premature strike-picking
- **Separate impact & confidence** — high impact + weak confirmation looks different from confirmed signals
- **Traceability** — raw headlines stored, model/scoring versions persisted
- **Graceful degradation** — works without Finnhub or Odds API keys

## Stack

- Python, FastAPI, SQLite, APScheduler worker, OpenAI
- React, Vite, Tailwind
- Finnhub, RSS, yfinance (provider-isolated), Reddit RSS, The Odds API

## Optional: auto-run at 8am (macOS)

```bash
cp scripts/com.degen.research.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.degen.research.plist
```

For continuous catalyst intelligence, prefer `make worker` over launchd for the scan jobs.

.PHONY: setup dev research build frontend-install backend-install seed worker catalyst

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

setup: backend-install frontend-install
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example — add your API keys"; fi

backend-install:
	python3 -m venv $(VENV)
	$(PIP) install -r backend/requirements.txt

frontend-install:
	cd frontend && npm install

dev: build
	cd backend && ../$(UVICORN) main:app --reload --host 127.0.0.1 --port 8000

worker:
	cd backend && ../$(PYTHON) worker.py

research:
	cd backend && ../$(PYTHON) run_research.py

catalyst:
	cd backend && ../$(PYTHON) -c "import asyncio; from pipeline.catalyst import run_catalyst_scan; print(asyncio.run(run_catalyst_scan()))"

seed:
	cd backend && ../$(PYTHON) seed_demo.py

seed-catalysts:
	cd backend && ../$(PYTHON) seed_catalysts.py

build:
	cd frontend && npm run build

frontend-dev:
	cd frontend && npm run dev

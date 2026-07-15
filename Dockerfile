FROM node:20-slim AS frontend

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci
COPY frontend ./frontend
RUN cd frontend && npm run build

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/data/briefings.db

COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY --from=frontend /app/frontend/dist ./frontend/dist

RUN mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health')"

CMD ["sh", "-c", "cd backend && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
